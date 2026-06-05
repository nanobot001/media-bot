import json
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from moviebot.db.repositories import UserProfileRepository
from moviebot.tools.tmdb_fact_provider import TMDbFactProvider


EXTERNAL_RECOMMENDATION_PATTERN = re.compile(
    r"\[External Recommendation:\s*(?P<title>[^\]\(\n]+?)(?:\s*\((?P<year>\d{4})\))?\s*\]",
    re.IGNORECASE,
)

ALLOWED_CONTENT_RATING_ORDER = {
    "G": 0,
    "PG": 1,
    "PG-13": 2,
    "R": 3,
    "NC-17": 4,
}

NON_MEDIA_QUERY_PATTERNS = [
    re.compile(r"\b(weather|stock|stocks|crypto|bitcoin|recipe|recipes|code|programming|math homework)\b", re.I),
    re.compile(r"\b(politics|election|sports scores?|medical|legal advice|tax advice)\b", re.I),
]

MEDIA_QUERY_PATTERNS = [
    re.compile(r"\b(movie|movies|film|films|cinema|director|actor|actress|watch|library|plex|recommend|add next)\b", re.I),
]


@dataclass(frozen=True)
class ExternalRecommendation:
    title: str
    year: Optional[int]
    sanitized_query: str
    content_rating: Optional[str] = None
    tmdb_id: Optional[int] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "title": self.title,
            "year": self.year,
            "sanitized_query": self.sanitized_query,
            "content_rating": self.content_rating,
            "tmdb_id": self.tmdb_id,
        }


def is_media_domain_question(question: str, chat_history: Optional[List[Dict[str, str]]] = None) -> bool:
    text = question or ""
    if chat_history:
        text = f"{text} " + " ".join(entry.get("text", "") for entry in chat_history)
    if any(pattern.search(text) for pattern in MEDIA_QUERY_PATTERNS):
        return True
    if any(pattern.search(text) for pattern in NON_MEDIA_QUERY_PATTERNS):
        return False
    return True


def sanitize_external_title(title: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9 ]+", " ", title or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def parse_external_recommendations(answer: str) -> List[Dict[str, Any]]:
    found: List[Dict[str, Any]] = []
    seen = set()
    for match in EXTERNAL_RECOMMENDATION_PATTERN.finditer(answer or ""):
        title = match.group("title").strip()
        year_raw = match.group("year")
        year = int(year_raw) if year_raw else None
        sanitized = sanitize_external_title(title)
        if not sanitized:
            continue
        key = (sanitized.lower(), year)
        if key in seen:
            continue
        seen.add(key)
        found.append({"title": title, "year": year, "sanitized_query": sanitized})
    return found


def _profile_filter_config(discord_user_id: Optional[str]) -> Dict[str, Any]:
    if not discord_user_id:
        return {}
    profile = UserProfileRepository.get(discord_user_id)
    if not profile or not profile.get("metadata_json"):
        return {}
    try:
        metadata = json.loads(profile["metadata_json"])
    except Exception:
        return {}
    return metadata if isinstance(metadata, dict) else {}


def _rating_is_allowed(rating: Optional[str], max_rating: Optional[str]) -> bool:
    if not max_rating or not rating:
        return True
    normalized_rating = rating.upper()
    normalized_max = max_rating.upper()
    if normalized_rating not in ALLOWED_CONTENT_RATING_ORDER or normalized_max not in ALLOWED_CONTENT_RATING_ORDER:
        return True
    return ALLOWED_CONTENT_RATING_ORDER[normalized_rating] <= ALLOWED_CONTENT_RATING_ORDER[normalized_max]


def _genres_are_allowed(genres: List[str], excluded_genres: List[str]) -> bool:
    excluded = {g.strip().lower() for g in excluded_genres if str(g).strip()}
    if not excluded:
        return True
    return not any(str(genre).strip().lower() in excluded for genre in genres)


def filter_external_recommendations(
    recommendations: List[Dict[str, Any]],
    discord_user_id: Optional[str] = None,
    tmdb_provider: Optional[TMDbFactProvider] = None,
) -> List[ExternalRecommendation]:
    if not recommendations:
        return []

    # Lazy import to avoid circular dependency (dedupe imports repositories)
    from moviebot.core.dedupe import evaluate_deduplication

    config = _profile_filter_config(discord_user_id)
    max_rating = config.get("max_content_rating") or config.get("maximum_content_rating")
    excluded_genres = config.get("excluded_genres") or config.get("exclude_genres") or []
    if isinstance(excluded_genres, str):
        excluded_genres = [excluded_genres]

    provider = tmdb_provider or TMDbFactProvider()
    filtered: List[ExternalRecommendation] = []

    for rec in recommendations:
        title = rec.get("title") or ""
        year = rec.get("year")
        sanitized = sanitize_external_title(title)
        if not sanitized:
            continue

        # --- Ownership gate (zero prompt-token cost) ---
        # Use the existing multi-tier dedupe engine to check whether this title
        # already exists in the local library.  Any tier other than "not_found"
        # means the user already owns it — drop the external rec silently.
        if year:
            try:
                tier, _action, _details, _match = evaluate_deduplication(sanitized, year)
                if tier != "not_found":
                    continue
            except Exception:
                pass  # dedupe errors are non-fatal; let the rec through
        # If year is unknown we skip the ownership gate to avoid false-positives

        facts = provider.get_facts(title=sanitized, year=year)
        content_rating = None
        tmdb_id = None
        genres: List[str] = []
        if facts:
            tmdb_id = facts.get("tmdb_id")
            genres = facts.get("genres") or []
            content_rating = facts.get("content_rating")

        if not _rating_is_allowed(content_rating, max_rating):
            continue
        if not _genres_are_allowed(genres, excluded_genres):
            continue

        filtered.append(
            ExternalRecommendation(
                title=sanitized,
                year=year,
                sanitized_query=sanitized,
                content_rating=content_rating,
                tmdb_id=tmdb_id,
            )
        )

    return filtered


def remove_filtered_external_markers(answer: str, allowed: List[ExternalRecommendation]) -> str:
    allowed_keys = {(rec.sanitized_query.lower(), rec.year) for rec in allowed}

    def replace(match: re.Match[str]) -> str:
        title = sanitize_external_title(match.group("title"))
        year_raw = match.group("year")
        year = int(year_raw) if year_raw else None
        if (title.lower(), year) not in allowed_keys:
            return ""
        return match.group(0)

    cleaned = EXTERNAL_RECOMMENDATION_PATTERN.sub(replace, answer or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    return cleaned
