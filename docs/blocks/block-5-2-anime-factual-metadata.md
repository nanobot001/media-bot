# Block 5-2: Anime Factual Metadata

> Status: Planned.
> Result: Not implemented.
> Notes: Mirrors source-backed anime facts before typed enrichment, embeddings, or RAG.

## Goal

Populate durable factual anime metadata from Plex and explicit source-backed providers so later LLM enrichment and RAG operate on evidence instead of guesses. This block applies the movie lesson: factual fields first, inferred fields later.

## Scope

- Extend anime show and episode records with factual fields available from Plex, such as genres, studios, cast/roles, content rating, audience rating, labels, originally available date, episode summaries, and collections.
- Define source-backed anime fact fields for later providers, such as source material, production studio, franchise, related works, external IDs, and canonical/alternate titles.
- Add source attribution storage for factual fields.
- Add dry-run-first factual metadata backfill for existing anime rows.
- Add query-ready helper fields only for facts populated from explicit metadata.

## Out Of Scope

- Do not add Gemini typed enrichment or subjective theme/tone classification.
- Do not add composite embeddings or RAG.
- Do not add download search.
- Do not require a single external provider if Plex facts are enough for the first implementation slice; provider additions should remain source-backed and testable.

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/repositories.py`
- `src/moviebot/adapters/plex_client.py`
- `src/moviebot/tools/`
- `tests/test_anime_factual_metadata.py`

## Acceptance Criteria

- Anime factual metadata fields exist and are self-healing for existing anime DBs.
- Plex-backed anime facts are parsed and persisted during sync or factual backfill.
- Dry-run factual backfill previews proposed changes without mutating the DB.
- Source attribution distinguishes Plex-provided facts from future external-provider facts.
- Public-read outputs redact private file paths, raw vectors, API keys, and raw provider payloads.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_factual_metadata.py -q`
- Dry-run factual backfill returns a JSON envelope with preview counts and no database mutation.
