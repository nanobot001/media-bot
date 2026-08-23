# Block 6-4: Anime File Selection & Pack Handling

> Status: Planned.
> Result: Not implemented.
> Notes: Extends debrid manifest handling from single movie files to anime episodes, specials, whole seasons, and packs.

## Goal

Teach the download pipeline to inspect AllDebrid file manifests for anime requests and safely choose individual episode files, whole-season file sets, or season-pack files while prompting when file selection is ambiguous.

## Scope

- Extend file selection heuristics for anime episode numbers, absolute episode numbers, specials/OVAs, episode ranges, whole-season requests, and season/cour packs.
- Reuse existing sample/trailer/extra pruning while adding anime naming patterns.
- Return structured `requires_selection` states when multiple plausible files remain.
- Preserve dry-run behavior so manifest inspection and proposed selection can be tested without sending links to IDM.
- Keep movie main-file selection behavior unchanged.

## Out Of Scope

- Do not change final file movement or naming; `media-watcher` remains responsible after IDM starts.
- Do not add autonomous batch downloads.
- Do not implement TV pack handling yet.
- Do not expose raw direct download links in public outputs.

## Likely Files Or Areas

- `src/moviebot/adapters/alldebrid_client.py`
- `src/moviebot/tools/`
- `src/moviebot/db/repositories.py`
- `tests/test_anime_file_selection.py`

## Acceptance Criteria

- Anime file selection can identify a requested episode, special, absolute episode, whole season, or season-pack file set from mocked manifests.
- Ambiguous manifests return structured selection choices without enqueueing.
- Dry-run mode does not call IDM or mutate download state beyond allowed preview behavior.
- Existing movie enqueue/file-selection tests continue to pass.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_file_selection.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_enqueue_download.py tests/test_anime_file_selection.py -q --basetemp data\\pytesttmp-anime-files`
