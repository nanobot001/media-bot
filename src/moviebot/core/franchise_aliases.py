import re
from typing import Dict, Any, List, Set, Tuple, Optional

# Canonical Brand Map (Source values -> Canonical Brand)
BRAND_RULES = {
    r"\bmarvel\b": "Marvel",
    r"\bmcu\b": "Marvel",
    r"\bdc (comics|studios|entertainment|films)\b": "DC",
    r"\bdceu\b": "DC",
    r"\bpixar\b": "Pixar",
    r"\blucasfilm\b": "Lucasfilm",
}

# Canonical Franchise Map
FRANCHISE_RULES = {
    r"\bstar wars\b": "Star Wars",
    r"\b(james\s+)?bond\b": "James Bond",
    r"\b007\b": "James Bond",
    r"\beon productions\b": "James Bond",
    r"\bharry potter\b": "Wizarding World",
    r"\bfantastic beasts\b": "Wizarding World",
    r"\bwizarding world\b": "Wizarding World",
    r"\blord of the rings\b": "Middle-earth",
    r"\bhobbit\b": "Middle-earth",
    r"\bmiddle-earth\b": "Middle-earth",
    r"\bjurassic park\b": "Jurassic Park",
    r"\bjurassic world\b": "Jurassic Park",
    r"\bstar trek\b": "Star Trek",
    r"\bfast & furious\b": "Fast & Furious",
    r"\bfast and the furious\b": "Fast & Furious",
    r"\bmission:? impossible\b": "Mission: Impossible",
    r"\balien vs\.? predator\b": "Alien vs. Predator",
    r"\balien\b": "Alien",
    r"\bpredator\b": "Predator",
    r"\bjohn wick\b": "John Wick",
}

# Universe Map (Some franchises define their own universe)
UNIVERSE_RULES = {
    r"\bmarvel cinematic universe\b": "Marvel Cinematic Universe",
    r"\bmcu\b": "Marvel Cinematic Universe",
    r"\bdc extended universe\b": "DC Extended Universe",
    r"\bdceu\b": "DC Extended Universe",
    r"\bwizarding world\b": "Wizarding World",
    r"\bmiddle-earth\b": "Middle-earth",
}

# Source Property Map (The underlying IP / character name)
SOURCE_PROPERTY_RULES = {
    r"\biron man\b": "Iron Man",
    r"\bspider-?man\b": "Spider-Man",
    r"\bcaptain america\b": "Captain America",
    r"\bthor\b": "Thor",
    r"\bavengers\b": "Avengers",
    r"\bbatman\b": "Batman",
    r"\bsuperman\b": "Superman",
    r"\bwonder woman\b": "Wonder Woman",
    r"\b(james\s+)?bond\b": "James Bond",
    r"\bharry potter\b": "Harry Potter",
    r"\blord of the rings\b": "The Lord of the Rings",
    r"\bstar wars\b": "Star Wars",
    r"\bjurassic park\b": "Jurassic Park",
    r"\bjurassic world\b": "Jurassic Park",
    r"\bjohn wick\b": "John Wick",
}

def resolve_canonical_tags(
    tmdb_facts: Optional[Dict[str, Any]],
    wikidata_facts: Optional[Dict[str, Any]] = None,
    plex_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[List[str], List[str], List[str], List[str], Dict[str, Any]]:
    """
    Resolves raw metadata facts into canonical tags.
    Returns:
        - brand_tags: List[str]
        - franchise_tags: List[str]
        - universe_tags: List[str]
        - source_property_tags: List[str]
        - evidence_json: Dict[str, Any]
    """
    brand_tags = set()
    franchise_tags = set()
    universe_tags = set()
    source_property_tags = set()
    
    evidence = {
        "brand": [],
        "franchise": [],
        "universe": [],
        "source_property": []
    }
    
    raw_candidates = []
    
    if tmdb_facts:
        if tmdb_facts.get("collection"):
            raw_candidates.append(("tmdb", "collection", tmdb_facts["collection"]))
        for pc in tmdb_facts.get("production_companies", []):
            raw_candidates.append(("tmdb", "production_company", pc))
        for kw in tmdb_facts.get("keywords", []):
            raw_candidates.append(("tmdb", "keyword", kw))
        if tmdb_facts.get("title"):
            raw_candidates.append(("tmdb", "title", tmdb_facts["title"]))
            
    if wikidata_facts:
        for s in wikidata_facts.get("series", []):
            raw_candidates.append(("wikidata", "series", s))
        for b in wikidata_facts.get("based_on", []):
            raw_candidates.append(("wikidata", "based_on", b))
            
    if plex_metadata:
        if plex_metadata.get("studio"):
            studio_val = plex_metadata["studio"]
            if isinstance(studio_val, str):
                for s in studio_val.split(","):
                    raw_candidates.append(("plex", "studio", s.strip()))
            elif isinstance(studio_val, list):
                for s in studio_val:
                    raw_candidates.append(("plex", "studio", s))
        if plex_metadata.get("collections"):
            col_val = plex_metadata["collections"]
            if isinstance(col_val, str):
                for c in col_val.split(","):
                    raw_candidates.append(("plex", "collection", c.strip()))
            elif isinstance(col_val, list):
                for c in col_val:
                    raw_candidates.append(("plex", "collection", c))

    def check_matches(value: str, rules_dict: Dict[str, str]) -> List[str]:
        matched = []
        for pattern, canonical in rules_dict.items():
            if re.search(pattern, value.lower()):
                matched.append(canonical)
        return matched

    for source, field_type, raw_val in raw_candidates:
        if not raw_val or not isinstance(raw_val, str):
            continue
            
        matched_brands = check_matches(raw_val, BRAND_RULES)
        for b in matched_brands:
            if b not in brand_tags:
                brand_tags.add(b)
                evidence["brand"].append({
                    "canonical": b,
                    "source": source,
                    "field": field_type,
                    "value": raw_val
                })
                
        matched_franchises = check_matches(raw_val, FRANCHISE_RULES)
        for f in matched_franchises:
            if f not in franchise_tags:
                if f in ("Alien", "Predator") and "Alien vs. Predator" in franchise_tags:
                    continue
                franchise_tags.add(f)
                evidence["franchise"].append({
                    "canonical": f,
                    "source": source,
                    "field": field_type,
                    "value": raw_val
                })
                
        matched_universes = check_matches(raw_val, UNIVERSE_RULES)
        for u in matched_universes:
            if u not in universe_tags:
                universe_tags.add(u)
                evidence["universe"].append({
                    "canonical": u,
                    "source": source,
                    "field": field_type,
                    "value": raw_val
                })
                
        matched_source_properties = check_matches(raw_val, SOURCE_PROPERTY_RULES)
        for sp in matched_source_properties:
            if sp not in source_property_tags:
                source_property_tags.add(sp)
                evidence["source_property"].append({
                    "canonical": sp,
                    "source": source,
                    "field": field_type,
                    "value": raw_val
                })

    if "Marvel Cinematic Universe" in universe_tags and "Marvel" not in brand_tags:
        brand_tags.add("Marvel")
        evidence["brand"].append({"canonical": "Marvel", "source": "implied_by_universe", "field": "universe_tags", "value": "Marvel Cinematic Universe"})
        
    if "DC Extended Universe" in universe_tags and "DC" not in brand_tags:
        brand_tags.add("DC")
        evidence["brand"].append({"canonical": "DC", "source": "implied_by_universe", "field": "universe_tags", "value": "DC Extended Universe"})
        
    if "Star Wars" in franchise_tags and "Lucasfilm" not in brand_tags:
        brand_tags.add("Lucasfilm")
        evidence["brand"].append({"canonical": "Lucasfilm", "source": "implied_by_franchise", "field": "franchise_tags", "value": "Star Wars"})

    for source, field_type, raw_val in raw_candidates:
        if field_type == "collection" and raw_val:
            if "Collection" in raw_val and raw_val not in franchise_tags:
                if not any(generic in raw_val.lower() for generic in ["favorite", "best", "my collection", "new collection"]):
                    franchise_tags.add(raw_val)
                    evidence["franchise"].append({
                        "canonical": raw_val,
                        "source": source,
                        "field": field_type,
                        "value": raw_val
                    })

    return sorted(list(brand_tags)), sorted(list(franchise_tags)), sorted(list(universe_tags)), sorted(list(source_property_tags)), evidence
