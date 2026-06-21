# Block 6-6: Anime Download Regression Harness

> Status: Planned.
> Result: Not implemented.
> Notes: Locks anime download safety before the end-to-end Phase 6 MVP is declared complete.

## Goal

Create a deterministic regression harness for anime search, matching, deduplication, file selection, confirmation, dry-run, and structured-error behavior so risky anime release naming cases stay protected.

## Scope

- Add mocked Prowlarr and AllDebrid fixtures for single episodes, absolute episodes, specials, whole seasons, season packs, multi-season packs, wrong-show releases, samples, extras, and ambiguous manifests.
- Add regression cases for sub/dub labels, release groups, quality filters, already-owned episodes, missing absolute numbers, and duplicate pack ranges.
- Assert dry-run no-write behavior for search, match, manifest inspection, and confirmation preview paths.
- Assert public outputs never include raw magnets, direct links, private paths, API keys, or raw sensitive payloads.
- Include structured error code expectations for ambiguity, no safe candidates, duplicate owned item, and upstream failure.

## Out Of Scope

- Do not call live Prowlarr, AllDebrid, IDM, Plex, or external providers.
- Do not implement new production behavior beyond test helpers if earlier blocks did not expose it.
- Do not add autonomous monitor regressions.
- Do not cover TV or TV Classic downloads yet.

## Likely Files Or Areas

- `tests/fixtures/`
- `tests/test_anime_download_regressions.py`
- `tests/test_anime_result_matching.py`
- `tests/test_anime_file_selection.py`

## Acceptance Criteria

- Regression tests cover the major anime false-positive and ambiguity risks.
- Dry-run assertions prove no AllDebrid/IDM write calls occur.
- Privacy assertions prove public payloads remain redacted.
- The harness can run without live credentials or network access.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_download_regressions.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_result_matching.py tests/test_anime_file_selection.py tests/test_anime_download_regressions.py -q`
