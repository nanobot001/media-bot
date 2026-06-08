# Block 5-1: Anime Schema & Plex Mirror

> Status: Planned.
> Result: Not implemented.
> Notes: First Anime Phase 5 implementation block and the proving ground for reusable series/episode state.

## Goal

Create the anime database schema and Plex mirror path for anime shows, seasons/arcs, episodes, and specials. This block should establish durable anime identity before any LLM enrichment or anime RAG work.

## Scope

- Add anime-domain tables for shows, seasons or arcs, episodes, specials/OVAs, files, and sync metadata.
- Store Plex rating keys, titles, normalized titles, alternate titles when available, season number, episode number, absolute episode number when known, air date, runtime, watched state, watch count, file metadata, and synopsis.
- Sync configured anime Plex sections into the anime DB through the domain router.
- Preserve movie `library_items` behavior and existing movie sync behavior.
- Add dry-run preview support for anime sync if the existing sync path supports dry-run patterns.
- Record structured events for non-dry-run anime sync writes.

## Out Of Scope

- Do not add AniList, TMDb TV, TVDB, Wikidata, or Gemini enrichment in this block.
- Do not add anime RAG, anime recommendations, or anime download search.
- Do not solve all anime alternate-title and watch-order issues beyond storing available Plex fields.
- Do not change movie schema or movie query behavior.

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/repositories.py`
- `src/moviebot/adapters/plex_client.py`
- `src/moviebot/tools/`
- `tests/test_anime_schema_sync.py`

## Acceptance Criteria

- The anime DB can be initialized independently from the movie DB.
- Anime Plex sections sync show/season/episode/special records into anime-specific tables.
- Episode identity supports season/episode and a nullable absolute episode number.
- Sync output uses structured JSON and does not expose private file paths in public-read contexts.
- Existing movie tests continue to pass.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_schema_sync.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_intelligence.py tests/test_discord_app.py -q --basetemp data\\pytesttmp-anime-schema`
