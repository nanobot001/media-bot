import datetime
import json
from typing import Dict, Any, Optional, List

from moviebot.db.connection import get_db_connection
from moviebot.db.repositories import LibraryItemRepository
from moviebot.core.embeddings import get_embedding, decode_vector, cosine_similarity


async def query_library_tool(
    query: Optional[str] = None,
    semantic_query: Optional[str] = None,
    genre: Optional[str] = None,
    director: Optional[str] = None,
    resolution: Optional[str] = None,
    watch_status: Optional[str] = None,
    max_runtime: Optional[int] = None,
    min_rating: Optional[float] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Search the local media intelligence database with exact filters, FTS5 text matching, and optional semantic ranking.

    Args:
        query: FTS5 match query against title, synopsis, genres, directors.
        semantic_query: Text prompt for semantic vector similarity matching.
        genre: Case-insensitive genre filter.
        director: Case-insensitive director filter.
        resolution: Exact/case-insensitive resolution filter.
        watch_status: Exact/case-insensitive watch status filter.
        max_runtime: Upper limit for movie runtime.
        min_rating: Lower limit for movie rating.
        limit: Max number of records to return.
    """
    tool_name = "query_library_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        # 1. Fetch baseline matches (either FTS5 search or all library items)
        if query:
            # LibraryItemRepository.search_fts handles FTS5 MATCH on the virtual table
            raw_matches = LibraryItemRepository.search_fts(query)
        else:
            with get_db_connection() as conn:
                cursor = conn.execute("SELECT * FROM library_items")
                raw_matches = [dict(row) for row in cursor.fetchall()]

        filtered_matches: List[Dict[str, Any]] = []

        # 2. Apply filters in Python
        for item in raw_matches:
            # Redact/delete file_path first for security
            item.pop("file_path", None)

            # Genre filter
            if genre:
                genres_list = []
                if item.get("genres"):
                    try:
                        genres_list = json.loads(item["genres"])
                    except Exception:
                        pass
                if not any(g.lower() == genre.lower() for g in genres_list):
                    continue

            # Director filter
            if director:
                directors_list = []
                if item.get("directors"):
                    try:
                        directors_list = json.loads(item["directors"])
                    except Exception:
                        pass
                if not any(d.lower() == director.lower() for d in directors_list):
                    continue

            # Resolution filter
            if resolution and item.get("resolution"):
                if item["resolution"].lower() != resolution.lower():
                    continue

            # Watch status filter
            if watch_status and item.get("watch_status"):
                if item["watch_status"].lower() != watch_status.lower():
                    continue

            # Max runtime filter
            if max_runtime is not None:
                item_runtime = item.get("runtime")
                if item_runtime is None or item_runtime > max_runtime:
                    continue

            # Min rating filter
            if min_rating is not None:
                item_rating = item.get("rating")
                if item_rating is None or item_rating < min_rating:
                    continue

            filtered_matches.append(item)

        # 3. Apply semantic query ranking if requested
        if semantic_query:
            query_vector = await get_embedding(semantic_query)
            for item in filtered_matches:
                score = 0.0
                blob = item.get("synopsis_vector")
                if blob:
                    try:
                        vector = decode_vector(blob)
                        score = cosine_similarity(query_vector, vector)
                    except Exception:
                        pass
                # Convert blob vector to none in output JSON to keep response clean/serializable
                item.pop("synopsis_vector", None)
                item["similarity_score"] = score

            # Sort descending by similarity score
            filtered_matches.sort(key=lambda x: x.get("similarity_score", 0.0), reverse=True)
        else:
            # Remove BLOB vector from output to avoid JSON serialization issues
            for item in filtered_matches:
                item.pop("synopsis_vector", None)
            # Default sorting by title ascending if not semantic
            filtered_matches.sort(key=lambda x: x.get("title", ""))

        # Apply limit
        limited_matches = filtered_matches[:limit]

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "movies": limited_matches
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "LIBRARY_QUERY_FAILED",
                "message": f"Error querying library: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
