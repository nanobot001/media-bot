import re
from typing import List, Dict, Any, Tuple


def select_primary_video_file(
    files: List[Dict[str, Any]]
) -> Tuple[bool, List[Dict[str, Any]]]:
    """
    Applies exclusions and size heuristic checks to isolate the primary video file.
    
    Accepts:
        files: A list of dicts with 'name' (or 'n') and 'size' (or 's') keys.
               Example: [{'name': 'film.mkv', 'size': 10000000}]
               
    Returns:
        (is_resolved, result_list)
        - If is_resolved is True, result_list contains exactly 1 selected file dict.
        - If is_resolved is False, result_list contains multiple candidate file dicts (within 10% size).
        
    Raises:
        ValueError if no matching files remain after filtering.
    """
    cleaned_files = []
    
    # Normalize input dictionary structures
    for f in files:
        name = f.get("name") or f.get("n")
        size = f.get("size") or f.get("s") or f.get("size_bytes") or 0
        file_id = f.get("id")
        
        if not name:
            continue
            
        cleaned_files.append({
            "id": file_id,
            "name": name,
            "size": int(size)
        })

    # 1. Regex Exclusions
    exclusion_pattern = re.compile(r'(sample|trailer|extra|bonus|featurette)', re.IGNORECASE)
    filtered = [f for f in cleaned_files if not exclusion_pattern.search(f["name"])]

    # 2. Extension Filter
    valid_extensions = ('.mkv', '.mp4', '.avi')
    filtered = [f for f in filtered if f["name"].lower().endswith(valid_extensions)]

    if not filtered:
        raise ValueError("No valid movie files found after pruning samples and extensions.")

    # 3. Decision Logic
    if len(filtered) == 1:
        return True, [filtered[0]]

    # Sort by size descending
    filtered.sort(key=lambda x: x["size"], reverse=True)

    largest = filtered[0]
    second_largest = filtered[1]

    # Check if the second largest is within 10% of the largest size
    # 10% window means second_largest['size'] >= 0.90 * largest['size']
    if second_largest["size"] >= 0.90 * largest["size"]:
        # High variance uncertainty: return all matching files in the size window
        threshold_size = 0.90 * largest["size"]
        candidates = [f for f in filtered if f["size"] >= threshold_size]
        return False, candidates

    # Clear winner
    return True, [largest]
