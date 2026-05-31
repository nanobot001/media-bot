import json
import re
from typing import List, Dict, Any, Optional

# Knowledge base of popular movie collections with their full sequence mapping
POPULAR_COLLECTIONS = {
    "john wick collection": [
        {"index": 1, "title": "John Wick", "year": 2014},
        {"index": 2, "title": "John Wick: Chapter 2", "year": 2017},
        {"index": 3, "title": "John Wick: Chapter 3 - Parabellum", "year": 2019},
        {"index": 4, "title": "John Wick: Chapter 4", "year": 2023}
    ],
    "the godfather collection": [
        {"index": 1, "title": "The Godfather", "year": 1972},
        {"index": 2, "title": "The Godfather: Part II", "year": 1974},
        {"index": 3, "title": "The Godfather: Part III", "year": 1990}
    ],
    "the dark knight trilogy": [
        {"index": 1, "title": "Batman Begins", "year": 2005},
        {"index": 2, "title": "The Dark Knight", "year": 2008},
        {"index": 3, "title": "The Dark Knight Rises", "year": 2012}
    ],
    "back to the future collection": [
        {"index": 1, "title": "Back to the Future", "year": 1985},
        {"index": 2, "title": "Back to the Future Part II", "year": 1989},
        {"index": 3, "title": "Back to the Future Part III", "year": 1990}
    ],
    "toy story collection": [
        {"index": 1, "title": "Toy Story", "year": 1995},
        {"index": 2, "title": "Toy Story 2", "year": 1999},
        {"index": 3, "title": "Toy Story 3", "year": 2010},
        {"index": 4, "title": "Toy Story 4", "year": 2019}
    ],
    "lethal weapon collection": [
        {"index": 1, "title": "Lethal Weapon", "year": 1987},
        {"index": 2, "title": "Lethal Weapon 2", "year": 1989},
        {"index": 3, "title": "Lethal Weapon 3", "year": 1992},
        {"index": 4, "title": "Lethal Weapon 4", "year": 1998}
    ],
    "the matrix collection": [
        {"index": 1, "title": "The Matrix", "year": 1999},
        {"index": 2, "title": "The Matrix Reloaded", "year": 2003},
        {"index": 3, "title": "The Matrix Revolutions", "year": 2003},
        {"index": 4, "title": "The Matrix Resurrections", "year": 2021}
    ],
    "iron man collection": [
        {"index": 1, "title": "Iron Man", "year": 2008},
        {"index": 2, "title": "Iron Man 2", "year": 2010},
        {"index": 3, "title": "Iron Man 3", "year": 2013}
    ]
}

ROMAN_NUMERALS = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5, "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10
}


def parse_sequence_index(title: str, col_name: str) -> Optional[int]:
    """Parse the sequence index (e.g. 1, 2, 3) from a movie title using regex heuristics."""
    clean_col = col_name.replace("Collection", "").replace("Trilogy", "").replace("Series", "").strip().lower()
    clean_title = title.strip().lower()

    # If title is exactly or very close to the base collection name, it's likely the first
    if clean_title == clean_col or clean_title == clean_col + " 1" or clean_title == clean_col + ": part 1" or clean_title == clean_col + " part i":
        return 1

    # Look for Chapter X or Part X
    match = re.search(r'\b(?:chapter|part|vol|volume)\s+(\d+)\b', clean_title)
    if match:
        return int(match.group(1))

    # Look for Chapter/Part Roman numerals
    match_roman = re.search(r'\b(?:chapter|part|vol|volume)\s+([ivx]+)\b', clean_title)
    if match_roman:
        roman_str = match_roman.group(1).upper()
        if roman_str in ROMAN_NUMERALS:
            return ROMAN_NUMERALS[roman_str]

    # Look for Roman numeral at the end of the title or as a standalone word (e.g., "Die Hard II")
    match_roman_standalone = re.search(r'\b([ivx]+)\b$', clean_title)
    if match_roman_standalone:
        roman_str = match_roman_standalone.group(1).upper()
        if roman_str in ROMAN_NUMERALS:
            return ROMAN_NUMERALS[roman_str]

    # Look for standalone number at the end (e.g. "Die Hard 2")
    match_num_standalone = re.search(r'\b(\d+)\b$', clean_title)
    if match_num_standalone:
        val = int(match_num_standalone.group(1))
        if val < 50:  # Avoid years
            return val

    # Look for numbers after the collection base name
    pattern = re.escape(clean_col) + r'\s+(\d+)\b'
    match_col_num = re.search(pattern, clean_title)
    if match_col_num:
        return int(match_col_num.group(1))

    pattern_roman = re.escape(clean_col) + r'\s+([ivx]+)\b'
    match_col_roman = re.search(pattern_roman, clean_title)
    if match_col_roman:
        roman_str = match_col_roman.group(1).upper()
        if roman_str in ROMAN_NUMERALS:
            return ROMAN_NUMERALS[roman_str]

    return None


def normalize_for_matching(title: str) -> str:
    """Normalize title for exact alphanumeric matching."""
    return re.sub(r'[^a-z0-9]', '', title.lower())


def audit_collections(db_conn) -> List[Dict[str, Any]]:
    """
    Scans the database for movies tagged with collections, groups them, and audits them
    for sequence gaps or missing sequels.
    """
    cursor = db_conn.cursor()
    cursor.execute("SELECT rating_key, title, year, collections FROM library_items")
    rows = cursor.fetchall()

    # Group items by collection tag
    collection_groups = {}
    for row in rows:
        rating_key, title, year, collections_json = row
        if not collections_json:
            continue

        try:
            collections_list = json.loads(collections_json)
        except Exception:
            continue

        for col in collections_list:
            if not col:
                continue
            if col not in collection_groups:
                collection_groups[col] = []
            collection_groups[col].append({
                "rating_key": rating_key,
                "title": title,
                "year": year
            })

    gap_reports = []

    for col_name, owned_items in collection_groups.items():
        col_name_lower = col_name.strip().lower()

        # 1. Check knowledge base match
        kb_match_key = None
        for kb_key in POPULAR_COLLECTIONS.keys():
            # Match case-insensitively, or allow matching with/without "Collection"
            if col_name_lower == kb_key or col_name_lower.replace(" collection", "") == kb_key.replace(" collection", ""):
                kb_match_key = kb_key
                break

        if kb_match_key:
            sequence = POPULAR_COLLECTIONS[kb_match_key]
            missing_items = []
            matched_owned = []

            for seq_item in sequence:
                # Find if we own this sequence item
                found = False
                for owned in owned_items:
                    # Match by normalized title, release year, or parsed index
                    title_match = normalize_for_matching(owned["title"]) == normalize_for_matching(seq_item["title"])
                    year_match = owned["year"] == seq_item["year"]
                    
                    owned_idx = parse_sequence_index(owned["title"], col_name)
                    index_match = (owned_idx is not None) and (owned_idx == seq_item["index"])
                    
                    if title_match or year_match or index_match:
                        found = True
                        matched_owned.append({
                            "rating_key": owned["rating_key"],
                            "title": owned["title"],
                            "year": owned["year"],
                            "index": seq_item["index"]
                        })
                        break
                if not found:
                    missing_items.append({
                        "index": seq_item["index"],
                        "title": seq_item["title"],
                        "year": seq_item["year"]
                    })

            if missing_items:
                gap_reports.append({
                    "collection": col_name,
                    "owned": matched_owned,
                    "missing": missing_items,
                    "confidence": 1.0  # High confidence from knowledge base
                })

        # 2. Heuristic fallback for arbitrary collections
        else:
            # Parse indices of owned items
            indexed_owned = []
            unindexed_owned = []

            for owned in owned_items:
                idx = parse_sequence_index(owned["title"], col_name)
                item_info = {
                    "rating_key": owned["rating_key"],
                    "title": owned["title"],
                    "year": owned["year"],
                    "index": idx
                }
                if idx is not None:
                    indexed_owned.append(item_info)
                else:
                    unindexed_owned.append(item_info)

            # Sort owned items by year to attempt to fill index for unindexed ones
            owned_sorted_by_year = sorted(owned_items, key=lambda x: x["year"] or 0)
            
            # If the oldest movie has no index, and we have index 2 in indexed_owned, guess it is index 1
            if unindexed_owned and indexed_owned:
                has_index_2 = any(x["index"] == 2 for x in indexed_owned)
                has_index_1 = any(x["index"] == 1 for x in indexed_owned)
                if has_index_2 and not has_index_1:
                    # Find the oldest unindexed item
                    oldest_unindexed = min(unindexed_owned, key=lambda x: x["year"] or 9999)
                    oldest_unindexed["index"] = 1
                    indexed_owned.append(oldest_unindexed)
                    unindexed_owned.remove(oldest_unindexed)

            # Gather all parsed indices
            owned_indices = {x["index"] for x in indexed_owned if x["index"] is not None}
            
            if owned_indices:
                min_idx = min(owned_indices)
                max_idx = max(owned_indices)
                
                # Check for sequence gaps between min and max indices
                missing_items = []
                for idx in range(min_idx, max_idx + 1):
                    if idx not in owned_indices:
                        # Guess the missing title pattern
                        clean_col = col_name.replace("Collection", "").replace("Trilogy", "").replace("Series", "").strip()
                        # See if there is a title format we can copy (e.g. Chapter vs Part)
                        title_format = None
                        for x in indexed_owned:
                            if "chapter" in x["title"].lower():
                                title_format = "chapter"
                                break
                            elif "part" in x["title"].lower():
                                title_format = "part"
                                break
                        
                        if title_format == "chapter":
                            guessed_title = f"{clean_col}: Chapter {idx}"
                        elif title_format == "part":
                            guessed_title = f"{clean_col}: Part {idx}"
                        else:
                            guessed_title = f"{clean_col} {idx}"

                        missing_items.append({
                            "index": idx,
                            "title": guessed_title,
                            "year": None
                        })

                if missing_items:
                    # Format matched owned items
                    formatted_owned = []
                    for x in indexed_owned:
                        formatted_owned.append({
                            "rating_key": x["rating_key"],
                            "title": x["title"],
                            "year": x["year"],
                            "index": x["index"]
                        })
                    for x in unindexed_owned:
                        formatted_owned.append({
                            "rating_key": x["rating_key"],
                            "title": x["title"],
                            "year": x["year"],
                            "index": None
                        })

                    gap_reports.append({
                        "collection": col_name,
                        "owned": formatted_owned,
                        "missing": missing_items,
                        "confidence": 0.6  # Medium confidence for heuristic analysis
                    })

    return gap_reports
