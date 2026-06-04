"""
Auto-enrichment module: enriches a single library item and optionally posts
a rich Discord embed card with the results.
"""
import asyncio
import datetime
import json
import logging
from typing import Dict, Any, Optional

from moviebot.tools.fact_normalizer import FactNormalizer
from moviebot.tools.fact_provider import WikidataFactProvider
from moviebot.core.enrichment import enrich_library_item, serialize_enrichment
from moviebot.db.repositories import LibraryItemRepository

logger = logging.getLogger(__name__)


async def auto_enrich_item(item: Dict[str, Any], provider: str = "gemini") -> Optional[Dict[str, Any]]:
    """
    Enriches a single library item using the specified provider.
    Returns the enrichment dict, or None on failure.
    """
    title = item.get("title", "Unknown")
    year = item.get("year")
    imdb_id = item.get("imdb_id")

    try:
        fact_provider = WikidataFactProvider()
        facts = fact_provider.get_facts(
            title=title,
            year=year,
            imdb_id=imdb_id
        ) or {}
    except Exception as e:
        logger.warning(f"[Auto-Enrich] Wikidata fetch failed for {title}: {e}")
        facts = {}

    try:
        if provider == "gemini":
            enrichment = await FactNormalizer.normalize_with_gemini(facts, item)
        else:
            enrichment = FactNormalizer.normalize_with_rules(facts, item)
    except Exception as e:
        logger.error(f"[Auto-Enrich] Enrichment failed for {title}: {e}")
        # Fallback to rules with no facts
        enrichment = FactNormalizer.normalize_with_rules({}, item)
        enrichment["enrichment_json"]["source"] = "rules_fallback"

    # Persist to database
    try:
        serialized = serialize_enrichment(enrichment)
        LibraryItemRepository.update_enrichment(
            id=item["id"],
            enrichment_json=serialized["enrichment_json"],
            setting_locations=serialized["setting_locations"],
            premise_tags=serialized["premise_tags"],
            character_tags=serialized["character_tags"],
            theme_tags=serialized["theme_tags"],
            tone_tags=serialized["tone_tags"],
            craft_tags=serialized["craft_tags"],
            content_warning_tags=serialized["content_warning_tags"],
            content_warnings_json=serialized["content_warnings_json"],
            field_confidence_json=serialized["field_confidence_json"],
            field_evidence_json=serialized["field_evidence_json"],
            enrichment_version=serialized["enrichment_version"],
            enrichment_model=serialized["enrichment_model"],
            enrichment_updated_at=serialized["enrichment_updated_at"],
            story_locations=serialized.get("story_locations", "[]"),
            filming_locations=serialized.get("filming_locations", "[]"),
            production_countries=serialized.get("production_countries", "[]"),
            mentioned_locations=serialized.get("mentioned_locations", "[]"),
            event_locations=serialized.get("event_locations", "[]"),
            central_premise_tags=serialized.get("central_premise_tags", "[]"),
            subplot_tags=serialized.get("subplot_tags", "[]"),
            protagonist_tags=serialized.get("protagonist_tags", "[]"),
            antagonist_tags=serialized.get("antagonist_tags", "[]"),
            supporting_character_tags=serialized.get("supporting_character_tags", "[]"),
            central_theme_tags=serialized.get("central_theme_tags", "[]"),
            minor_theme_tags=serialized.get("minor_theme_tags", "[]"),
            dominant_tone_tags=serialized.get("dominant_tone_tags", "[]"),
            secondary_tone_tags=serialized.get("secondary_tone_tags", "[]"),
            ending_tone_tags=serialized.get("ending_tone_tags", "[]"),
            format_tags=serialized.get("format_tags", "[]"),
            visual_style_tags=serialized.get("visual_style_tags", "[]"),
            narrative_structure_tags=serialized.get("narrative_structure_tags", "[]"),
            music_role_tags=serialized.get("music_role_tags", "[]"),
            depicted_content_warning_tags=serialized.get("depicted_content_warning_tags", "[]"),
            discussed_content_warning_tags=serialized.get("discussed_content_warning_tags", "[]"),
            award_tags=serialized.get("award_tags", "[]"),
            award_wins_json=serialized.get("award_wins_json", "{}"),
            award_nominations_json=serialized.get("award_nominations_json", "{}"),
            acclaim_tags=serialized.get("acclaim_tags", "[]"),
            source_material_tags=serialized.get("source_material_tags", "[]"),
            adaptation_type_tags=serialized.get("adaptation_type_tags", "[]"),
            popularity_tags=serialized.get("popularity_tags", "[]"),
            cultural_impact_tags=serialized.get("cultural_impact_tags", "[]"),
            box_office_tier=serialized.get("box_office_tier"),
            hard_fact_sources_json=serialized.get("hard_fact_sources_json", "{}"),
        )
        logger.info(f"[Auto-Enrich] Saved enrichment for {title} ({year})")
    except Exception as e:
        logger.error(f"[Auto-Enrich] Failed to persist enrichment for {title}: {e}")
        return None

    # After updating enrichment, generate/update the composite embedding!
    try:
        from moviebot.core.embeddings import (
            build_composite_document,
            get_composite_document_hash,
            get_embedding_result,
            encode_vector
        )
        
        genres_val = item.get("genres")
        tones_val = enrichment.get("tone_tags")
        themes_val = enrichment.get("theme_tags")
        synopsis_val = item.get("synopsis") or ""
        
        comp_doc = build_composite_document(
            title=title,
            year=year,
            genres=genres_val,
            tones=tones_val,
            themes=themes_val,
            synopsis=synopsis_val
        )
        comp_hash = get_composite_document_hash(comp_doc)
        
        emb = await get_embedding_result(comp_doc)
        
        LibraryItemRepository.update_vector_and_hash(
            id=item["id"],
            synopsis_vector=encode_vector(emb.vector),
            synopsis_vector_model=emb.model,
            synopsis_vector_dim=emb.dim,
            synopsis_hash=comp_hash
        )
        logger.info(f"[Auto-Enrich] Generated and saved composite search embedding for {title} ({year})")
    except Exception as embed_err:
        logger.error(f"[Auto-Enrich] Failed to update composite embedding for {title}: {embed_err}")

    return enrichment



def _display_list(val):
    """Parse a JSON list string or list for display."""
    if not val:
        return ""
    try:
        if isinstance(val, str):
            parsed = json.loads(val)
            if isinstance(parsed, list):
                return ", ".join(str(x) for x in parsed[:8])
        elif isinstance(val, list):
            return ", ".join(str(x) for x in val[:8])
    except Exception:
        pass
    return str(val)


def _tag_line(tags):
    """Format a tag list as inline code blocks."""
    if not tags:
        return "_none_"
    items = tags if isinstance(tags, list) else []
    if not items:
        return "_none_"
    return " ".join(f"`{t}`" for t in items[:12])


def build_new_movie_embed(item: Dict[str, Any], enrichment: Dict[str, Any]):
    """
    Builds a Discord embed for a newly added and enriched movie.
    Returns the embed object.
    """
    import discord

    title = item.get("title", "Unknown")
    year = item.get("year", "")
    genres = item.get("genres", "")
    studios = item.get("studios", "")
    content_rating = item.get("content_rating", "")
    rating = item.get("rating")
    runtime = item.get("runtime")

    embed = discord.Embed(
        title=f"\U0001f3ac New Movie Added: {title} ({year})",
        color=discord.Color.teal()
    )

    # Core metadata
    meta_parts = []
    if content_rating:
        meta_parts.append(f"**Rated**: {content_rating}")
    if runtime:
        try:
            rt = int(runtime)
            hours = rt // 60
            mins = rt % 60
            meta_parts.append(f"**Runtime**: {hours}h {mins}m" if hours else f"**Runtime**: {mins}m")
        except (ValueError, TypeError):
            pass
    if rating:
        meta_parts.append(f"**Rating**: \u2b50 {rating}")
    genre_str = _display_list(genres)
    if genre_str:
        meta_parts.append(f"**Genres**: {genre_str}")
    studio_str = _display_list(studios)
    if studio_str:
        meta_parts.append(f"**Studios**: {studio_str}")
    if meta_parts:
        embed.description = "\n".join(meta_parts)

    # Enrichment tags
    embed.add_field(name="\U0001f3ad Themes", value=_tag_line(enrichment.get("theme_tags", [])), inline=True)
    embed.add_field(name="\U0001f3b5 Tone", value=_tag_line(enrichment.get("tone_tags", [])), inline=True)
    embed.add_field(name="\U0001f4dd Premise", value=_tag_line(enrichment.get("premise_tags", [])), inline=True)
    embed.add_field(name="\U0001f4cd Setting", value=_tag_line(enrichment.get("setting_locations", [])), inline=True)

    if enrichment.get("award_tags"):
        embed.add_field(name="\U0001f3c6 Awards", value=_tag_line(enrichment["award_tags"]), inline=True)
    if enrichment.get("source_material_tags"):
        embed.add_field(name="\U0001f4d6 Source", value=_tag_line(enrichment["source_material_tags"]), inline=True)
    if enrichment.get("popularity_tags"):
        embed.add_field(name="\U0001f4ca Popularity", value=_tag_line(enrichment["popularity_tags"]), inline=True)
    if enrichment.get("cultural_impact_tags"):
        embed.add_field(name="\U0001f30d Cultural Impact", value=_tag_line(enrichment["cultural_impact_tags"]), inline=True)
    if enrichment.get("content_warning_tags"):
        embed.add_field(name="\u26a0\ufe0f Content Warnings", value=_tag_line(enrichment["content_warning_tags"]), inline=True)

    # Provenance footer
    provider = enrichment.get("enrichment_json", {}).get("source", "rules")
    sources_json = enrichment.get("hard_fact_sources_json", {})
    fact_source = sources_json.get("source", "unknown") if isinstance(sources_json, dict) else "unknown"
    embed.set_footer(text=f"Enrichment: {provider} | Facts: {fact_source}")

    return embed
