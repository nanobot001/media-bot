# Block 08: Pipeline Status Card & Media Watcher State Bridge

**Status: PROPOSED**

## Goal

Give users real-time visibility into where a movie download is across the full ingestion pipeline — from debrid cache unlock through IDM download, folder handoff, FileBot rename, and Plex import — directly in Discord, without needing to cross-reference logs or guess where a breakdown occurred.

The core interaction is a **live status card** that is posted automatically when a download is enqueued, and is edited in place as each pipeline stage completes. A `/status` command provides on-demand access to recent jobs by movie title — no UUIDs ever exposed to the user.

---

## Background

The current handoff chain is:

```
Discord /download
  → AllDebrid (debrid unlock)
    → IDM (file download to output_dir)
      → media-watcher (detects file, runs FileBot rename)
        → Plex library folder
          → Plex (library refresh + Tautulli webhook)
```

media-bot has visibility into stages 1–2 (AllDebrid status, download job DB). After that, the file is handed off to `media-watcher`, a separate PowerShell polling process that has no queryable interface. If a breakdown occurs at the FileBot or Plex stage, there is currently no way to detect it without inspecting logs manually.

---

## Scope

### 1. media-watcher State Bridge (`media-watcher` repo)

Add a single write operation at the end of each scan cycle in `media_watcher.ps1`:

*   Write a `state.json` file to a configured shared path (e.g. `config/watcher-state.json`) after every scan.
*   Contents:
    ```json
    {
      "last_scan": "2026-05-30T01:40:00Z",
      "tracked_files": [
        {
          "filename": "Predator.Badlands.2025.1080p.mkv",
          "size_bytes": 13421772800,
          "stable": false,
          "first_seen_at": "2026-05-30T01:35:00Z",
          "stable_at": null
        }
      ],
      "last_batch": {
        "processed_at": "2026-05-30T01:32:00Z",
        "results": [
          {
            "source_file": "Inception.2010.mkv",
            "dest_path": "Inception (2010)/Inception (2010).mkv",
            "success": true,
            "error": null
          }
        ]
      }
    }
    ```
*   This is a non-breaking, additive change. The path is configurable via `config/media-watcher.json`.
*   No HTTP server, no threading changes, no new dependencies.

### 2. Download Job Schema Extension (`media-bot`)

Add a `discord_message_id` column to the `download_jobs` table:

*   Stores the Discord message ID of the live status card posted when the job was created.
*   Allows the background resolver loop to edit the message in place as status changes.
*   Migration is additive (nullable column, no existing rows broken).

### 3. `MediaWatcherClient` Adapter (`media-bot`)

New file: `src/moviebot/adapters/media_watcher_client.py`

*   Reads and parses `watcher-state.json` from the configured shared path.
*   Exposes:
    *   `get_tracked_files()` → list of files currently being monitored (not yet stable)
    *   `get_last_batch()` → result of the most recent processing run
    *   `is_file_tracked(filename)` → bool
    *   `get_file_status(filename)` → stable/tracking/processed/unknown

### 4. `PipelineStatusService` Core Logic (`media-bot`)

New file: `src/moviebot/core/pipeline_status.py`

Given a `download_job` record, assembles a full pipeline status snapshot by querying:

1. **job DB** → job status, filename, created\_at
2. **AllDebrid** → magnet status (processing / ready / error)
3. **MediaWatcherClient** → is the file being tracked? stable? processed?
4. **`library_items` DB** → has Plex imported and indexed it?

Returns a structured `PipelineStatus` dataclass:

```python
@dataclass
class PipelineStatus:
    title: str
    stage: str          # "debrid" | "downloading" | "in_folder" | "filebot" | "in_plex" | "error"
    debrid_ok: bool
    idm_status: str     # "pending" | "downloading" | "completed" | "failed"
    watcher_tracking: bool
    watcher_stable: bool
    filebot_ok: Optional[bool]
    in_plex: bool
    error_detail: Optional[str]
```

### 5. Live Status Card (`discord_app.py`)

**Auto-posted card**: When `/download` succeeds and a job is created, the bot immediately posts a status embed and stores the Discord message ID in `discord_message_id` on the job row.

**Card appearance (example):**

```
🎬  Predator Badlands (2025)
━━━━━━━━━━━━━━━━━━━━━━━━
✅  Debrid       Unlocked & cached
✅  Downloading  File received by IDM
⏳  Folder       Waiting to stabilise…
⬜  FileBot      —
⬜  Plex         —
━━━━━━━━━━━━━━━━━━━━━━━━
Last checked: just now  [🔄 Refresh]
```

**Background update loop**: The existing `job_resolver` background task (already in `discord_app.py`) is extended to also edit live status card messages for any active job that has a `discord_message_id`. Runs on the same poll interval.

**`/status` command**: `/status [title]`
*   With no argument → shows a list of the 5 most recent jobs as a dropdown by title.
*   With a title argument → searches `download_jobs.selected_file_name` by partial match, shows the matching job's pipeline card.
*   Never exposes raw UUIDs to the user.

**`[🔄 Refresh]` button**: Triggers a manual pipeline status refresh for that job on demand (deferred response, no timeout risk).

---

## Data Flow

```
/download called
  → job created in DB (status: pending)
  → status card posted to Discord
  → discord_message_id saved to job row

Background resolver loop (every N seconds):
  → for each active job:
      → query AllDebrid
      → read watcher-state.json
      → check library_items
      → build PipelineStatus
      → edit Discord message in place

Tautulli webhook (library-add event):
  → marks job as in_plex
  → final card edit → all stages green
```

---

## Acceptance Criteria

*   `media-watcher` writes `watcher-state.json` after every scan cycle with no regressions to existing behaviour.
*   `MediaWatcherClient` correctly reads and parses the state file, returning structured data.
*   `PipelineStatusService.get_status(job)` correctly maps all five pipeline stages from available data sources.
*   Status card is auto-posted when a download is enqueued and auto-updated as stages complete.
*   `/status` accepts a partial movie title and returns the correct card — no UUID required.
*   `[🔄 Refresh]` button triggers an immediate pipeline re-query and edits the embed.
*   Unit tests cover: `PipelineStatusService` stage mapping, `MediaWatcherClient` parsing, card rendering logic.
*   No regressions in existing tests (51 currently passing).
