# Block 2-6: Typed Enrichment Metadata v2

## Status

Completed

## Objective

Replace the single flat enrichment buckets with a durable typed metadata contract that distinguishes factual roles such as story setting vs filming location, central theme vs minor theme, and depicted vs discussed content warnings.

## Scope

- Keep the existing flat helper fields for compatibility.
- Add typed helper columns for high-value query facets.
- Extend `enrichment_json` with a v2 typed contract.
- Route factual setting queries through `story_locations`.
- Keep the current rule-based extractor as a bootstrap/fallback.
- Preserve dry-run behavior and structured JSON tool outputs.

## Typed Metadata Fields

- Geography: `story_locations`, `filming_locations`, `production_countries`, `mentioned_locations`, `event_locations`
- Premise: `central_premise_tags`, `subplot_tags`
- Characters: `protagonist_tags`, `antagonist_tags`, `supporting_character_tags`
- Themes: `central_theme_tags`, `minor_theme_tags`
- Tone: `dominant_tone_tags`, `secondary_tone_tags`, `ending_tone_tags`
- Craft: `format_tags`, `visual_style_tags`, `narrative_structure_tags`, `music_role_tags`
- Content warnings: `depicted_content_warning_tags`, `discussed_content_warning_tags`, with severity retained in `content_warnings_json`

## Implementation Notes

- Implemented on 2026-05-31.
- The first pass remains rule-based and conservative.
- The v2 contract is designed so a later Gemini metadata enrichment pass can populate the same fields with better evidence and confidence.
- Existing flat helper columns remain populated for compatibility.

## Verification

- `py -3.12 -m pytest tests/test_intelligence.py::test_self_healing_migration tests/test_intelligence.py::test_sync_enrichment_tool_dry_run_and_real_mode tests/test_intelligence.py::test_query_library_routes_setting_phrase_to_structured_filter tests/test_intelligence.py::test_query_library_routes_new_york_phrase_to_city_location tests/test_intelligence.py::test_query_library_excludes_content_warnings_conservatively -q --basetemp C:\tmp\media-bot-pytest-v2`
- Result: 5 passed.
