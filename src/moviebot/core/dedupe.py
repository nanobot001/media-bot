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


def evaluate_deduplication(
    title: str,
    year: int,
    imdb_id: Optional[str] = None
) -> Tuple[str, str, str, Optional[Dict[str, Any]]]:
    """
    Evaluates an input title against the local library_items sqlite table.
    Returns: (tier, action, details_message, matched_item_dict)
    """
    # Tier 1: exact_guid
    if imdb_id:
        guid_matches = LibraryItemRepository.get_by_imdb_id(imdb_id)
        if guid_matches:
            return (
                "exact_guid",
                "block",
                f"IMDb/TMDb identifier {imdb_id} matches existing file: {guid_matches[0]['title']}",
                guid_matches[0]
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
        # Tier 2: exact_title_year
        if item["normalized_title"] == normalized_input and item["year"] == year:
            return (
                "exact_title_year",
                "block",
                f"Normalized title and year matches exactly: {item['title']} ({item['year']})",
                item
            )
        
        # Calculate fuzzy similarity
        ratio = levenshtein_ratio(normalized_input, item["normalized_title"])
        if ratio > best_ratio:
            best_ratio = ratio
            best_candidate = item

    # Tier 3: fuzzy_likely
    if best_ratio >= 0.90 and best_candidate:
        cand_year = best_candidate["year"]
        if cand_year and abs(cand_year - year) <= 1:
            return (
                "fuzzy_likely",
                "warn",
                f"Fuzzy match detected ({best_ratio:.2f} similarity): {best_candidate['title']} ({best_candidate['year']})",
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
