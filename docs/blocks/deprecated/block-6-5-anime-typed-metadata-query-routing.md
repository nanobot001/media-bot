# Block 5-5: Anime Typed Metadata & Query Routing

> Status: Planned.
> Result: Not implemented.
> Notes: Adds query-ready anime metadata and routes exact questions before semantic search.

## Goal

Add typed anime metadata fields and deterministic query routing so factual show/episode questions use structured database lookups before any semantic or LLM layer is consulted.

## Scope

- Add typed anime fields for arcs, formats, demographics when source-backed, related-work labels, franchise labels, source-material labels, content warnings, and episode-level tags where evidence exists.
- Store confidence and evidence/source metadata for inferred or provider-derived fields.
- Add routing helpers that detect exact show, episode, season, absolute episode, special, studio, cast, and watched-state questions.
- Ensure structured routes return citations and decline unsupported hard claims instead of guessing.
- Preserve dry-run behavior for any typed metadata backfill.

## Out Of Scope

- Do not generate composite embeddings.
- Do not add full conversational RAG.
- Do not require an external provider if Plex/source-backed facts are enough for this slice.
- Do not add anime download behavior.

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/repositories.py`
- `src/moviebot/core/`
- `src/moviebot/tools/`
- `tests/test_anime_typed_metadata.py`
- `tests/test_anime_query_routing.py`

## Acceptance Criteria

- Typed anime fields are self-healing for existing anime DBs.
- Query routing sends exact factual questions to SQL-backed routes before semantic search.
- Unsupported or low-evidence hard-fact questions return structured, non-secret errors or caveats.
- Regression tests cover routing precedence and citation output.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_typed_metadata.py tests/test_anime_query_routing.py -q`
- Typed metadata dry-run backfill returns a JSON envelope and does not mutate the database.
