"""Bounded public-read exact movie profile lookup for local tool consumers."""

import json
from typing import Any, Dict, List, Optional

from moviebot.core.dedupe import normalize_title
from moviebot.db.repositories import LibraryItemRepository


SCHEMA_VERSION = 1
MAX_LIST_ITEMS = 16


def exact_movie_profile_tool(
    rating_key: Optional[str] = None,
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None,
    title: Optional[str] = None,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """Return one sanitized local profile without semantic search or external calls."""
    matches: List[Dict[str, Any]] = []
    matched_by: Optional[str] = None

    if rating_key:
        matches = LibraryItemRepository.get_by_rating_key(rating_key)
        matched_by = "rating_key"
    if not matches and imdb_id:
        matches = LibraryItemRepository.get_by_imdb_id(imdb_id)
        matched_by = "imdb_id"
    if not matches and tmdb_id is not None:
        matches = LibraryItemRepository.get_by_tmdb_id(tmdb_id)
        matched_by = "tmdb_id"
    if not matches and title and year is not None:
        matches = LibraryItemRepository.get_by_normalized_title_and_year(normalize_title(title), year)
        matched_by = "title_year"

    if not matches:
        return _envelope("not_found", matched_by=matched_by)
    unique = {str(item.get("id")): item for item in matches}
    if len(unique) != 1:
        return _envelope("ambiguous", matched_by=matched_by)
    item = next(iter(unique.values()))
    return _envelope("available", matched_by=matched_by, profile=_sanitize_profile(item))


def _envelope(status: str, matched_by: Optional[str], profile: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "matched_by": matched_by,
    }
    if profile is not None:
        data["profile"] = profile
    return {"ok": True, "tool": "exact_movie_profile", "data": data}


def _json_list(raw: Any, limit: int = MAX_LIST_ITEMS) -> List[str]:
    if not raw:
        return []
    try:
        values = json.loads(raw) if isinstance(raw, str) else raw
    except (TypeError, ValueError):
        return []
    if not isinstance(values, list):
        return []
    result: List[str] = []
    for value in values[:limit]:
        text = str(value).strip()
        if text and text not in result:
            result.append(text[:160])
    return result


def _optional_text(value: Any, limit: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:limit] if value else None


def _sanitize_profile(item: Dict[str, Any]) -> Dict[str, Any]:
    runtime = item.get("runtime")
    runtime_minutes = int(runtime) if isinstance(runtime, (int, float)) and runtime > 0 else None
    tmdb_id = item.get("tmdb_id")
    return {
        "title": _optional_text(item.get("title"), 300) or "Untitled movie",
        "release_year": item.get("year") if isinstance(item.get("year"), int) else None,
        "release_date": _optional_text(item.get("originally_available_at"), 40),
        "runtime_minutes": runtime_minutes,
        "genres": _json_list(item.get("genres")),
        "directors": _json_list(item.get("directors"), 8),
        "cast": _json_list(item.get("cast"), 12),
        "studios": _json_list(item.get("studios"), 8),
        "countries": _json_list(item.get("countries"), 8),
        "content_rating": _optional_text(item.get("content_rating"), 40),
        "tagline": _optional_text(item.get("tagline"), 300),
        "synopsis": _optional_text(item.get("synopsis"), 4000),
        "imdb_id": _optional_text(item.get("imdb_id"), 20),
        "tmdb_id": int(tmdb_id) if isinstance(tmdb_id, int) and tmdb_id > 0 else None,
        "brand_tags": _json_list(item.get("brand_tags")),
        "franchise_tags": _json_list(item.get("franchise_tags")),
        "universe_tags": _json_list(item.get("universe_tags")),
        "source_property_tags": _json_list(item.get("source_property_tags")),
        "refreshed_at": _optional_text(item.get("metadata_refreshed_at") or item.get("updated_at"), 80),
    }
