# Block 5-3: Anime Query Surface & Structured Search

> Status: Planned.
> Result: Not implemented.
> Notes: Makes the synced anime database queryable before semantic search or RAG.

## Goal

Expose deterministic anime library queries over the anime database so users and tools can find shows, seasons/arcs, episodes, specials, and watched state with structured JSON results and citations to local records.

## Scope

- Add an anime query tool or domain-aware query path that reads from the `anime` database.
- Support structured filters for show title, alternate title, episode title, season number, episode number, nullable absolute episode number, special/OVA status, watched state, genre, studio, cast/role, and air date when those fields exist.
- Return stable local citations such as show rating key, episode rating key, season/episode numbers, and source domain.
- Preserve public-read redaction of private file paths and raw provider payloads.
- Keep movie `query_library` behavior backward compatible.

## Out Of Scope

- Do not add semantic embeddings or LLM/RAG answering.
- Do not add anime download search.
- Do not add external anime providers beyond fields already stored by earlier blocks.
- Do not route `tv` or `tv_classic` queries yet.

## Likely Files Or Areas

- `src/moviebot/db/repositories.py`
- `src/moviebot/tools/`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/cli/mcp_server.py`
- `tests/test_anime_query_surface.py`

## Acceptance Criteria

- Anime query results use structured JSON envelopes and include local citations.
- Exact show, episode, season/episode, absolute episode, and special lookups are covered by tests.
- Public-read results omit or redact private file paths.
- Existing movie query tests continue to pass.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_query_surface.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_intelligence.py tests/test_mcp_server.py -q --basetemp data\\pytesttmp-anime-query`
