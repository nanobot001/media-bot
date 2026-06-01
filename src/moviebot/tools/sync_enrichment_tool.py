import datetime
import json
import logging
from typing import Any, Dict

from moviebot.core.enrichment import serialize_enrichment
from moviebot.db.connection import get_db_connection, init_db
from moviebot.db.repositories import EventRepository, LibraryItemRepository
from moviebot.tools.fact_provider import WikidataFactProvider
from moviebot.tools.fact_normalizer import FactNormalizer

logger = logging.getLogger(__name__)

async def sync_enrichment_tool(
    dry_run: bool = True,
    limit: int = 50,
    provider: str = "rules",
    offset: int = 0,
    only_missing_hard_facts: bool = False,
) -> Dict[str, Any]:
    tool_name = "sync_enrichment"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        if not dry_run:
            init_db()
            
        with get_db_connection() as conn:
            # 1. Plex Factual Coverage Audit
            total_cursor = conn.execute("SELECT COUNT(*) FROM library_items WHERE source = 'plex'")
            total_items = total_cursor.fetchone()[0]
            
            audit_stats = {}
            if total_items > 0:
                audit_fields = [
                    "studios", "cast", "countries", "labels", "content_rating",
                    "award_tags", "source_material_tags", "popularity_tags",
                    "cultural_impact_tags", "box_office_tier"
                ]
                for field in audit_fields:
                    c = conn.execute(
                        f'SELECT COUNT(*) FROM library_items WHERE source = \'plex\' AND "{field}" IS NOT NULL AND "{field}" != \'\' AND "{field}" != \'[]\' AND "{field}" != \'{{}}\''
                    )
                    audit_stats[field] = c.fetchone()[0]
                
                # Check Plex coverage health (excluding labels, which is typically empty)
                core_fields = ["studios", "cast", "countries", "content_rating"]
                core_coverage = {f: audit_stats.get(f, 0) / total_items for f in core_fields}
                avg_coverage = sum(core_coverage.values()) / len(core_fields)
                
                if avg_coverage < 0.5:
                    return {
                        "ok": False,
                        "tool": tool_name,
                        "timestamp": timestamp,
                        "error": {
                            "code": "PLEX_BACKFILL_INCOMPLETE",
                            "message": f"Plex factual coverage is too low (average core coverage {avg_coverage:.1%}). Please run Plex factual backfill first.",
                            "retryable": True,
                            "severity": "error"
                        }
                    }
            else:
                core_coverage = {}
                avg_coverage = 0.0

            # 2. Get items to enrich
            missing_hard_fact_sql = """
                AND (
                    award_tags IS NULL OR award_tags = '' OR award_tags = '[]'
                    OR source_material_tags IS NULL OR source_material_tags = '' OR source_material_tags = '[]'
                    OR popularity_tags IS NULL OR popularity_tags = '' OR popularity_tags = '[]'
                    OR cultural_impact_tags IS NULL OR cultural_impact_tags = '' OR cultural_impact_tags = '[]'
                    OR box_office_tier IS NULL OR box_office_tier = ''
                )
            """
            cursor = conn.execute(
                f"""
                SELECT * FROM library_items
                WHERE source = 'plex'
                {missing_hard_fact_sql if only_missing_hard_facts else ""}
                ORDER BY title ASC
                LIMIT ? OFFSET ?
                """,
                (limit, offset)
            )
            items = [dict(row) for row in cursor.fetchall()]

        normalized_provider = (provider or "rules").lower()
        if normalized_provider not in {"rules", "gemini"}:
            raise ValueError("provider must be 'rules' or 'gemini'")

        # Initialize Wikidata fact provider
        fact_provider = WikidataFactProvider()
        
        previews = []
        provider_errors = []
        for item in items:
            # Redact path from logs
            log_title = item.get("title")
            logger.info(f"Syncing enrichment for {log_title} ({item.get('year')})")
            
            try:
                # Fetch raw Wikidata facts
                facts = fact_provider.get_facts(
                    title=item.get("title", ""),
                    year=item.get("year"),
                    imdb_id=item.get("imdb_id")
                ) or {}
                if not facts and getattr(fact_provider, "_rate_limited", False) is True:
                    provider_errors.append({
                        "id": item.get("id"),
                        "title": log_title,
                        "provider": normalized_provider,
                        "message": "Skipped because Wikidata rate-limited the fact provider.",
                    })
                    continue
                
                if normalized_provider == "gemini":
                    enrichment = await FactNormalizer.normalize_with_gemini(facts, item)
                else:
                    enrichment = FactNormalizer.normalize_with_rules(facts, item)
            except Exception as enrich_err:
                logger.error(f"Failed to enrich item {log_title}: {enrich_err}")
                # Fallback to rules-based standard enrichment with no facts
                enrichment = FactNormalizer.normalize_with_rules({}, item)
                enrichment["enrichment_json"]["source"] = "rules_fallback"
                provider_errors.append({
                    "id": item.get("id"),
                    "title": log_title,
                    "provider": normalized_provider,
                    "message": str(enrich_err),
                })
                
            serialized = serialize_enrichment(enrichment)

            previews.append({
                "id": item.get("id"),
                "title": log_title,
                "year": item.get("year"),
                "setting_locations": enrichment.get("setting_locations", []),
                "story_locations": enrichment.get("story_locations", []),
                "event_locations": enrichment.get("event_locations", []),
                "premise_tags": enrichment.get("premise_tags", []),
                "central_premise_tags": enrichment.get("central_premise_tags", []),
                "character_tags": enrichment.get("character_tags", []),
                "theme_tags": enrichment.get("theme_tags", []),
                "central_theme_tags": enrichment.get("central_theme_tags", []),
                "tone_tags": enrichment.get("tone_tags", []),
                "dominant_tone_tags": enrichment.get("dominant_tone_tags", []),
                "craft_tags": enrichment.get("craft_tags", []),
                "content_warning_tags": enrichment.get("content_warning_tags", []),
                "depicted_content_warning_tags": enrichment.get("depicted_content_warning_tags", []),
                "discussed_content_warning_tags": enrichment.get("discussed_content_warning_tags", []),
                # Hard facts fields
                "award_tags": enrichment.get("award_tags", []),
                "award_wins_json": enrichment.get("award_wins_json", {}),
                "award_nominations_json": enrichment.get("award_nominations_json", {}),
                "acclaim_tags": enrichment.get("acclaim_tags", []),
                "source_material_tags": enrichment.get("source_material_tags", []),
                "adaptation_type_tags": enrichment.get("adaptation_type_tags", []),
                "popularity_tags": enrichment.get("popularity_tags", []),
                "cultural_impact_tags": enrichment.get("cultural_impact_tags", []),
                "box_office_tier": enrichment.get("box_office_tier"),
                "hard_fact_sources_json": enrichment.get("hard_fact_sources_json", {}),
                "enrichment_version": enrichment.get("enrichment_version"),
                "enrichment_model": enrichment.get("enrichment_model"),
                "provider_requested": normalized_provider,
                "provider_used": enrichment.get("enrichment_json", {}).get("source", "rules"),
            })

            if not dry_run:
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
                    story_locations=serialized["story_locations"],
                    filming_locations=serialized["filming_locations"],
                    production_countries=serialized["production_countries"],
                    mentioned_locations=serialized["mentioned_locations"],
                    event_locations=serialized["event_locations"],
                    central_premise_tags=serialized["central_premise_tags"],
                    subplot_tags=serialized["subplot_tags"],
                    protagonist_tags=serialized["protagonist_tags"],
                    antagonist_tags=serialized["antagonist_tags"],
                    supporting_character_tags=serialized["supporting_character_tags"],
                    central_theme_tags=serialized["central_theme_tags"],
                    minor_theme_tags=serialized["minor_theme_tags"],
                    dominant_tone_tags=serialized["dominant_tone_tags"],
                    secondary_tone_tags=serialized["secondary_tone_tags"],
                    ending_tone_tags=serialized["ending_tone_tags"],
                    format_tags=serialized["format_tags"],
                    visual_style_tags=serialized["visual_style_tags"],
                    narrative_structure_tags=serialized["narrative_structure_tags"],
                    music_role_tags=serialized["music_role_tags"],
                    depicted_content_warning_tags=serialized["depicted_content_warning_tags"],
                    discussed_content_warning_tags=serialized["discussed_content_warning_tags"],
                    award_tags=serialized["award_tags"],
                    award_wins_json=serialized["award_wins_json"],
                    award_nominations_json=serialized["award_nominations_json"],
                    acclaim_tags=serialized["acclaim_tags"],
                    source_material_tags=serialized["source_material_tags"],
                    adaptation_type_tags=serialized["adaptation_type_tags"],
                    popularity_tags=serialized["popularity_tags"],
                    cultural_impact_tags=serialized["cultural_impact_tags"],
                    box_office_tier=serialized["box_office_tier"],
                    hard_fact_sources_json=serialized["hard_fact_sources_json"],
                )

        if not dry_run and len(previews) > 0:
            EventRepository.insert(
                event_type="sync_enrichment",
                source="moviebot",
                title="Structured enrichment sync",
                summary=f"Structured enrichment updated for {len(previews)} library items.",
                entity_type="library_items",
                status="completed",
                severity="info",
                data_json=json.dumps({
                    "count": len(previews),
                    "selected_count": len(items),
                    "limit": limit,
                    "offset": offset,
                    "provider": normalized_provider,
                    "only_missing_hard_facts": only_missing_hard_facts,
                })
            )

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "dry_run": dry_run,
                "provider": normalized_provider,
                "processed": len(previews),
                "selected": len(items),
                "limit": limit,
                "offset": offset,
                "only_missing_hard_facts": only_missing_hard_facts,
                "audit": {
                    "total_items": total_items,
                    "avg_core_coverage": avg_coverage,
                    "fields": audit_stats
                },
                "provider_errors": provider_errors,
                "items": previews,
            }
        }
    except Exception as e:
        logger.exception("Error during sync_enrichment")
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "SYNC_ENRICHMENT_FAILED",
                "message": f"Error syncing structured enrichment: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
