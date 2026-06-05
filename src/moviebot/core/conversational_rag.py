import asyncio
import hashlib
import json
import re
import time
from typing import Any, Dict, List, Optional


from moviebot.core.gemini_client import generate_gemini_content
from moviebot.core.embeddings import get_embedding_result, decode_vector, cosine_similarity
from moviebot.core.external_recommendations import (
    filter_external_recommendations,
    is_media_domain_question,
    parse_external_recommendations,
    remove_filtered_external_markers,
)
from moviebot.core.dedupe import normalize_title
from moviebot.db.connection import get_db_connection
from moviebot.db.repositories import LibraryItemRepository
from moviebot.core.user_memory_manager import UserMemoryManager
from moviebot.db.repositories import UserInteractionMemoryRepository

# Global cache instance for convenient reuse across components
global_rag_cache = None


def _parse_tags(val: Any) -> List[str]:
    """
    Robust helper to parse tags/fields stored as JSON lists, comma-separated lists, or individual strings.
    """
    if not val:
        return []
    if isinstance(val, list):
        return [str(x).strip() for x in val if x]
    if isinstance(val, str):
        val_stripped = val.strip()
        if val_stripped.startswith("[") and val_stripped.endswith("]"):
            try:
                parsed = json.loads(val_stripped)
                if isinstance(parsed, list):
                    return [str(x).strip() for x in parsed if x]
            except Exception:
                pass
        return [str(x).strip() for x in val.split(",") if x.strip()]
    return [str(val).strip()]


def _truncate_synopsis(syn: Optional[str]) -> Optional[str]:
    """
    Truncates a synopsis to the first two sentences or under 150 characters.
    """
    if not syn:
        return None
    # Strip whitespace
    syn_stripped = syn.strip()
    # Simple sentence boundary detection
    sentences = re.split(r'(?<=[.!?])\s+', syn_stripped)
    first_two = " ".join(sentences[:2])
    
    if len(first_two) > 150:
        return first_two[:147] + "..."
    return first_two


def minimize_movie_metadata(movie: Dict[str, Any]) -> Dict[str, Any]:
    """
    Minimizes a movie record's metadata to reduce token consumption during RAG processing.
    Keeps only key fields (Title, Year, Genres, top 3 tones/themes/awards/studios/directors)
    and truncates the synopsis to under 150 chars/2 sentences.
    """
    # Required core identifiers
    minimized: Dict[str, Any] = {
        "id": movie.get("id"),
        "title": movie.get("title"),
        "year": movie.get("year"),
    }

    # Normalize genres to a comma-separated list
    genres = _parse_tags(movie.get("genres"))
    if genres:
        minimized["genres"] = ", ".join(genres)

    # Optional tagline
    tagline = movie.get("tagline")
    if tagline:
        minimized["tagline"] = tagline.strip()

    # Truncate synopsis
    syn = movie.get("synopsis")
    if syn:
        minimized["synopsis"] = _truncate_synopsis(syn)

    # Slice tags to top 3
    for field, key in [
        ("tone_tags", "tones"),
        ("theme_tags", "themes"),
        ("award_tags", "awards"),
        ("studios", "studios"),
        ("directors", "directors"),
    ]:
        tags = _parse_tags(movie.get(field))
        if tags:
            minimized[key] = tags[:3]

    return minimized


def _is_rate_limit_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in ("429", "too many requests", "resource_exhausted", "rate limit"))


def _build_local_fallback_answer(candidates: List[Dict[str, Any]], reason: str) -> str:
    lines = [
        "The conversational model is temporarily rate-limited, so I pulled the strongest local library matches instead.",
        "",
    ]
    for movie in candidates[:5]:
        title = movie.get("title") or "Unknown title"
        year = f" ({movie.get('year')})" if movie.get("year") else ""
        details = []
        genres = _parse_tags(movie.get("genres"))
        directors = _parse_tags(movie.get("directors"))
        themes = _parse_tags(movie.get("theme_tags"))
        tones = _parse_tags(movie.get("tone_tags"))
        if genres:
            details.append(f"genres: {', '.join(genres[:3])}")
        if directors:
            details.append(f"directed by {', '.join(directors[:2])}")
        if themes:
            details.append(f"themes: {', '.join(themes[:3])}")
        if tones:
            details.append(f"tone: {', '.join(tones[:3])}")
        detail_text = f" - {'; '.join(details)}" if details else ""
        lines.append(f"- **{title}**{year}{detail_text}")
    lines.append("")
    lines.append(reason)
    return "\n".join(lines).strip()


def _inventory_title_queries(question: str) -> List[str]:
    text = (question or "").strip()
    if not text:
        return []

    cleaned = re.sub(r"[?!.]+$", "", text).strip()
    candidates = [cleaned]
    patterns = [
        r"^(?:do|did|can|could)\s+(?:i|we|you)\s+(?:already\s+)?(?:have|own|got)\s+(.+)$",
        r"^(?:have|got)\s+(?:i|we|you)\s+(?:already\s+)?(?:got\s+)?(.+)$",
        r"^is\s+(.+?)\s+(?:already\s+)?in\s+(?:my|our|the)\s+library$",
        r"^is\s+(.+?)\s+(?:already\s+)?(?:owned|available)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            candidates.append(match.group(1).strip())

    expanded = []
    for candidate in candidates:
        candidate = re.sub(r"\b(?:already|in my library|in our library|in the library)\b", "", candidate, flags=re.IGNORECASE)
        candidate = re.sub(r"\s+", " ", candidate).strip(" .?!")
        if candidate and candidate.lower() not in {c.lower() for c in expanded}:
            expanded.append(candidate)
    return expanded


def _is_inventory_question(question: str) -> bool:
    text = (question or "").lower()
    return any(
        phrase in text
        for phrase in (
            "do i have",
            "do we have",
            "already have",
            "in my library",
            "in our library",
            "in the library",
            "do i own",
            "do we own",
        )
    )


def _find_inventory_matches(question: str) -> List[Dict[str, Any]]:
    if not _is_inventory_question(question):
        return []
    matches_by_id: Dict[str, Dict[str, Any]] = {}
    for title_query in _inventory_title_queries(question):
        normalized = normalize_title(title_query)
        if not normalized:
            continue
        for item in LibraryItemRepository.search_by_normalized_title(normalized):
            item_id = item.get("id")
            if item_id:
                matches_by_id[item_id] = item
    return list(matches_by_id.values())


def _build_inventory_answer(matches: List[Dict[str, Any]]) -> str:
    if not matches:
        return ""
    lines = ["Yes, this is already in your local library:"]
    for movie in matches[:5]:
        title = movie.get("title") or "Unknown title"
        year = f" ({movie.get('year')})" if movie.get("year") else ""
        details = []
        resolution = movie.get("resolution")
        size_bytes = movie.get("size_bytes")
        if resolution:
            details.append(f"{resolution}p" if str(resolution).isdigit() else str(resolution))
        if size_bytes:
            details.append(f"{size_bytes / (1024 ** 3):.2f} GB")
        suffix = f" - {', '.join(details)}" if details else ""
        lines.append(f"- **{title}**{year}{suffix}")
    lines.append("")
    lines.append("I would treat another search/download for this title as a duplicate unless you are intentionally replacing it with a better version.")
    return "\n".join(lines)


class RAGQueryCache:
    """
    A thread-safe, async-capable, in-memory TTL cache for RAG queries.
    """
    def __init__(self, default_ttl_seconds: float = 300.0):
        self.default_ttl = default_ttl_seconds
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def _normalize_key(self, key: str) -> str:
        return key.strip().lower()

    async def get(self, key: str) -> Optional[Any]:
        normalized_key = self._normalize_key(key)
        async with self._lock:
            if normalized_key not in self._cache:
                return None
            entry = self._cache[normalized_key]
            if time.time() - entry["timestamp"] > entry["ttl"]:
                del self._cache[normalized_key]
                return None
            return entry["value"]

    async def set(self, key: str, value: Any, ttl: Optional[float] = None) -> None:
        normalized_key = self._normalize_key(key)
        ttl_val = ttl if ttl is not None else self.default_ttl
        async with self._lock:
            self._cache[normalized_key] = {
                "value": value,
                "timestamp": time.time(),
                "ttl": ttl_val
            }

    async def clear(self) -> None:
        async with self._lock:
            self._cache.clear()

    async def prune(self) -> None:
        """Evicts all expired keys from the cache."""
        now = time.time()
        async with self._lock:
            expired = [
                k for k, entry in self._cache.items()
                if now - entry["timestamp"] > entry["ttl"]
            ]
            for k in expired:
                del self._cache[k]


def get_global_rag_cache() -> RAGQueryCache:
    """
    Retrieves or initializes the global RAGQueryCache instance.
    """
    global global_rag_cache
    if global_rag_cache is None:
        global_rag_cache = RAGQueryCache()
    return global_rag_cache


async def _reformulate_query(question: str, chat_history: List[Dict[str, str]]) -> str:
    """
    Uses Gemini to reformulate a follow-up question into a standalone query.
    """
    history_lines = []
    for entry in chat_history:
        role = "User" if entry.get("role") == "user" else "Librarian"
        history_lines.append(f"{role}: {entry.get('text', '')}")
    history_str = "\n".join(history_lines)

    prompt = (
        "Given the following chat history and a follow-up question, rewrite the follow-up question "
        "to be a standalone, self-contained search query that preserves the original intent and "
        "resolves all pronouns/references. Do not include any explanation or introduction, return ONLY "
        "the rewritten question.\n\n"
        f"Chat History:\n{history_str}\n\n"
        f"Follow-up Question: \"{question}\"\n"
        "Standalone Question:"
    )

    try:
        reformulated = await generate_gemini_content(
            prompt=prompt,
            system_instruction="You are an expert search query contextualizer. You rewrite follow-up questions to be self-contained.",
            temperature=0.1
        )
        reformulated = reformulated.strip()
        # Clean up any quotes or markdown the model might have returned
        reformulated = reformulated.strip("\"'")
        if reformulated:
            return reformulated
    except Exception as e:
        print(f"[RAG] Warning: Query reformulation failed: {e}. Falling back to original question.")
    
    return question


async def query_library_conversational(
    question: str,
    chat_history: Optional[List[Dict[str, str]]] = None,
    discord_user_id: Optional[str] = None,
    known_users: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Performs a 2-stage conversational RAG search on the library items.
    Stage 1: Semantic search to retrieve the top 15 candidate movies.
    Stage 2: LLM reranking and conversational explanation using Gemini Flash.
    Caches the results to prevent repeated API calls.
    """
    if not is_media_domain_question(question, chat_history):
        return {
            "answer": "I can only help with movie, library, and media-download questions in this bot.",
            "cited_movie_ids": [],
            "external_recommendations": [],
        }

    inventory_matches = _find_inventory_matches(question)
    if inventory_matches:
        result = {
            "answer": _build_inventory_answer(inventory_matches),
            "cited_movie_ids": [m["id"] for m in inventory_matches[:5] if m.get("id")],
            "external_recommendations": [],
        }
        return result

    cache = get_global_rag_cache()
    
    cache_key = question
    if discord_user_id:
        cache_key = f"{discord_user_id}::{cache_key}"
    if chat_history:
        # Use a hash of the history to keep cache keys reasonable
        history_json = json.dumps(chat_history, sort_keys=True)
        history_hash = hashlib.sha256(history_json.encode("utf-8")).hexdigest()[:8]
        cache_key = f"{cache_key}::h:{history_hash}"

    cached = await cache.get(cache_key)
    if cached:
        return cached

    # If discord_user_id is provided, extract any new user preferences/facts in the background/inline
    memory_context = ""
    if discord_user_id:
        try:
            await UserMemoryManager.extract_and_save_memories(discord_user_id, question, known_users)
        except Exception as e:
            print(f"[RAG] Warning: User memory extraction failed: {e}")
        try:
            memory_context = UserMemoryManager.get_relevant_memories(discord_user_id, question)
        except Exception as e:
            print(f"[RAG] Warning: User memory retrieval failed: {e}")

    # Determine standalone question for search retrieval
    search_query = question
    if chat_history:
        search_query = await _reformulate_query(question, chat_history)

    # 1. Fetch query embedding
    try:
        embedding_result = await get_embedding_result(search_query)
    except Exception as e:
        err_msg = f"Failed to generate search query embedding: {str(e)}"
        return {"ok": False, "error": {"message": err_msg}}

    query_vector = embedding_result.vector

    # 2. Retrieve items with vectors from DB
    try:
        with get_db_connection() as conn:
            cursor = conn.execute("""
                SELECT id, title, year, genres, tagline, synopsis,
                       tone_tags, theme_tags, award_tags, studios, directors,
                       synopsis_vector, synopsis_vector_model, synopsis_vector_dim
                FROM library_items
                WHERE synopsis_vector IS NOT NULL
            """)
            raw_matches = [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        err_msg = f"Database error during candidate retrieval: {str(e)}"
        return {"ok": False, "error": {"message": err_msg}}

    if not raw_matches:
        ans = "I couldn't find any movie embeddings in your library. Please run sync-intelligence or sync-enrichment to build the embeddings."
        res = {"answer": ans, "cited_movie_ids": []}
        await cache.set(cache_key, res)
        return res

    # 3. Compute cosine similarity and filter by model/dimension
    candidates = []
    for item in raw_matches:
        if item.get("synopsis_vector_model") != embedding_result.model or item.get("synopsis_vector_dim") != embedding_result.dim:
            continue
        try:
            vector = decode_vector(item["synopsis_vector"])
            score = cosine_similarity(query_vector, vector)
            item["similarity_score"] = score
            candidates.append(item)
        except Exception:
            continue

    if not candidates:
        ans = "None of the movies in your library match the embedding model of your query. Please re-run sync-intelligence with the configured model."
        res = {"answer": ans, "cited_movie_ids": []}
        await cache.set(cache_key, res)
        return res

    # Sort descending by similarity score
    candidates.sort(key=lambda x: x.get("similarity_score", 0.0), reverse=True)
    top_candidates = candidates[:15]

    # 4. Minify metadata for LLM prompt
    minimized_candidates = [minimize_movie_metadata(c) for c in top_candidates]

    # 5. Build LLM prompt and query Gemini Flash
    prompt_items = []
    for m in minimized_candidates:
        prompt_items.append({
            "id": m.get("id"),
            "title": m.get("title"),
            "year": m.get("year"),
            "genres": m.get("genres"),
            "tagline": m.get("tagline"),
            "synopsis": m.get("synopsis"),
            "tones": m.get("tones"),
            "themes": m.get("themes"),
            "awards": m.get("awards"),
            "studios": m.get("studios"),
            "directors": m.get("directors")
        })

    history_lines = []
    if chat_history:
        for entry in chat_history:
            role = "User" if entry.get("role") == "user" else "Librarian"
            history_lines.append(f"{role}: {entry.get('text', '')}")
    history_str = "\n".join(history_lines)

    history_context = ""
    if history_str:
        history_context = f"Here is the conversation history so far:\n{history_str}\n\n"

    memory_prompt_part = ""
    if memory_context:
        memory_prompt_part = f"\nUser Profile and Preference Context:\n{memory_context}\n\n"

    prompt = (
        f"You are a helpful and knowledgeable media librarian. The user has asked the following question about their local movie library:\n"
        f"{memory_prompt_part}"
        f"{history_context}"
        f"New User Question: \"{question}\"\n\n"
        f"Here are the top candidate movies retrieved from their library based on semantic similarity:\n"
        f"{json.dumps(prompt_items, indent=2)}\n\n"
        f"Task:\n"
        f"1. Select the best matching movies (up to 5, ideally 3-4) that fit the user's request, keeping the conversation history and user preferences in mind.\n"
        f"2. Write a warm, conversational, and direct markdown response to the user explaining why these movies are good recommendations, referencing their specific genres, themes, tones, directors, or awards where appropriate. Tailor the tone based on the user's mapped interests/tastes if available.\n"
        f"3. For each recommended movie, clearly state its Title and Year in bold (e.g. **Interstellar** (2014)) so they are easy to identify.\n"
        f"4. If the user asks what to add next or asks for movies outside the local library, you may recommend external movies not present in the candidate list. Format each external movie exactly as [External Recommendation: Title (Year)].\n"
        f"5. Stay strictly within movies and media-library discovery. Refuse non-media questions briefly.\n"
        f"6. If none of the candidates match the user's query well, politely explain that you couldn't find a strong match, but highlight 1-2 close matches from the list or clearly marked external additions if the user asked what to add next.\n"
    )

    try:
        answer = await generate_gemini_content(
            prompt=prompt,
            system_instruction="You are an expert movie intelligence advisor who helps users search and discover films in their library.",
            temperature=0.2
        )
    except Exception as e:
        if _is_rate_limit_error(e):
            answer = _build_local_fallback_answer(
                top_candidates,
                "Try again in a bit for the richer conversational explanation.",
            )
            result = {
                "answer": answer,
                "cited_movie_ids": [c["id"] for c in top_candidates[:5] if c.get("id")],
                "external_recommendations": [],
                "rate_limited": True,
            }
            await cache.set(cache_key, result, ttl=60.0)
            return result
        err_msg = f"Failed to generate conversational answer from Gemini: {str(e)}"
        return {"ok": False, "error": {"message": err_msg, "code": "RAG_GENERATION_FAILED", "retryable": True}}

    external_recs = []
    parsed_external = parse_external_recommendations(answer)
    if parsed_external:
        try:
            allowed_external = filter_external_recommendations(parsed_external, discord_user_id=discord_user_id)
            answer = remove_filtered_external_markers(answer, allowed_external)
            external_recs = [rec.as_dict() for rec in allowed_external]
        except Exception as e:
            print(f"[RAG] Warning: External recommendation filtering failed: {e}")
            answer = remove_filtered_external_markers(answer, [])

    # Log interaction to user_interaction_memory
    if discord_user_id:
        try:
            UserInteractionMemoryRepository.log(
                discord_user_id=discord_user_id,
                query_text=question,
                response_text=answer.strip()
            )
            UserInteractionMemoryRepository.prune_oldest(discord_user_id, max_limit=30)
        except Exception as e:
            print(f"[RAG] Warning: Failed to log user interaction: {e}")

    # 6. Extract cited movie IDs based on title matching
    cited_movie_ids = []
    sorted_candidates = sorted(top_candidates, key=lambda x: len(x.get("title") or ""), reverse=True)
    for c in sorted_candidates:
        title = c.get("title")
        if not title:
            continue
        pattern = re.compile(r'\b' + re.escape(title) + r'\b', re.IGNORECASE)
        if not re.match(r'^\w+$', title):
            pattern = re.compile(re.escape(title), re.IGNORECASE)
        if pattern.search(answer):
            cited_movie_ids.append(c["id"])

    result = {
        "answer": answer.strip(),
        "cited_movie_ids": cited_movie_ids,
        "external_recommendations": external_recs,
    }

    # Cache the result
    await cache.set(cache_key, result)
    return result
