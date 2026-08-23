# Block 5-6: Anime Composite Embeddings

> Status: Planned.
> Result: Not implemented.
> Notes: Adds semantic retrieval only after anime schema, facts, typed metadata, and routing exist.

## Goal

Build anime composite search documents and embeddings so semantic retrieval can find relevant shows and episodes without replacing exact structured routes.

## Scope

- Create compact anime search documents from show title, alternate titles, episode title, synopsis, genres, studios, cast, arcs, formats, franchise labels, source-material labels, and typed metadata.
- Store embedding vectors, model name, dimension, source hash, and updated timestamp in the anime database.
- Add dry-run-first embedding backfill with limit/offset support.
- Add in-memory vector cache behavior compatible with existing movie retrieval patterns.
- Ensure exact structured routing remains preferred for exact show/episode questions.

## Out Of Scope

- Do not add final conversational answer generation.
- Do not embed private file paths or raw provider payloads.
- Do not build embeddings for `tv` or `tv_classic` yet.
- Do not add download search.

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/repositories.py`
- `src/moviebot/core/embeddings.py`
- `src/moviebot/tools/`
- `tests/test_anime_embeddings.py`

## Acceptance Criteria

- Anime embeddings are generated from metadata-rich composite documents.
- Backfill supports dry-run, limit, offset, and resumable updates.
- Semantic retrieval tests find relevant anime records for descriptive queries.
- Exact structured query tests still prove routing precedence over semantic retrieval.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_embeddings.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_query_routing.py tests/test_anime_embeddings.py -q`
