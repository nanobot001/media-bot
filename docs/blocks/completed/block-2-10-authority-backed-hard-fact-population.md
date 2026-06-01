# Block 2-10: Authority-Backed Hard-Fact Population

> Status: Completed.
> Result: Implemented.
> Notes: This block fills the hard-fact columns created in Block 2-9 using explicit metadata sources instead of LLM guesses.

## Goal

Populate the Phase 2 hard-fact discovery fields for local library items so `/library` can answer queries like `award winning movies`, `oscar movies`, `based on a book`, `true story`, `blockbuster movies`, `cult classics`, and similar factual category searches from sourced data.

## Scope

- Audit the live `library_items` table to report current coverage for Plex factual fields and Block 2-9 hard-fact fields.
- Verify whether the interrupted `sync-intelligence --no-dry-run` pass completed enough Plex factual backfill. If incomplete, rerun or add a bounded dry-run-first path to populate Plex-backed fields before hard-fact enrichment.
- Add one dry-run-first enrichment/backfill path that can populate:
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
- Use authority-backed or explicit metadata only. Candidate sources may include TMDB, Wikidata, OMDb, IMDb IDs already stored in Plex, or Plex labels/collections when they explicitly encode the fact.
- Keep Gemini optional and secondary: Gemini may normalize explicit facts into canonical tags, but it must not invent awards, source material, box office, or cultural-footprint claims.
- Run or document the required enrichment backfill sequence after facts exist, so hard-fact data flows into the fields `/library` already queries.
- Preserve existing JSON tool envelopes, dry-run behavior, public-read redaction, and PM2 runtime model.
- Record a structured event after any non-dry-run population pass.

## Out Of Scope

- Do not add conversational RAG or LLM answer generation in this block.
- Do not redesign `/library` ranking beyond using the hard-fact fields already added in Block 2-9.
- Do not manually curate all movies inside code or tests.
- Do not store API keys, raw secrets, private paths, or unsanitized external payloads in public tool responses.
- Do not make unsupported claims from synopsis text alone.

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/repositories.py`
- `src/moviebot/tools/sync_enrichment_tool.py`
- `src/moviebot/tools/query_library_tool.py`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/cli/mcp_server.py`
- `src/moviebot/config.py`
- `docs/tool-manifest.yaml`
- `docs/tool-surface.md`
- `tests/test_intelligence.py`
- `tests/test_mcp_server.py`

## Suggested Design

- Add a coverage/audit mode before writing data, for example:
  - count rows with non-empty `studios`, `cast`, `countries`, and `labels`
  - count rows with non-empty hard-fact fields
  - show sample missing rows without exposing `file_path`
- Treat Plex factual coverage as the prerequisite check:
  - if Plex `studios`, `cast`, `countries`, `labels`, or `content_rating` are mostly empty, finish the Plex backfill first
  - if Plex coverage is healthy, proceed to external hard-fact population
- Add a fact-provider module that accepts a library row and returns a normalized fact payload with source attribution.
- Match external data by strongest available identifiers first:
  - IMDb ID
  - Plex GUID/provider IDs if available
  - title + year only as a fallback with confidence/source notes
- Store compact source attribution in `hard_fact_sources_json`, for example source name, external ID, fetched timestamp, and fields supported.
- Keep all write paths dry-run by default and resumable by `limit`.
- Keep the query parser focused on hard-fact phrases in this block:
  - `award winning`, `award-winning`, `oscar winner`, `oscar nominee`, `festival winner`, `critically acclaimed`
  - `based on a book`, `true story`, `comic book`, `video game`, `remake`, `sequel`, `reboot`
  - `blockbuster`, `cult classic`, `classic`, `hidden gem`, `mainstream`
- Defer softer audience/occasion and pacing inference unless the hard-fact importer requires small parser additions.

## Acceptance Criteria

- A dry-run command reports how many library rows already have Plex factual metadata and hard-fact metadata.
- The implementation verifies whether the interrupted Plex factual backfill left gaps and either completes the backfill or reports a concrete blocker.
- A dry-run hard-fact population pass returns preview rows with proposed tags and source attribution without mutating the DB.
- A non-dry-run hard-fact population pass writes sourced facts to the Block 2-9 columns and records a structured event.
- `/library` queries for `award winning movies`, `oscar movies`, `based on a book`, `true story`, and `blockbuster movies` return results when matching sourced facts exist.
- Public outputs redact private paths and do not expose API keys, raw tokens, or full external payload dumps.
- Tests cover successful population, dry-run no-op behavior, source attribution storage, and at least two query examples using populated hard facts.

## Verification

- `py -3.12 -m pytest tests/test_intelligence.py tests/test_mcp_server.py -q --basetemp C:\tmp\media-bot-pytest-hard-fact-population`
- Dry-run coverage command returns a JSON envelope with counts and no private paths.
- Dry-run population command previews sourced hard facts and does not mutate `library_items`.
- Non-dry-run population command on a small limit writes fields and records a `sync_enrichment` or dedicated hard-fact population event.

## Deferred Follow-Up

Create a separate query-understanding block for softer categories after hard facts are populated:

- audience and occasion: `family movies`, `kids movies`, `date night`, `comfort watch`, `group watch`, `holiday watch`
- people facets: `female-led`, `child-led`, `ensemble`, `musician-led`, `sports-team-led`
- pacing and intensity: `slow burn`, `fast-paced`, `low-stress`, `intense`, `scary`, `emotionally heavy`
