# Block 5-4: Anime Regression Harness

> Status: Planned.
> Result: Not implemented.
> Notes: Locks deterministic anime matching behavior before typed metadata, embeddings, and RAG.

## Goal

Create a focused anime regression harness that proves show/episode identity, alias handling, specials, watched-state queries, and citation formatting behave deterministically before conversational layers rely on them.

## Scope

- Add fixture builders for anime shows, seasons/arcs, episodes, specials/OVAs, aliases, and watched state.
- Add regression cases for episode title lookup, show title aliases, season/episode lookup, absolute episode lookup, specials, unwatched episodes, and studio/genre filters.
- Add negative cases for ambiguous aliases, missing absolute numbers, and unknown shows.
- Include citation expectations in regression assertions.
- Keep fixtures small and independent of live Plex data.

## Out Of Scope

- Do not call live Plex, Gemini, TMDb, AniList, TVDB, or Wikidata.
- Do not add new user-facing tools unless required for testability.
- Do not implement RAG or embeddings.
- Do not test download search.

## Likely Files Or Areas

- `tests/fixtures/`
- `tests/test_anime_regressions.py`
- `src/moviebot/tools/`
- `src/moviebot/db/repositories.py`

## Acceptance Criteria

- Regression fixtures can initialize an isolated anime database.
- Tests prove exact structured routes beat fuzzy/semantic behavior for known episode questions.
- Ambiguous or missing anime identities return structured errors or empty results rather than guessed matches.
- Citation fields are asserted in successful results.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_regressions.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_query_surface.py tests/test_anime_regressions.py -q`
