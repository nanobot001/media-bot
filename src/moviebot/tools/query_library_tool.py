import datetime
import json
import re
from typing import Dict, Any, Optional, List

from moviebot.db.connection import get_db_connection
from moviebot.db.repositories import LibraryItemRepository
from moviebot.core.embeddings import get_embedding_result, decode_vector, cosine_similarity
from moviebot.core.enrichment import canonical_location

CONTENT_WARNING_RANK = {
    "none": 0,
    "mild": 1,
    "moderate": 2,
    "strong": 3,
    "extreme": 4,
    "unknown": 99,
}


def _json_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except Exception:
        return []
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if value is not None]


def _json_object(raw: Optional[str]) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _contains_value(raw: Optional[str], expected: str) -> bool:
    expected_norm = expected.lower()
    return any(value.lower() == expected_norm for value in _json_list(raw))


def _contains_any(raw: Optional[str], expected_values: List[str]) -> bool:
    actual = {value.lower() for value in _json_list(raw)}
    return any(value.lower() in actual for value in expected_values)


def _contains_text(raw: Optional[str], expected: str) -> bool:
    expected_norm = expected.lower()
    return any(expected_norm == value.lower() or expected_norm in value.lower() for value in _json_list(raw))


def _contains_json_text(raw: Optional[str], expected: str) -> bool:
    expected_norm = expected.lower()
    if _contains_text(raw, expected):
        return True
    value = _json_object(raw)
    return bool(value) and expected_norm in json.dumps(value).lower()


def _has_any_json_fact(*raw_values: Optional[str]) -> bool:
    for raw in raw_values:
        if _json_list(raw) or _json_object(raw):
            return True
    return False


def _matches_award_fact(item: Dict[str, Any], expected: str) -> bool:
    expected_norm = expected.lower()
    if expected_norm in {"award winning", "award-winning", "award winner", "winner"}:
        return _has_any_json_fact(
            item.get("award_tags"),
            item.get("award_wins_json"),
            item.get("acclaim_tags"),
        )
    return (
        _contains_json_text(item.get("award_tags"), expected)
        or _contains_json_text(item.get("award_wins_json"), expected)
        or _contains_json_text(item.get("award_nominations_json"), expected)
        or _contains_json_text(item.get("acclaim_tags"), expected)
    )


def _contains_typed_or_flat(item: Dict[str, Any], typed_field: str, flat_field: str, expected: str) -> bool:
    typed_raw = item.get(typed_field)
    typed_values = _json_list(typed_raw)
    if typed_raw is not None:
        return any(value.lower() == expected.lower() for value in typed_values)
    return _contains_value(item.get(flat_field), expected)


def _infer_setting_location(query: Optional[str]) -> Optional[str]:
    if not query:
        return None
    patterns = [
        r"\b(?:takes place|take place|set|located)\s+in\s+([a-zA-Z][a-zA-Z\s-]{1,60})",
    ]
    for pattern in patterns:
        match = re.search(pattern, query, flags=re.IGNORECASE)
        if match:
            location = match.group(1).strip(" .?!")
            return canonical_location(location)
    return None


def _infer_studio_or_brand(query: Optional[str]) -> Optional[str]:
    if not query:
        return None
    cleaned = query.strip(" .?!")
    patterns = [
        r"\b(.+?)\s+(?:movies|films)\b",
        r"\b(?:movies|films)\s+by\s+(.+?)\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if match:
            value = match.group(1).strip(" .?!")
            if value and value.lower() not in {"animated", "family", "scary", "good", "best"}:
                return value.title()
    return None


def _infer_hard_fact_filters(query: Optional[str]) -> Dict[str, str]:
    text = (query or "").lower()
    filters: Dict[str, str] = {}
    if any(phrase in text for phrase in ("award winning", "award-winning", "award winner")):
        filters["award_tag"] = "award winning"
    if "oscar" in text:
        filters["award_tag"] = "oscar"
    if any(phrase in text for phrase in ("critically acclaimed", "acclaimed")):
        filters["award_tag"] = "critically acclaimed"
    if "festival winner" in text:
        filters["award_tag"] = "festival winner"
    if "based on a book" in text:
        filters["source_material_tag"] = "based on a book"
    if "true story" in text or "based on a true story" in text:
        filters["source_material_tag"] = "based on a true story"
    if "comic book" in text:
        filters["source_material_tag"] = "comic book"
    if "video game" in text:
        filters["source_material_tag"] = "video game"
    if "blockbuster" in text:
        filters["popularity_tag"] = "blockbuster"
    if "cult classic" in text:
        filters["cultural_impact_tag"] = "cult classic"
    if "classic" in text and "cult classic" not in text:
        filters["cultural_impact_tag"] = "classic"
    return filters


def _warning_level(item: Dict[str, Any], warning: str) -> str:
    raw = item.get("content_warnings_json")
    if not raw:
        return "unknown"
    try:
        warnings = json.loads(raw)
    except Exception:
        return "unknown"
    if not isinstance(warnings, dict):
        return "unknown"
    value = warnings.get(warning)
    if not isinstance(value, dict):
        return "unknown"
    level = str(value.get("level") or "unknown").lower()
    return level if level in CONTENT_WARNING_RANK else "unknown"


async def query_library_tool(
    query: Optional[str] = None,
    semantic_query: Optional[str] = None,
    genre: Optional[str] = None,
    director: Optional[str] = None,
    resolution: Optional[str] = None,
    watch_status: Optional[str] = None,
    max_runtime: Optional[int] = None,
    min_rating: Optional[float] = None,
    setting_location: Optional[str] = None,
    premise_tag: Optional[str] = None,
    character_tag: Optional[str] = None,
    theme_tag: Optional[str] = None,
    tone_tag: Optional[str] = None,
    craft_tag: Optional[str] = None,
    studio: Optional[str] = None,
    actor: Optional[str] = None,
    content_rating: Optional[str] = None,
    award_tag: Optional[str] = None,
    source_material_tag: Optional[str] = None,
    popularity_tag: Optional[str] = None,
    cultural_impact_tag: Optional[str] = None,
    exclude_content_warnings: Optional[List[str]] = None,
    exclude_warning_level: str = "mild",
    include_unknown_content_warnings: bool = False,
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
        setting_location: Exact structured setting location filter.
        premise_tag: Exact structured premise tag filter.
        character_tag: Exact structured character tag filter.
        theme_tag: Exact structured theme tag filter.
        tone_tag: Exact structured tone tag filter.
        craft_tag: Exact structured craft tag filter.
        studio: Exact studio/brand filter matched against studios, collections, and labels.
        actor: Exact actor/cast-name filter.
        content_rating: Exact Plex content rating filter.
        award_tag: Hard-fact award/acclaim tag filter.
        source_material_tag: Hard-fact source material tag filter.
        popularity_tag: Hard-fact popularity tag filter.
        cultural_impact_tag: Hard-fact cultural impact tag filter.
        exclude_content_warnings: Warning names to exclude at or above exclude_warning_level.
        exclude_warning_level: Minimum warning severity to exclude.
        include_unknown_content_warnings: Include unknown warning rows instead of excluding conservatively.
        limit: Max number of records to return.
    """
    tool_name = "query_library_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        inferred_hard_facts = {
            **_infer_hard_fact_filters(semantic_query),
            **_infer_hard_fact_filters(query),
        }
        inferred_setting_location = setting_location or _infer_setting_location(semantic_query) or _infer_setting_location(query)
        inferred_studio = studio
        if not inferred_studio and not inferred_hard_facts:
            inferred_studio = _infer_studio_or_brand(semantic_query) or _infer_studio_or_brand(query)
        inferred_award_tag = award_tag or inferred_hard_facts.get("award_tag")
        inferred_source_material_tag = source_material_tag or inferred_hard_facts.get("source_material_tag")
        inferred_popularity_tag = popularity_tag or inferred_hard_facts.get("popularity_tag")
        inferred_cultural_impact_tag = cultural_impact_tag or inferred_hard_facts.get("cultural_impact_tag")
        structured_filters_applied = set()
        query_routing = {
            "inferred_setting_location": inferred_setting_location,
            "inferred_studio": inferred_studio,
            "inferred_award_tag": inferred_award_tag,
            "inferred_source_material_tag": inferred_source_material_tag,
            "inferred_popularity_tag": inferred_popularity_tag,
            "inferred_cultural_impact_tag": inferred_cultural_impact_tag,
            "structured_filters_applied": []
        }

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
            item.pop("enrichment_json", None)
            item.pop("field_confidence_json", None)
            item.pop("field_evidence_json", None)

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

            if inferred_setting_location:
                structured_filters_applied.add("story_location")
                if not _contains_typed_or_flat(item, "story_locations", "setting_locations", inferred_setting_location):
                    continue

            if premise_tag:
                structured_filters_applied.add("premise_tag")
                if not _contains_value(item.get("premise_tags"), premise_tag):
                    continue

            if character_tag:
                structured_filters_applied.add("character_tag")
                if not _contains_value(item.get("character_tags"), character_tag):
                    continue

            if theme_tag:
                structured_filters_applied.add("theme_tag")
                if not _contains_value(item.get("theme_tags"), theme_tag):
                    continue

            if tone_tag:
                structured_filters_applied.add("tone_tag")
                if not _contains_value(item.get("tone_tags"), tone_tag):
                    continue

            if craft_tag:
                structured_filters_applied.add("craft_tag")
                if not _contains_value(item.get("craft_tags"), craft_tag):
                    continue

            if inferred_studio:
                structured_filters_applied.add("studio")
                if not (
                    _contains_text(item.get("studios"), inferred_studio)
                    or _contains_text(item.get("collections"), inferred_studio)
                    or _contains_text(item.get("labels"), inferred_studio)
                ):
                    continue

            if actor:
                structured_filters_applied.add("actor")
                if not _contains_text(item.get("cast"), actor):
                    continue

            if content_rating and item.get("content_rating") != content_rating:
                structured_filters_applied.add("content_rating")
                continue

            if inferred_award_tag:
                structured_filters_applied.add("award_tag")
                if not _matches_award_fact(item, inferred_award_tag):
                    continue

            if inferred_source_material_tag:
                structured_filters_applied.add("source_material_tag")
                if not (_contains_text(item.get("source_material_tags"), inferred_source_material_tag) or _contains_text(item.get("adaptation_type_tags"), inferred_source_material_tag)):
                    continue

            if inferred_popularity_tag:
                structured_filters_applied.add("popularity_tag")
                if not _contains_text(item.get("popularity_tags"), inferred_popularity_tag):
                    continue

            if inferred_cultural_impact_tag:
                structured_filters_applied.add("cultural_impact_tag")
                if not _contains_text(item.get("cultural_impact_tags"), inferred_cultural_impact_tag):
                    continue

            warning_exclusions = exclude_content_warnings or []
            if warning_exclusions:
                structured_filters_applied.add("content_warning_exclusions")
                threshold = CONTENT_WARNING_RANK.get(exclude_warning_level.lower(), CONTENT_WARNING_RANK["mild"])
                should_skip = False
                for warning in warning_exclusions:
                    level = _warning_level(item, warning)
                    if level == "unknown" and not include_unknown_content_warnings:
                        should_skip = True
                        break
                    if level != "unknown" and CONTENT_WARNING_RANK.get(level, 99) >= threshold:
                        should_skip = True
                        break
                if should_skip:
                    continue

            filtered_matches.append(item)

        # 3. Apply semantic query ranking if requested
        semantic_metadata: Optional[Dict[str, Any]] = None
        if semantic_query and not any([
            inferred_setting_location,
            inferred_studio,
            inferred_award_tag,
            inferred_source_material_tag,
            inferred_popularity_tag,
            inferred_cultural_impact_tag,
        ]):
            embedding_result = await get_embedding_result(semantic_query)
            query_vector = embedding_result.vector
            compared_count = 0
            skipped_missing_vector = 0
            skipped_model_mismatch = 0

            for item in filtered_matches:
                score = None
                blob = item.get("synopsis_vector")
                item_model = item.get("synopsis_vector_model")
                item_dim = item.get("synopsis_vector_dim")
                if not blob:
                    skipped_missing_vector += 1
                elif item_model != embedding_result.model or item_dim != embedding_result.dim:
                    skipped_model_mismatch += 1
                else:
                    try:
                        vector = decode_vector(blob)
                        score = cosine_similarity(query_vector, vector)
                        compared_count += 1
                    except Exception:
                        skipped_missing_vector += 1
                # Convert blob vector to none in output JSON to keep response clean/serializable
                item.pop("synopsis_vector", None)
                if score is not None:
                    item["similarity_score"] = score

            filtered_matches = [item for item in filtered_matches if "similarity_score" in item]

            # Sort descending by similarity score
            filtered_matches.sort(key=lambda x: x.get("similarity_score", 0.0), reverse=True)
            semantic_metadata = {
                "query_model": embedding_result.model,
                "query_source": embedding_result.source,
                "fallback": embedding_result.fallback,
                "compared_count": compared_count,
                "skipped_missing_vector": skipped_missing_vector,
                "skipped_model_mismatch": skipped_model_mismatch,
            }
        else:
            # Remove BLOB vector from output to avoid JSON serialization issues
            for item in filtered_matches:
                item.pop("synopsis_vector", None)
            # Default sorting by title ascending if not semantic
            filtered_matches.sort(key=lambda x: x.get("title", ""))

        # Apply limit
        limited_matches = filtered_matches[:limit]
        for item in limited_matches:
            item.pop("content_warnings_json", None)
        query_routing["structured_filters_applied"] = sorted(structured_filters_applied)

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "movies": limited_matches,
                "semantic_search": semantic_metadata,
                "query_routing": query_routing
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
