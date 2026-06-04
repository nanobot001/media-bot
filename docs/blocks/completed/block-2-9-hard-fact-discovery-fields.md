# Block 2-9: Hard-Fact Discovery Fields

## Status

Completed

> Status: Implemented on 2026-05-31.
> Result: Implemented.
> Verification: `py -3.12 -m pytest tests/test_intelligence.py::test_self_healing_migration tests/test_intelligence.py::test_sync_enrichment_tool_gemini_provider_normalizes_output tests/test_intelligence.py::test_query_library_routes_hard_fact_phrases_to_structured_filters tests/test_mcp_server.py::test_mcp_query_library_invocation -q --basetemp C:\tmp\media-bot-pytest-hard-facts` - passed.
> Notes: Adds schema and query support for sourced awards, source material, popularity, and cultural impact facts; rows remain empty until populated by Gemini from explicit metadata or a later authority-backed importer.

## Objective

Add durable database fields and query routing for hard-fact movie discovery categories that should not be guessed from synopsis text alone.

## Fields

- `award_tags`
- `award_wins_json`
- `award_nominations_json`
- `acclaim_tags`
- `source_material_tags`
- `adaptation_type_tags`
- `popularity_tags`
- `cultural_impact_tags`
- `box_office_tier`
- `hard_fact_sources_json`

## Scope

- Add self-healing SQLite columns to `library_items`.
- Preserve empty defaults in rule-based enrichment.
- Allow Gemini enrichment to normalize these fields only from explicit provided metadata.
- Add `/library`, CLI, and MCP query filters for award, source material, popularity, and cultural impact tags.
- Route common phrases like `award winning`, `oscar movies`, `based on a book`, and `blockbuster movies` to structured filters before semantic ranking.

## Non-Goals

- Do not add IMDb, TMDB, Wikidata, OMDb, or other third-party fact importers in this block.
- Do not ask Gemini to invent award, source-material, or popularity facts without evidence.
- Do not run a live enrichment backfill as part of this block.

## Follow-Up

Populate the hard-fact fields from authority-backed metadata sources, then optionally let Gemini normalize labels and resolve conflicts with source citations.
