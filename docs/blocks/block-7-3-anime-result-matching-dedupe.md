# Block 6-3: Anime Result Matching & Deduplication

> Status: Planned.
> Result: Not implemented.
> Notes: Prevents confident wrong anime downloads before any enqueue flow is exposed.

## Goal

Match anime source results against structured anime request intents and local owned state so the bot can rank likely candidates, reject unsafe matches, and avoid downloading already-owned episodes or packs.

## Scope

- Add anime result matching for show aliases, season/episode numbers, absolute episode numbers, specials/OVAs, episode ranges, whole-season requests, season packs, and release titles.
- Add conservative rejection rules for wrong shows, wrong seasons, suspicious batch ranges, samples, trailers, unrelated extras, and already-owned episodes.
- Track match reasons, confidence, and safety flags in structured result output.
- Support configured preferences such as quality, release group, sub/dub preference, and batch allowance when settings exist.
- Preserve obfuscated result references and public-read privacy boundaries.

## Out Of Scope

- Do not unlock magnets or inspect AllDebrid file manifests.
- Do not enqueue downloads.
- Do not implement autonomous monitoring.
- Do not add TV result matching yet.

## Likely Files Or Areas

- `src/moviebot/core/`
- `src/moviebot/tools/`
- `src/moviebot/db/repositories.py`
- `tests/test_anime_result_matching.py`

## Acceptance Criteria

- Candidate results include structured match reasons, confidence, and rejection reasons.
- Already-owned anime episodes are rejected or clearly marked as duplicates.
- Ambiguous results require confirmation rather than auto-selection.
- Tests cover aliases, absolute episodes, whole seasons, season packs, specials, wrong-show false positives, and duplicate protection.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_result_matching.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_request_parser.py tests/test_anime_result_matching.py -q`
