import json
import os
from typing import Any, Dict, List, Optional

import httpx

from moviebot.config import settings
from moviebot.core.enrichment import enrich_library_item


GEMINI_ENRICHMENT_SOURCE = "gemini"
RULE_FALLBACK_SOURCE = "rules_fallback"


def _normalize_model(model: str) -> str:
    return (model or "gemini-2.5-flash").removeprefix("models/")


def _list(value: Any) -> List[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _warning_payload(raw: Any) -> Dict[str, Dict[str, Any]]:
    warnings = _dict(raw)
    normalized: Dict[str, Dict[str, Any]] = {}
    for key, value in warnings.items():
        payload = _dict(value)
        level = str(payload.get("level") or "unknown").lower()
        if level not in {"none", "mild", "moderate", "strong", "extreme", "unknown"}:
            level = "unknown"
        normalized[str(key)] = {
            "level": level,
            "confidence": float(payload.get("confidence") or 0.0),
            "evidence": payload.get("evidence"),
        }
    return normalized


def _json_prompt(item: Dict[str, Any], wikidata_facts: Optional[Dict[str, Any]] = None) -> str:
    prompt_payload = {
        "task": "Generate typed metadata for a movie library search database. Return only JSON.",
        "schema": {
            "story_locations": "Places where the narrative/events take place.",
            "filming_locations": "Places where the movie or performance was filmed, if known from input.",
            "production_countries": "Production origin countries, only if explicit.",
            "mentioned_locations": "Places only mentioned but not core setting.",
            "event_locations": "Concert, documentary event, or stage-performance venue/location.",
            "central_premise_tags": "Main premise tags.",
            "subplot_tags": "Secondary premise tags.",
            "protagonist_tags": "Main character types/roles.",
            "antagonist_tags": "Antagonist types/roles.",
            "supporting_character_tags": "Important supporting character types/roles.",
            "central_theme_tags": "Central themes.",
            "minor_theme_tags": "Minor themes.",
            "dominant_tone_tags": "Most dominant tone tags.",
            "secondary_tone_tags": "Secondary tone tags.",
            "ending_tone_tags": "Ending tone only if explicit.",
            "format_tags": "Format/medium such as documentary, animation, concert film, musical.",
            "visual_style_tags": "Visual style only if explicit.",
            "narrative_structure_tags": "Narrative structure only if explicit.",
            "music_role_tags": "How music functions, such as musical theatre, concert film, score-focused.",
            "award_tags": "Sourced award/acclaim tags only, such as oscar winner or best picture nominee.",
            "award_wins": "Object of known awards won, only when supported by provided metadata.",
            "award_nominations": "Object of known nominations, only when supported by provided metadata.",
            "acclaim_tags": "Sourced acclaim tags such as critically acclaimed or festival winner.",
            "source_material_tags": "Sourced original material facts, such as based on a book or true story.",
            "adaptation_type_tags": "Sourced adaptation/remake/sequel/reboot facts.",
            "popularity_tags": "Sourced commercial/popularity facts such as blockbuster.",
            "cultural_impact_tags": "Sourced cultural footprint facts such as classic or cult classic.",
            "box_office_tier": "commercial tier only if supported by source metadata.",
            "hard_fact_sources": "Object naming source/evidence for awards, source material, and popularity facts.",
            "content_warnings": {
                "warning_name": {
                    "level": "none|mild|moderate|strong|extreme|unknown",
                    "confidence": "0.0 to 1.0",
                    "evidence": "short phrase from input or null",
                }
            },
            "depicted_content_warning_tags": "Warnings shown/depicted.",
            "discussed_content_warning_tags": "Warnings mentioned/contextual but not depicted.",
            "field_confidence": "Object keyed by field/tag.",
            "field_evidence": "Object keyed by field/tag with short input evidence.",
        },
        "rules": [
            "Use only evidence from the provided metadata and wikidata_facts.",
            "Do not infer filming or production country unless explicit.",
            "Distinguish story locations from event/filming locations.",
            "Prefer empty arrays over guesses.",
            "Awards, source material, and popularity are hard facts. Fill them only when explicit in provided metadata or wikidata_facts.",
            "Keep tags lowercase except proper-place names.",
            "Use 'wikidata_facts' as the primary source for 'award_tags', 'award_wins', 'award_nominations', 'source_material_tags', 'adaptation_type_tags', 'popularity_tags', 'cultural_impact_tags', 'box_office_tier', and 'hard_fact_sources'."
        ],
        "movie": {
            "title": item.get("title"),
            "year": item.get("year"),
            "genres": item.get("genres"),
            "directors": item.get("directors"),
            "studios": item.get("studios"),
            "writers": item.get("writers"),
            "producers": item.get("producers"),
            "cast": item.get("cast"),
            "countries": item.get("countries"),
            "content_rating": item.get("content_rating"),
            "audience_rating": item.get("audience_rating"),
            "tagline": item.get("tagline"),
            "originally_available_at": item.get("originally_available_at"),
            "labels": item.get("labels"),
            "collections": item.get("collections"),
            "synopsis": item.get("synopsis"),
        },
    }
    if wikidata_facts:
        prompt_payload["wikidata_facts"] = wikidata_facts

    return json.dumps(prompt_payload, ensure_ascii=False)


def normalize_gemini_enrichment(item: Dict[str, Any], raw: Dict[str, Any], model: str) -> Dict[str, Any]:
    base = enrich_library_item(item)
    warnings = _warning_payload(raw.get("content_warnings"))
    warning_tags = [key for key, payload in warnings.items() if payload.get("level") not in (None, "none", "unknown")]

    story_locations = _list(raw.get("story_locations"))
    event_locations = _list(raw.get("event_locations"))
    all_locations = sorted(set(story_locations + event_locations + _list(raw.get("filming_locations")) + _list(raw.get("mentioned_locations"))))

    base.update(
        {
            "setting_locations": all_locations,
            "story_locations": story_locations,
            "filming_locations": _list(raw.get("filming_locations")),
            "production_countries": _list(raw.get("production_countries")),
            "mentioned_locations": _list(raw.get("mentioned_locations")),
            "event_locations": event_locations,
            "premise_tags": sorted(set(_list(raw.get("central_premise_tags")) + _list(raw.get("subplot_tags")))),
            "central_premise_tags": _list(raw.get("central_premise_tags")),
            "subplot_tags": _list(raw.get("subplot_tags")),
            "character_tags": sorted(set(_list(raw.get("protagonist_tags")) + _list(raw.get("antagonist_tags")) + _list(raw.get("supporting_character_tags")))),
            "protagonist_tags": _list(raw.get("protagonist_tags")),
            "antagonist_tags": _list(raw.get("antagonist_tags")),
            "supporting_character_tags": _list(raw.get("supporting_character_tags")),
            "theme_tags": sorted(set(_list(raw.get("central_theme_tags")) + _list(raw.get("minor_theme_tags")))),
            "central_theme_tags": _list(raw.get("central_theme_tags")),
            "minor_theme_tags": _list(raw.get("minor_theme_tags")),
            "tone_tags": sorted(set(_list(raw.get("dominant_tone_tags")) + _list(raw.get("secondary_tone_tags")) + _list(raw.get("ending_tone_tags")))),
            "dominant_tone_tags": _list(raw.get("dominant_tone_tags")),
            "secondary_tone_tags": _list(raw.get("secondary_tone_tags")),
            "ending_tone_tags": _list(raw.get("ending_tone_tags")),
            "craft_tags": sorted(set(_list(raw.get("format_tags")) + _list(raw.get("visual_style_tags")) + _list(raw.get("narrative_structure_tags")) + _list(raw.get("music_role_tags")))),
            "format_tags": _list(raw.get("format_tags")),
            "visual_style_tags": _list(raw.get("visual_style_tags")),
            "narrative_structure_tags": _list(raw.get("narrative_structure_tags")),
            "music_role_tags": _list(raw.get("music_role_tags")),
            "content_warning_tags": warning_tags,
            "content_warnings_json": warnings,
            "depicted_content_warning_tags": _list(raw.get("depicted_content_warning_tags")),
            "discussed_content_warning_tags": _list(raw.get("discussed_content_warning_tags")),
            "award_tags": _list(raw.get("award_tags")),
            "award_wins_json": _dict(raw.get("award_wins")),
            "award_nominations_json": _dict(raw.get("award_nominations")),
            "acclaim_tags": _list(raw.get("acclaim_tags")),
            "source_material_tags": _list(raw.get("source_material_tags")),
            "adaptation_type_tags": _list(raw.get("adaptation_type_tags")),
            "popularity_tags": _list(raw.get("popularity_tags")),
            "cultural_impact_tags": _list(raw.get("cultural_impact_tags")),
            "box_office_tier": raw.get("box_office_tier") if isinstance(raw.get("box_office_tier"), str) else None,
            "hard_fact_sources_json": _dict(raw.get("hard_fact_sources")),
            "field_confidence_json": _dict(raw.get("field_confidence")),
            "field_evidence_json": _dict(raw.get("field_evidence")),
            "enrichment_model": model,
        }
    )
    base["enrichment_json"] = {
        **base["enrichment_json"],
        "source": GEMINI_ENRICHMENT_SOURCE,
        "gemini_model": model,
        "geography": {
            "story_locations": base["story_locations"],
            "filming_locations": base["filming_locations"],
            "production_countries": base["production_countries"],
            "mentioned_locations": base["mentioned_locations"],
            "event_locations": base["event_locations"],
        },
        "content_warnings": {
            "by_warning": warnings,
            "depicted": base["depicted_content_warning_tags"],
            "discussed": base["discussed_content_warning_tags"],
        },
        "hard_facts": {
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
        },
    }
    return base


async def enrich_library_item_with_gemini(item: Dict[str, Any], wikidata_facts: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    api_key = settings.gemini_api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        fallback = enrich_library_item(item)
        fallback["enrichment_json"]["source"] = RULE_FALLBACK_SOURCE
        return fallback

    model = _normalize_model(settings.gemini_enrichment_model)
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload = {
        "contents": [{"parts": [{"text": _json_prompt(item, wikidata_facts)}]}],
        "generationConfig": {
            "temperature": 0.1,
            "response_mime_type": "application/json",
        },
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post(url, headers={"x-goog-api-key": api_key}, json=payload)
        res.raise_for_status()
        data = res.json()
    text = data["candidates"][0]["content"]["parts"][0]["text"]
    raw = json.loads(text)
    return normalize_gemini_enrichment(item, raw, model)
