import datetime
import json
import re
from typing import Any, Dict, Iterable, List, Optional

ENRICHMENT_VERSION = "structured-enrichment-v2"
ENRICHMENT_MODEL = "moviebot-rule-enricher-v1"
CONTENT_WARNING_LEVELS = ("none", "mild", "moderate", "strong", "extreme", "unknown")


LOCATION_ALIASES = {
    "Canada": [
        "canada", "canadian", "calgary", "newfoundland", "prince edward island",
        "toronto", "vancouver", "montreal", "quebec", "ontario", "british columbia",
        "nova scotia", "alberta", "manitoba", "saskatchewan", "yukon"
    ],
    "New York": ["new york", "new york city", "nyc", "manhattan", "brooklyn", "queens", "bronx"],
    "Los Angeles": ["los angeles", "hollywood"],
    "California": ["california"],
    "Chicago": ["chicago"],
    "San Francisco": ["san francisco"],
    "Texas": ["texas"],
    "Florida": ["florida"],
    "Washington": ["washington", "washington dc", "washington, dc"],
    "United States": [
        "united states", "america", "american", "usa", "u.s.", "u.s.a."
    ],
    "United Kingdom": [
        "united kingdom", "england", "english", "london", "britain", "british",
        "scotland", "wales", "ireland"
    ],
    "Mexico": ["mexico", "mexican"],
    "China": ["china", "chinese", "canton", "beijing", "shanghai"],
    "Japan": ["japan", "japanese", "tokyo", "kyoto"],
    "France": ["france", "french", "paris"],
    "Germany": ["germany", "german", "berlin"],
    "Italy": ["italy", "italian", "rome"],
    "Space": ["space", "spaceship", "astronaut", "intergalactic", "galaxy", "planet", "moon"],
}


def canonical_location(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = value.strip().lower()
    if not normalized:
        return None
    for canonical, aliases in LOCATION_ALIASES.items():
        if normalized == canonical.lower() or normalized in aliases:
            return canonical
    return value.strip().title()

SETTING_ENVIRONMENT_KEYWORDS = {
    "small town": ["small town", "village"],
    "city": ["city", "urban", "metropolis"],
    "wilderness": ["wilderness", "forest", "jungle", "woods", "lapland"],
    "space": ["space", "spaceship", "galaxy", "planet", "moon"],
    "school": ["school", "college", "university", "academy"],
    "battlefield": ["battle", "war", "soldier", "army"],
    "ocean": ["ocean", "sea", "ship", "submarine"],
}

PREMISE_KEYWORDS = {
    "stranded travelers": ["stranded", "passengers"],
    "survival": ["survive", "survival", "wilderness", "escape"],
    "revenge": ["revenge", "avenge", "retaliates"],
    "investigation": ["detective", "investigate", "mystery", "case"],
    "rescue mission": ["rescue", "save"],
    "heist": ["heist", "steal", "robbery"],
    "competition": ["tournament", "championship", "contest", "compete"],
    "romance": ["fall in love", "romance", "love story"],
    "coming of age": ["coming-of-age", "teenager", "youth"],
}

CHARACTER_KEYWORDS = {
    "astronaut": ["astronaut"],
    "teacher": ["teacher"],
    "soldier": ["soldier", "marine", "army"],
    "detective": ["detective", "cop", "police"],
    "athlete": ["athlete", "hockey player", "basketball", "football", "bobsled"],
    "criminal": ["criminal", "thief", "assassin", "killer"],
    "family": ["family", "parent", "grandpa", "grandma", "daughter", "son"],
    "outsider": ["outsider", "outcast", "orphan"],
}

THEME_KEYWORDS = {
    "community": ["community", "town", "welcomed", "together"],
    "grief": ["grief", "loss", "mourning", "aftermath"],
    "resilience": ["resilience", "survive", "overcome"],
    "belonging": ["belonging", "accept", "home"],
    "identity": ["identity", "who he is", "who she is"],
    "corruption": ["corrupt", "conspiracy"],
    "sacrifice": ["sacrifice"],
    "friendship": ["friendship", "friends"],
    "family": ["family", "parent", "daughter", "son"],
}

TONE_KEYWORDS = {
    "warm": ["welcomed", "family", "community", "kindness"],
    "hopeful": ["hope", "new home", "save", "friendship"],
    "tense": ["thriller", "hunted", "chase", "battle"],
    "bleak": ["dystopian", "apocalyptic", "ruins"],
    "funny": ["comedy", "funny", "hilarious"],
    "bittersweet": ["aftermath", "grief", "loss"],
}

CRAFT_KEYWORDS = {
    "musical theatre": ["musical", "stage", "theater", "theatre"],
    "animation": ["animation", "animated"],
    "documentary": ["documentary", "archival", "interviews"],
    "nonlinear": ["flashback", "nonlinear"],
    "found footage": ["found footage"],
    "visual effects": ["cgi", "special effects"],
}

CONTENT_WARNING_RULES = {
    "violence": ("moderate", ["violence", "battle", "war", "kill", "killer", "assassin", "gun", "soldier"]),
    "gore": ("unknown", []),
    "body_horror": ("unknown", []),
    "jump_scares": ("unknown", []),
    "war_violence": ("moderate", ["war", "battlefield", "soldier", "army", "wwii"]),
    "gun_violence": ("moderate", ["gun", "shoot", "shooting"]),
    "animal_harm": ("unknown", []),
    "child_harm": ("unknown", []),
    "domestic_abuse": ("unknown", []),
    "sexual_content": ("unknown", []),
    "nudity": ("unknown", []),
    "sexual_violence": ("unknown", []),
    "self_harm": ("unknown", []),
    "suicide": ("unknown", []),
    "addiction": ("moderate", ["addiction", "drug", "alcoholic"]),
    "drug_use": ("moderate", ["drug", "ecstasy", "cocaine"]),
    "medical_trauma": ("mild", ["hospital", "medical", "illness", "disease"]),
    "death": ("moderate", ["death", "dead", "kill", "murder"]),
    "grief": ("moderate", ["grief", "loss", "mourning", "aftermath"]),
    "hate_speech_or_slurs": ("unknown", []),
}


def _safe_json_list(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        values = json.loads(raw)
    except Exception:
        return []
    if not isinstance(values, list):
        return []
    return [str(value) for value in values if value is not None]


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"\b{re.escape(phrase.lower())}\b", text) is not None


def _snippet(text: str, phrase: str, window: int = 90) -> str:
    lower = text.lower()
    idx = lower.find(phrase.lower())
    if idx < 0:
        return text[:window].strip()
    start = max(0, idx - window // 2)
    end = min(len(text), idx + len(phrase) + window // 2)
    return text[start:end].strip()


def _match_keyword_groups(text: str, groups: Dict[str, Iterable[str]]) -> tuple[List[str], Dict[str, str], Dict[str, float]]:
    values: List[str] = []
    evidence: Dict[str, str] = {}
    confidence: Dict[str, float] = {}
    for label, keywords in groups.items():
        for keyword in keywords:
            if _contains_phrase(text, keyword):
                values.append(label)
                evidence[label] = _snippet(text, keyword)
                confidence[label] = 0.82
                break
    return values, evidence, confidence


def _warning_payload(text: str) -> tuple[Dict[str, Dict[str, Any]], List[str], Dict[str, str], Dict[str, float]]:
    warnings: Dict[str, Dict[str, Any]] = {}
    tags: List[str] = []
    evidence: Dict[str, str] = {}
    confidence: Dict[str, float] = {}

    for warning, (level, keywords) in CONTENT_WARNING_RULES.items():
        matched_keyword = next((keyword for keyword in keywords if _contains_phrase(text, keyword)), None)
        if matched_keyword:
            warnings[warning] = {
                "level": level,
                "confidence": 0.65,
                "evidence": _snippet(text, matched_keyword),
            }
            tags.append(warning)
            evidence[warning] = warnings[warning]["evidence"]
            confidence[warning] = 0.65
        else:
            warnings[warning] = {
                "level": "unknown",
                "confidence": 0.0,
                "evidence": None,
            }

    return warnings, tags, evidence, confidence


def _typed_locations(locations: List[str], evidence: Dict[str, str]) -> Dict[str, List[str]]:
    typed = {
        "story_locations": [],
        "filming_locations": [],
        "production_countries": [],
        "mentioned_locations": [],
        "event_locations": [],
    }
    for location in locations:
        snippet = (evidence.get(location) or "").lower()
        if any(marker in snippet for marker in ("filmed", "performs", "performance", "stage", "theater", "theatre")):
            typed["event_locations"].append(location)
        elif any(marker in snippet for marker in ("mentions", "referenced", "told about")):
            typed["mentioned_locations"].append(location)
        else:
            typed["story_locations"].append(location)
    return typed


def _typed_content_warning_tags(warnings: Dict[str, Dict[str, Any]]) -> tuple[List[str], List[str]]:
    depicted: List[str] = []
    discussed: List[str] = []
    for warning, payload in warnings.items():
        level = str(payload.get("level") or "unknown").lower()
        if level == "unknown":
            continue
        evidence = str(payload.get("evidence") or "").lower()
        if any(marker in evidence for marker in ("aftermath", "grief", "mourning", "loss")):
            discussed.append(warning)
        else:
            depicted.append(warning)
    return depicted, discussed


def enrich_library_item(item: Dict[str, Any], now_iso: Optional[str] = None) -> Dict[str, Any]:
    synopsis = item.get("synopsis") or ""
    genres = _safe_json_list(item.get("genres"))
    title = item.get("title") or ""
    text = " ".join([title, synopsis, " ".join(genres)]).lower()
    now = now_iso or datetime.datetime.now(datetime.timezone.utc).isoformat()

    setting_locations, setting_evidence, setting_confidence = _match_keyword_groups(text, LOCATION_ALIASES)
    setting_environment, env_evidence, env_confidence = _match_keyword_groups(text, SETTING_ENVIRONMENT_KEYWORDS)
    premise_tags, premise_evidence, premise_confidence = _match_keyword_groups(text, PREMISE_KEYWORDS)
    character_tags, character_evidence, character_confidence = _match_keyword_groups(text, CHARACTER_KEYWORDS)
    theme_tags, theme_evidence, theme_confidence = _match_keyword_groups(text, THEME_KEYWORDS)
    tone_tags, tone_evidence, tone_confidence = _match_keyword_groups(text, TONE_KEYWORDS)
    craft_tags, craft_evidence, craft_confidence = _match_keyword_groups(text, CRAFT_KEYWORDS)
    warning_payload, warning_tags, warning_evidence, warning_confidence = _warning_payload(text)
    typed_locations = _typed_locations(setting_locations, setting_evidence)
    depicted_warning_tags, discussed_warning_tags = _typed_content_warning_tags(warning_payload)

    central_premise_tags = premise_tags
    subplot_tags: List[str] = []
    protagonist_tags = character_tags
    antagonist_tags = [tag for tag in character_tags if tag in ("criminal",)]
    supporting_character_tags: List[str] = []
    central_theme_tags = theme_tags[:2]
    minor_theme_tags = theme_tags[2:]
    dominant_tone_tags = tone_tags[:1]
    secondary_tone_tags = tone_tags[1:]
    ending_tone_tags: List[str] = []
    format_tags = [tag for tag in craft_tags if tag in ("animation", "documentary", "musical theatre")]
    visual_style_tags = [tag for tag in craft_tags if tag in ("found footage", "visual effects")]
    narrative_structure_tags = [tag for tag in craft_tags if tag in ("nonlinear",)]
    music_role_tags = [tag for tag in craft_tags if tag in ("musical theatre",)]
    award_tags: List[str] = []
    award_wins_json: Dict[str, Any] = {}
    award_nominations_json: Dict[str, Any] = {}
    acclaim_tags: List[str] = []
    source_material_tags: List[str] = []
    adaptation_type_tags: List[str] = []
    popularity_tags: List[str] = []
    cultural_impact_tags: List[str] = []
    box_office_tier = None
    hard_fact_sources_json: Dict[str, Any] = {}

    enrichment = {
        "schema_version": 2,
        "setting": {
            "locations": setting_locations,
            "environment": setting_environment,
            "time_period": [],
            "world_type": [],
            "confidence": max(setting_confidence.values(), default=0.0),
            "evidence": setting_evidence,
        },
        "geography": typed_locations,
        "premise": {
            "tags": premise_tags,
            "central": central_premise_tags,
            "subplots": subplot_tags,
            "plot_engine": premise_tags,
            "stakes": [],
            "confidence": max(premise_confidence.values(), default=0.0),
            "evidence": premise_evidence,
        },
        "characters": {
            "protagonist_types": character_tags,
            "protagonists": protagonist_tags,
            "antagonists": antagonist_tags,
            "supporting": supporting_character_tags,
            "relationship_focus": [tag for tag in character_tags if tag in ("family",)],
            "confidence": max(character_confidence.values(), default=0.0),
            "evidence": character_evidence,
        },
        "themes": {
            "values": theme_tags,
            "central": central_theme_tags,
            "minor": minor_theme_tags,
            "confidence": max(theme_confidence.values(), default=0.0),
            "evidence": theme_evidence,
        },
        "tone": {
            "values": tone_tags,
            "dominant": dominant_tone_tags,
            "secondary": secondary_tone_tags,
            "ending": ending_tone_tags,
            "confidence": max(tone_confidence.values(), default=0.0),
            "evidence": tone_evidence,
        },
        "craft": {
            "values": craft_tags,
            "format": format_tags,
            "visual_style": visual_style_tags,
            "narrative_structure": narrative_structure_tags,
            "music_role": music_role_tags,
            "confidence": max(craft_confidence.values(), default=0.0),
            "evidence": craft_evidence,
        },
        "content_warnings": {
            "by_warning": warning_payload,
            "depicted": depicted_warning_tags,
            "discussed": discussed_warning_tags,
        },
        "hard_facts": {
            "awards": {
                "tags": award_tags,
                "wins": award_wins_json,
                "nominations": award_nominations_json,
            },
            "source_material": source_material_tags,
            "adaptation_types": adaptation_type_tags,
            "popularity": {
                "tags": popularity_tags,
                "cultural_impact": cultural_impact_tags,
                "box_office_tier": box_office_tier,
            },
            "sources": hard_fact_sources_json,
        },
    }

    confidence = {
        "setting": {**setting_confidence, **env_confidence},
        "premise": premise_confidence,
        "characters": character_confidence,
        "themes": theme_confidence,
        "tone": tone_confidence,
        "craft": craft_confidence,
        "content_warnings": warning_confidence,
    }
    evidence = {
        "setting": {**setting_evidence, **env_evidence},
        "premise": premise_evidence,
        "characters": character_evidence,
        "themes": theme_evidence,
        "tone": tone_evidence,
        "craft": craft_evidence,
        "content_warnings": warning_evidence,
    }

    return {
        "enrichment_json": enrichment,
        "setting_locations": setting_locations,
        "premise_tags": premise_tags,
        "character_tags": character_tags,
        "theme_tags": theme_tags,
        "tone_tags": tone_tags,
        "craft_tags": craft_tags,
        "content_warning_tags": warning_tags,
        "content_warnings_json": warning_payload,
        "field_confidence_json": confidence,
        "field_evidence_json": evidence,
        "enrichment_version": ENRICHMENT_VERSION,
        "enrichment_model": ENRICHMENT_MODEL,
        "enrichment_updated_at": now,
        **typed_locations,
        "central_premise_tags": central_premise_tags,
        "subplot_tags": subplot_tags,
        "protagonist_tags": protagonist_tags,
        "antagonist_tags": antagonist_tags,
        "supporting_character_tags": supporting_character_tags,
        "central_theme_tags": central_theme_tags,
        "minor_theme_tags": minor_theme_tags,
        "dominant_tone_tags": dominant_tone_tags,
        "secondary_tone_tags": secondary_tone_tags,
        "ending_tone_tags": ending_tone_tags,
        "format_tags": format_tags,
        "visual_style_tags": visual_style_tags,
        "narrative_structure_tags": narrative_structure_tags,
        "music_role_tags": music_role_tags,
        "depicted_content_warning_tags": depicted_warning_tags,
        "discussed_content_warning_tags": discussed_warning_tags,
        "award_tags": award_tags,
        "award_wins_json": award_wins_json,
        "award_nominations_json": award_nominations_json,
        "acclaim_tags": acclaim_tags,
        "source_material_tags": source_material_tags,
        "adaptation_type_tags": adaptation_type_tags,
        "popularity_tags": popularity_tags,
        "cultural_impact_tags": cultural_impact_tags,
        "box_office_tier": box_office_tier,
        "hard_fact_sources_json": hard_fact_sources_json,
    }


def serialize_enrichment(enrichment: Dict[str, Any]) -> Dict[str, str]:
    serialized: Dict[str, str] = {}
    json_fields = {
        "enrichment_json",
        "setting_locations",
        "premise_tags",
        "character_tags",
        "theme_tags",
        "tone_tags",
        "craft_tags",
        "content_warning_tags",
        "content_warnings_json",
        "field_confidence_json",
        "field_evidence_json",
        "story_locations",
        "filming_locations",
        "production_countries",
        "mentioned_locations",
        "event_locations",
        "central_premise_tags",
        "subplot_tags",
        "protagonist_tags",
        "antagonist_tags",
        "supporting_character_tags",
        "central_theme_tags",
        "minor_theme_tags",
        "dominant_tone_tags",
        "secondary_tone_tags",
        "ending_tone_tags",
        "format_tags",
        "visual_style_tags",
        "narrative_structure_tags",
        "music_role_tags",
        "depicted_content_warning_tags",
        "discussed_content_warning_tags",
        "award_tags",
        "award_wins_json",
        "award_nominations_json",
        "acclaim_tags",
        "source_material_tags",
        "adaptation_type_tags",
        "popularity_tags",
        "cultural_impact_tags",
        "hard_fact_sources_json",
    }
    for key, value in enrichment.items():
        if value is None:
            serialized[key] = None
        else:
            serialized[key] = json.dumps(value, ensure_ascii=False) if key in json_fields else str(value)
    return serialized
