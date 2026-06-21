# Block 6-2: Anime Episode Request Parser

> Status: Planned.
> Result: Not implemented.
> Notes: Turns user anime download text into structured episode, special, absolute episode, whole-season, or season-pack intents.

## Goal

Parse anime download requests into deterministic structured intents using the anime database for show identity, alternate titles, episode numbering, specials, whole-season targets, and season-pack targets before source matching begins.

## Scope

- Add an anime request parser for show title, alternate title, season number, episode number, absolute episode number, episode title, special/OVA, whole-season requests, and season/cour pack requests.
- Resolve parsed show identities against the anime database from Phase 5.
- Return structured ambiguity when multiple shows or episodes match instead of guessing.
- Preserve normalized query text suitable for anime source search.
- Add parser fixtures for common request formats such as `S01E03`, `episode 12`, `absolute 47`, `special 2`, `OVA`, and `season 1`.

## Out Of Scope

- Do not call Prowlarr, AllDebrid, or IDM.
- Do not select torrent results or files.
- Do not implement TV parsing yet.
- Do not infer unavailable absolute episode numbers when the anime database lacks them.

## Likely Files Or Areas

- `src/moviebot/core/`
- `src/moviebot/db/repositories.py`
- `src/moviebot/tools/`
- `tests/test_anime_request_parser.py`

## Acceptance Criteria

- Parser output is a structured intent with domain, show identity, target type, numbering fields, and confidence.
- Ambiguous or missing identities return structured errors or clarification candidates.
- Parser tests cover episodes, specials, absolute episodes, episode titles, whole-season requests, and season-pack requests.
- Existing Phase 5 anime query/regression tests continue to pass.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_request_parser.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_query_surface.py tests/test_anime_request_parser.py -q`
