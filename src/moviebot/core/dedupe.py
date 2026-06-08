import re
from typing import Dict, Any, Tuple, Optional
from moviebot.db.repositories import LibraryItemRepository


def normalize_title(title: str) -> str:
    """
    Transforms titles into a strict, predictable comparison baseline.
    Example: "The Matrix: Resurrections (2021)!!" -> "matrixresurrections"
    """
    text = title.lower()
    
    # Strip common scene tags or quality indicators that might leak
    text = re.sub(r'\b(bluray|1080p|720p|2160p|4k|hdr|webrip|web\-dl|dvdrip|h264|x264|h265|x265)\b', '', text)
    
    # Strip production years like (2021) or 2021
    text = re.sub(r'\b\d{4}\b', '', text)
    
    # Strip common articles globally
    text = re.sub(r'\b(the|a|an)\b', '', text)
    
    # Strip punctuation and brackets
    text = re.sub(r'[\.\-\_\:\,\!\?\'\"\(\)\[\]]', '', text)
    
    # Remove all whitespace
    text = "".join(text.split())
    return text


def levenshtein_distance(s1: str, s2: str) -> int:
    """Calculates Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    
    previous_row = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
        
    return previous_row[-1]


def levenshtein_ratio(s1: str, s2: str) -> float:
    """Calculates similarity ratio based on Levenshtein distance."""
    distance = levenshtein_distance(s1, s2)
    max_len = max(len(s1), len(s2))
    if max_len == 0:
        return 1.0
    return 1.0 - (distance / max_len)


from moviebot.db.repositories import LibraryItemRepository, EventRepository


def parse_resolution_rank(res: Optional[str]) -> int:
    """Maps resolution strings to integer ranks for comparison."""
    if not res:
        return 0
    res_clean = res.lower().strip()
    if "2160" in res_clean or "4k" in res_clean:
        return 40
    if "1080" in res_clean:
        return 30
    if "720" in res_clean:
        return 20
    if "576" in res_clean:
        return 15
    if "480" in res_clean:
        return 10
    if "sd" in res_clean:
        return 5
    return 0


def evaluate_quality_upgrade(
    owned_item: Dict[str, Any],
    incoming_resolution: Optional[str] = None,
    incoming_size_bytes: Optional[int] = None,
    incoming_bitrate_kbps: Optional[int] = None
) -> Tuple[bool, str]:
    """
    Determines if an incoming release is a conservative quality upgrade
    compared to the owned library item.
    
    Returns: (is_upgrade, reason_message)
    """
    owned_res = owned_item.get("resolution")
    owned_size = owned_item.get("size_bytes")
    owned_bitrate = owned_item.get("bitrate_kbps")

    # If no quality information is provided from the incoming side, it is ambiguous
    if not incoming_resolution and incoming_size_bytes is None and incoming_bitrate_kbps is None:
        return False, "No incoming quality evidence provided; duplicate block preserved."

    # Parse resolution ranks
    incoming_rank = parse_resolution_rank(incoming_resolution)
    owned_rank = parse_resolution_rank(owned_res)

    # Case 1: Higher resolution
    if incoming_rank > owned_rank:
        # Check for suspiciously small size/bitrate to prevent bad upscales
        if incoming_size_bytes is not None:
            if incoming_rank >= 40 and incoming_size_bytes < 3221225472:  # 3 GB
                return False, f"Incoming {incoming_resolution} size ({incoming_size_bytes / (1024**3):.2f} GB) is suspiciously small; duplicate block preserved."
            if incoming_rank == 30 and incoming_size_bytes < 734003200:  # 700 MB
                return False, f"Incoming {incoming_resolution} size ({incoming_size_bytes / (1024**2):.1f} MB) is suspiciously small; duplicate block preserved."
            if incoming_size_bytes < 314572800:  # 300 MB for any resolution
                return False, f"Incoming size ({incoming_size_bytes / (1024**2):.1f} MB) is too small; duplicate block preserved."

        if incoming_bitrate_kbps is not None:
            if incoming_rank >= 40 and incoming_bitrate_kbps < 6000:
                return False, f"Incoming {incoming_resolution} bitrate ({incoming_bitrate_kbps} kbps) is suspiciously low; duplicate block preserved."
            if incoming_rank == 30 and incoming_bitrate_kbps < 2000:
                return False, f"Incoming {incoming_resolution} bitrate ({incoming_bitrate_kbps} kbps) is suspiciously low; duplicate block preserved."
            if incoming_bitrate_kbps < 800:
                return False, f"Incoming bitrate ({incoming_bitrate_kbps} kbps) is too low; duplicate block preserved."

        # If both size and bitrate are missing, we treat the upgrade as ambiguous
        if incoming_size_bytes is None and incoming_bitrate_kbps is None:
            return False, f"Incoming claims higher resolution ({incoming_resolution} vs owned {owned_res or 'unknown'}), but lacks size or bitrate evidence; duplicate block preserved."

        return True, f"Upgrade allowed: higher resolution ({incoming_resolution} vs owned {owned_res or 'unknown'})."

    # Case 2: Same resolution
    elif incoming_rank == owned_rank and incoming_rank > 0:
        # Must have at least 1.5x size or 1.5x bitrate
        size_upgrade = False
        bitrate_upgrade = False

        if incoming_size_bytes is not None and owned_size:
            if incoming_size_bytes >= 1.5 * owned_size:
                size_upgrade = True
        
        if incoming_bitrate_kbps is not None and owned_bitrate:
            if incoming_bitrate_kbps >= 1.5 * owned_bitrate:
                bitrate_upgrade = True

        if size_upgrade or bitrate_upgrade:
            reasons = []
            if size_upgrade:
                reasons.append(f"size {incoming_size_bytes / (1024**3):.2f} GB vs owned {owned_size / (1024**3):.2f} GB")
            if bitrate_upgrade:
                reasons.append(f"bitrate {incoming_bitrate_kbps} kbps vs owned {owned_bitrate} kbps")
            return True, f"Upgrade allowed: same resolution ({incoming_resolution or 'unknown'}), but significantly better " + " and ".join(reasons) + "."

        return False, f"Same resolution ({incoming_resolution or 'unknown'}) with similar or worse quality metrics (size: {incoming_size_bytes or 'unknown'} vs {owned_size or 'unknown'}, bitrate: {incoming_bitrate_kbps or 'unknown'} vs {owned_bitrate or 'unknown'}); duplicate block preserved."

    # Case 3: Lower resolution or unknown resolution ranks
    else:
        return False, f"Incoming quality ({incoming_resolution or 'unknown'}) is lower than or equal to owned quality ({owned_res or 'unknown'}); duplicate block preserved."


def emit_upgrade_event(
    matched_item: Dict[str, Any],
    incoming_res: Optional[str],
    incoming_size: Optional[int],
    incoming_bitrate: Optional[int],
    reason: str
):
    import json
    try:
        title = matched_item.get("title", "Unknown")
        year = matched_item.get("year")
        owned_res = matched_item.get("resolution")
        
        summary = f"Allowed quality upgrade for {title} ({year or 'unknown'}) to {incoming_res or 'unknown'}."
        
        data_payload = {
            "title": title,
            "year": year,
            "owned_resolution": owned_res,
            "owned_size_bytes": matched_item.get("size_bytes"),
            "owned_bitrate_kbps": matched_item.get("bitrate_kbps"),
            "incoming_resolution": incoming_res,
            "incoming_size_bytes": incoming_size,
            "incoming_bitrate_kbps": incoming_bitrate,
            "reason": reason
        }
        
        EventRepository.insert(
            event_type="upgrade_allowed",
            source="moviebot",
            title=title,
            summary=summary,
            entity_type="movie",
            entity_id=matched_item.get("id"),
            status="completed",
            severity="info",
            data_json=json.dumps(data_payload)
        )
    except Exception as e:
        print(f"Failed to log upgrade event: {e}")


def evaluate_deduplication(
    title: str,
    year: int,
    imdb_id: Optional[str] = None,
    incoming_resolution: Optional[str] = None,
    incoming_size_bytes: Optional[int] = None,
    incoming_bitrate_kbps: Optional[int] = None
) -> Tuple[str, str, str, Optional[Dict[str, Any]]]:
    """
    Evaluates an input title against the local library_items sqlite table.
    Returns: (tier, action, details_message, matched_item_dict)
    """
    # Tier 1: exact_guid
    if imdb_id:
        guid_matches = LibraryItemRepository.get_by_imdb_id(imdb_id)
        if guid_matches:
            matched_item = guid_matches[0]
            is_upgrade, upgrade_reason = evaluate_quality_upgrade(
                matched_item, incoming_resolution, incoming_size_bytes, incoming_bitrate_kbps
            )
            if is_upgrade:
                emit_upgrade_event(matched_item, incoming_resolution, incoming_size_bytes, incoming_bitrate_kbps, upgrade_reason)
                return (
                    "upgrade_eligible",
                    "allow",
                    upgrade_reason,
                    matched_item
                )
            else:
                return (
                    "exact_guid",
                    "block",
                    f"IMDb/TMDb identifier {imdb_id} matches existing file: {matched_item['title']}. {upgrade_reason}",
                    matched_item
                )

    normalized_input = normalize_title(title)

    # Fetch candidates via normalized query or title prefix
    candidates = LibraryItemRepository.search_by_normalized_title(normalized_input)
    # If empty, let's also pull all items to do a fuzzy scan (keeps it robust for small local mirror sizes)
    if not candidates:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM library_items")
            candidates = [dict(row) for row in cursor.fetchall()]

    best_ratio = 0.0
    best_candidate = None

    for item in candidates:
        item_normalized = item["normalized_title"]
        item_year = item["year"]

        # Tier 2: exact_title_year
        if item_normalized == normalized_input and item_year == year:
            is_upgrade, upgrade_reason = evaluate_quality_upgrade(
                item, incoming_resolution, incoming_size_bytes, incoming_bitrate_kbps
            )
            if is_upgrade:
                emit_upgrade_event(item, incoming_resolution, incoming_size_bytes, incoming_bitrate_kbps, upgrade_reason)
                return (
                    "upgrade_eligible",
                    "allow",
                    upgrade_reason,
                    item
                )
            else:
                return (
                    "exact_title_year",
                    "block",
                    f"Normalized title and year matches exactly: {item['title']} ({item['year']}). {upgrade_reason}",
                    item
                )

        # Tier 2b: contained_title_year
        # Handles canonical/subtitle variants such as "Dune" vs
        # "Dune: Part One" when the release year is identical.
        if (
            year
            and item_year == year
            and len(normalized_input) >= 4
            and (
                normalized_input in item_normalized
                or item_normalized in normalized_input
            )
        ):
            is_upgrade, upgrade_reason = evaluate_quality_upgrade(
                item, incoming_resolution, incoming_size_bytes, incoming_bitrate_kbps
            )
            if is_upgrade:
                emit_upgrade_event(item, incoming_resolution, incoming_size_bytes, incoming_bitrate_kbps, upgrade_reason)
                return (
                    "upgrade_eligible",
                    "allow",
                    upgrade_reason,
                    item
                )
            else:
                return (
                    "contained_title_year",
                    "block",
                    f"Title/year appears to match existing canonical title: {item['title']} ({item['year']}). {upgrade_reason}",
                    item
                )
        
        # Calculate fuzzy similarity
        ratio = levenshtein_ratio(normalized_input, item_normalized)
        if ratio > best_ratio:
            best_ratio = ratio
            best_candidate = item

    # Tier 3: fuzzy_likely
    if best_ratio >= 0.90 and best_candidate:
        cand_year = best_candidate["year"]
        if cand_year and abs(cand_year - year) <= 1:
            is_upgrade, upgrade_reason = evaluate_quality_upgrade(
                best_candidate, incoming_resolution, incoming_size_bytes, incoming_bitrate_kbps
            )
            if is_upgrade:
                emit_upgrade_event(best_candidate, incoming_resolution, incoming_size_bytes, incoming_bitrate_kbps, upgrade_reason)
                return (
                    "upgrade_eligible",
                    "allow",
                    upgrade_reason,
                    best_candidate
                )
            else:
                return (
                    "fuzzy_likely",
                    "warn",
                    f"Fuzzy match detected ({best_ratio:.2f} similarity): {best_candidate['title']} ({best_candidate['year']}). {upgrade_reason}",
                    best_candidate
                )

    # Tier 4: not_found
    return (
        "not_found",
        "allow",
        "No matching items found in the library database.",
        None
    )


# Helper function to prevent circular imports
from moviebot.db.connection import get_db_connection
