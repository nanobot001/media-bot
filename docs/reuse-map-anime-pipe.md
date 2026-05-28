# Translation Map: `anime-pipe` to `movie-media-bot`

This document details how structural logic from the `anime-pipe` automation script maps into the modular components of `movie-media-bot`.

---

## 1. AllDebrid Integration (`adapters/alldebrid_client.py`)

*   **Cache Check:**
    *   *anime-pipe logic:* Query `/v4/magnet/instant` with torrent infohashes.
    *   *Implementation:* Wrapped inside `alldebrid_client.py` as `instant_check(infohashes: list[str])`. Prioritizes instantly cached releases to show green tags in Discord embeds.
*   **Magnet Upload:**
    *   *anime-pipe logic:* Upload magnet link to `/v4/magnet/upload`.
    *   *Implementation:* Returns a magnet ID to poll until files are fully resolved or cached.

---

## 2. File Selection Heuristics (`core/file_selection.py`)

To automatically isolate the primary movie file from samples, featurettes, or extra content in a torrent payload, we translate the following decision tree:

### Regex Exclusions
Filter out any files matching the following pattern:
```regex
(?i)(sample|trailer|extra|bonus|featurette)
```

### Format Filtering
Only include files matching common video container extensions:
*   `.mkv`
*   `.mp4`
*   `.avi`

### Selection Algorithm
1.  Apply exclusions and format filters.
2.  If the resulting list is empty, return an error.
3.  If there is exactly one file, return it.
4.  If there are multiple files:
    *   Sort files by size (descending).
    *   Calculate the size difference between the largest file and the second largest.
    *   If the difference is **within a 10% threshold**:
        *   Stop automated resolution.
        *   Yield a list of candidate files back to the caller to generate a select dropdown menu in the Discord interface.
    *   If the largest file is larger by **more than 10%**, automatically select it as the main film.

---

## 3. IDM Execution Subprocesses (`adapters/idm_adapter.py`)
*   *anime-pipe logic:* Executes direct command lines via `subprocess.Popen` in Windows.
*   *Implementation:* Refactored into a standardized `IdmAdapter` client which delegates either to local subprocess execution (monolithic host run) or forwards JSON payloads to the `idm_bridge_api` service.
