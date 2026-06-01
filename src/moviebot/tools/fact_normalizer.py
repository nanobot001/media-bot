import datetime
import logging
from typing import Any, Dict
from moviebot.core.enrichment import enrich_library_item
from moviebot.core.gemini_enrichment import enrich_library_item_with_gemini

logger = logging.getLogger(__name__)

class FactNormalizer:
    """
    Normalizes Wikidata raw facts and Plex metadata into structured DB tags.
    Supports rules-based and Gemini-based mapping.
    """

    @staticmethod
    def normalize_with_rules(facts: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
        # Start with standard rules-based enrichment
        base = enrich_library_item(item)
        
        # Ensure facts is a dictionary
        facts = facts or {}
            
        award_tags = []
        award_wins = {}
        award_nominations = {}
        acclaim_tags = []
        source_material_tags = []
        adaptation_type_tags = []
        popularity_tags = []
        cultural_impact_tags = []
        box_office_tier = None
        
        qid = facts.get("qid")
        box_office = facts.get("box_office")
        awards_received = facts.get("awards_received", [])
        nominated_for = facts.get("nominated_for", [])
        based_on = facts.get("based_on", [])
        series = facts.get("series", [])
        
        # 1. Awards & Nominations
        has_wins = False
        has_nominations = False
        
        # Populate award wins
        for award in awards_received:
            award_lower = award.lower()
            award_wins[award] = 1
            has_wins = True
            
            # Match tags
            if "academy award" in award_lower or "oscar" in award_lower:
                if "oscar_winner" not in award_tags:
                    award_tags.append("oscar_winner")
            if "golden globe" in award_lower:
                if "golden_globe_winner" not in award_tags:
                    award_tags.append("golden_globe_winner")
            if "bafta" in award_lower:
                if "bafta_winner" not in award_tags:
                    award_tags.append("bafta_winner")
            if any(term in award_lower for term in ["hugo", "saturn", "festival", "palme d'or", "golden lion", "golden bear", "sundance", "cannes"]):
                if "festival_winner" not in award_tags:
                    award_tags.append("festival_winner")
                    
        # Populate award nominations
        for nomination in nominated_for:
            award_lower = nomination.lower()
            award_nominations[nomination] = 1
            has_nominations = True
            
            if "academy award" in award_lower or "oscar" in award_lower:
                if "oscar_nominee" not in award_tags:
                    award_tags.append("oscar_nominee")
            if "golden globe" in award_lower:
                if "golden_globe_nominee" not in award_tags:
                    award_tags.append("golden_globe_nominee")
            if "bafta" in award_lower:
                if "bafta_nominee" not in award_tags:
                    award_tags.append("bafta_nominee")
                    
        if has_wins or has_nominations:
            award_tags.append("award_winning")
            
        # Acclaim
        rating = item.get("rating")
        try:
            rating_val = float(rating) if rating is not None else 0.0
        except (ValueError, TypeError):
            rating_val = 0.0
            
        if rating_val >= 8.0 or len(award_wins) >= 2:
            acclaim_tags.append("critically_acclaimed")
            
        # 2. Source Material
        for source in based_on:
            src_lower = source.lower()
            if any(term in src_lower for term in ["novel", "book", "literary", "memoir", "autobiography", "novelization"]):
                if "based_on_book" not in source_material_tags:
                    source_material_tags.append("based_on_book")
                if "book_adaptation" not in adaptation_type_tags:
                    adaptation_type_tags.append("book_adaptation")
            if any(term in src_lower for term in ["comic", "comics", "manga", "graphic novel"]):
                if "comic_book" not in source_material_tags:
                    source_material_tags.append("comic_book")
                if "comic_adaptation" not in adaptation_type_tags:
                    adaptation_type_tags.append("comic_adaptation")
            if "video game" in src_lower:
                if "video_game" not in source_material_tags:
                    source_material_tags.append("video_game")
                if "game_adaptation" not in adaptation_type_tags:
                    adaptation_type_tags.append("game_adaptation")
            if any(term in src_lower for term in ["true story", "biography", "historical", "life of"]):
                if "true_story" not in source_material_tags:
                    source_material_tags.append("true_story")
                    
        # 3. Series / Sequel / Franchise
        title = (item.get("title") or "").lower()
        has_sequel_marker = any(
            f" {marker}" in title or title.endswith(f" {marker}")
            for marker in ["2", "3", "4", "ii", "iii", "iv", "v", "part", "return of", "reloaded", "revolutions", "endgame", "ragnarok", "forever"]
        )
        if series:
            if "franchise" not in adaptation_type_tags:
                adaptation_type_tags.append("franchise")
            if has_sequel_marker:
                if "sequel" not in source_material_tags:
                    source_material_tags.append("sequel")
                if "sequel_adaptation" not in adaptation_type_tags:
                    adaptation_type_tags.append("sequel_adaptation")
                    
        # 4. Box Office & Popularity
        if box_office is not None:
            if box_office >= 500000000:
                box_office_tier = "mega_blockbuster"
                popularity_tags.extend(["blockbuster", "mainstream"])
            elif box_office >= 100000000:
                box_office_tier = "blockbuster"
                popularity_tags.extend(["blockbuster", "mainstream"])
            elif box_office >= 10000000:
                box_office_tier = "mainstream"
                popularity_tags.append("mainstream")
            else:
                box_office_tier = "low_budget"
                
        # Cult classic / classic
        year = item.get("year")
        try:
            year_val = int(year) if year is not None else datetime.datetime.now().year
        except (ValueError, TypeError):
            year_val = datetime.datetime.now().year
            
        current_year = datetime.datetime.now().year
        is_old = (current_year - year_val) >= 25
        
        if is_old and rating_val >= 7.8:
            cultural_impact_tags.append("classic")
            if "classic" not in popularity_tags:
                popularity_tags.append("classic")
                
        # 5. Local Curation Cues (Plex labels and collections)
        import json
        def safe_json_list(val):
            if not val:
                return []
            try:
                if isinstance(val, list):
                    return [str(x).lower().strip() for x in val]
                parsed = json.loads(val)
                if isinstance(parsed, list):
                    return [str(x).lower().strip() for x in parsed]
            except Exception:
                pass
            if isinstance(val, str):
                return [x.lower().strip() for x in val.split(",") if x.strip()]
            return []

        local_cues = safe_json_list(item.get("labels")) + safe_json_list(item.get("collections"))
        
        has_local_curation = False
        for cue in local_cues:
            if any(term in cue for term in ["oscar winner", "academy award winner", "oscar-winner"]):
                if "oscar_winner" not in award_tags:
                    award_tags.append("oscar_winner")
                has_local_curation = True
            if any(term in cue for term in ["oscar nominee", "academy award nominee", "oscar-nominee"]):
                if "oscar_nominee" not in award_tags:
                    award_tags.append("oscar_nominee")
                has_local_curation = True
            if any(term in cue for term in ["award winning", "award-winning"]):
                if "award_winning" not in award_tags:
                    award_tags.append("award_winning")
                has_local_curation = True
            if any(term in cue for term in ["critically acclaimed", "acclaimed"]):
                if "critically_acclaimed" not in acclaim_tags:
                    acclaim_tags.append("critically_acclaimed")
                has_local_curation = True
            
            # Check local cues for source material
            if any(term in cue for term in ["based on book", "based on a book", "novel", "book adaptation"]):
                if "based_on_book" not in source_material_tags:
                    source_material_tags.append("based_on_book")
                if "book_adaptation" not in adaptation_type_tags:
                    adaptation_type_tags.append("book_adaptation")
                has_local_curation = True
            if any(term in cue for term in ["true story", "based on a true story", "biography"]):
                if "true_story" not in source_material_tags:
                    source_material_tags.append("true_story")
                has_local_curation = True
            if "video game" in cue:
                if "video_game" not in source_material_tags:
                    source_material_tags.append("video_game")
                if "game_adaptation" not in adaptation_type_tags:
                    adaptation_type_tags.append("game_adaptation")
                has_local_curation = True

            # Check local cues for popularity & cultural impact
            if any(term in cue for term in ["cult classic", "cult"]):
                if "cult_classic" not in cultural_impact_tags:
                    cultural_impact_tags.append("cult_classic")
                if "cult_classic" not in popularity_tags:
                    popularity_tags.append("cult_classic")
                has_local_curation = True
            if "classic" in cue:  # matches "classic", "canadian classic", etc.
                if "classic" not in cultural_impact_tags:
                    cultural_impact_tags.append("classic")
                if "classic" not in popularity_tags:
                    popularity_tags.append("classic")
                has_local_curation = True
            if "blockbuster" in cue:
                if "blockbuster" not in popularity_tags:
                    popularity_tags.append("blockbuster")
                box_office_tier = "blockbuster"
                has_local_curation = True
            if "hidden gem" in cue:
                if "hidden_gem" not in popularity_tags:
                    popularity_tags.append("hidden_gem")
                has_local_curation = True
            if any(term in cue for term in ["popular", "mainstream"]):
                if "mainstream" not in popularity_tags:
                    popularity_tags.append("mainstream")
                has_local_curation = True

        if award_tags and "award_winning" not in award_tags:
            award_tags.append("award_winning")

        # Clean list duplicates
        popularity_tags = sorted(list(set(popularity_tags)))
        
        hard_fact_sources = {
            "source": "wikidata" if qid else ("plex_curation" if has_local_curation else "rules_inferred"),
            "qid": qid,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "fields_supported": ["box_office", "awards", "nominations", "based_on", "series"]
        }
        
        base.update({
            "award_tags": sorted(list(set(award_tags))),
            "award_wins_json": award_wins,
            "award_nominations_json": award_nominations,
            "acclaim_tags": sorted(list(set(acclaim_tags))),
            "source_material_tags": sorted(list(set(source_material_tags))),
            "adaptation_type_tags": sorted(list(set(adaptation_type_tags))),
            "popularity_tags": popularity_tags,
            "cultural_impact_tags": sorted(list(set(cultural_impact_tags))),
            "box_office_tier": box_office_tier,
            "hard_fact_sources_json": hard_fact_sources,
        })
        
        # Merge into the outer enrichment_json
        base["enrichment_json"]["hard_facts"] = {
            "awards": {
                "tags": base["award_tags"],
                "wins": base["award_wins_json"],
                "nominations": base["award_nominations_json"],
                "acclaim": base["acclaim_tags"],
            },
            "source_material": base["source_material_tags"],
            "adaptation_types": base["adaptation_type_tags"],
            "popularity": {
                "tags": base["popularity_tags"],
                "cultural_impact": base["cultural_impact_tags"],
                "box_office_tier": base["box_office_tier"],
            },
            "sources": base["hard_fact_sources_json"],
        }
        
        return base

    @staticmethod
    async def normalize_with_gemini(facts: Dict[str, Any], item: Dict[str, Any]) -> Dict[str, Any]:
        """Runs Gemini enrichment passing BOTH item metadata and Wikidata facts.
        
        Merge strategy (per hard-fact field):
          - Rules-based value wins when it has data (Wikidata or Plex curation).
          - Gemini value is kept as fallback when rules produce nothing.
          - Provenance is tracked per-field in hard_fact_sources_json.
        """
        # 1. Run Gemini to get soft tags (themes, tones, setting, premise, content warnings)
        gemini_res = await enrich_library_item_with_gemini(item, wikidata_facts=facts)
        
        # 2. Run rules-based normalization to get authority-backed hard facts
        rules_res = FactNormalizer.normalize_with_rules(facts, item)

        # 3. Smart merge: rules win when non-empty, Gemini fills the gaps
        def _has_data(val):
            """True when val is a non-empty list, non-empty dict, or non-None scalar."""
            if val is None:
                return False
            if isinstance(val, (list, dict)):
                return len(val) > 0
            return True

        # Fields whose values are lists
        list_fields = [
            "award_tags",
            "acclaim_tags",
            "source_material_tags",
            "adaptation_type_tags",
            "popularity_tags",
            "cultural_impact_tags",
        ]
        # Fields whose values are dicts
        dict_fields = [
            "award_wins_json",
            "award_nominations_json",
        ]
        # Scalar field
        scalar_fields = [
            "box_office_tier",
        ]
        
        provenance = {}  # track which source was used per field
        
        for field in list_fields:
            rules_val = rules_res.get(field, [])
            gemini_val = gemini_res.get(field, [])
            if _has_data(rules_val):
                # Rules have authoritative data — use it, but union with Gemini
                merged = sorted(set(rules_val) | set(gemini_val))
                gemini_res[field] = merged
                provenance[field] = "rules+gemini" if _has_data(gemini_val) else "rules"
            elif _has_data(gemini_val):
                # Rules are empty — keep Gemini's answer as fallback
                provenance[field] = "gemini_fallback"
            else:
                gemini_res[field] = []
                provenance[field] = "empty"

        for field in dict_fields:
            rules_val = rules_res.get(field, {})
            gemini_val = gemini_res.get(field, {})
            if _has_data(rules_val):
                gemini_res[field] = rules_val
                provenance[field] = "rules"
            elif _has_data(gemini_val):
                provenance[field] = "gemini_fallback"
            else:
                gemini_res[field] = {}
                provenance[field] = "empty"

        for field in scalar_fields:
            rules_val = rules_res.get(field)
            gemini_val = gemini_res.get(field)
            if _has_data(rules_val):
                gemini_res[field] = rules_val
                provenance[field] = "rules"
            elif _has_data(gemini_val):
                provenance[field] = "gemini_fallback"
            else:
                gemini_res[field] = None
                provenance[field] = "empty"

        # Build merged hard_fact_sources with provenance
        rules_sources = rules_res.get("hard_fact_sources_json", {})
        rules_sources["field_provenance"] = provenance
        gemini_res["hard_fact_sources_json"] = rules_sources
            
        # Rebuild nested hard_facts block in enrichment_json
        if "enrichment_json" in gemini_res:
            gemini_res["enrichment_json"]["hard_facts"] = {
                "awards": {
                    "tags": gemini_res["award_tags"],
                    "wins": gemini_res["award_wins_json"],
                    "nominations": gemini_res["award_nominations_json"],
                    "acclaim": gemini_res["acclaim_tags"],
                },
                "source_material": gemini_res["source_material_tags"],
                "adaptation_types": gemini_res["adaptation_type_tags"],
                "popularity": {
                    "tags": gemini_res["popularity_tags"],
                    "cultural_impact": gemini_res["cultural_impact_tags"],
                    "box_office_tier": gemini_res["box_office_tier"],
                },
                "sources": gemini_res["hard_fact_sources_json"],
            }
            
        return gemini_res
