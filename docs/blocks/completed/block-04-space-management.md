# Block 04: Space Management Guard & Disk Monitor

**Status: DEPRECATED**

## Deprecation Notice
This block has been deprecated in favor of **[Block 04-1: Active Jobs, Pending Job Resolution, and Diagnostics](block-04-1-jobs-and-diagnostics.md)**. 

The storage drive `F:\_temp\movies` is already automatically pruned and managed by the external `media-watcher` pipeline which moves files to their permanent Plex libraries immediately after download. Therefore, automated disk space checking and deletion logic directly within the bot is unnecessary.

## Scope
*   Create `src/moviebot/tools/space_guard_tool.py` to audit disk usage.
*   Query Plex/Tautulli view history to identify files in `F:\_temp\movies` that have been watched by the home server users.
*   Implement a safe cleanup filter: files can only be auto-deleted if:
    1.  They have been watched (view count >= 1 or marked watched on Plex).
    2.  The disk capacity exceeds a configurable threshold (e.g. 90% full).
    3.  They are older than a specific age (e.g. 14 days) if not watched.
*   Persist cleanup events in the `events` table.

## Out Of Scope
*   Interfacing with debrid magnet deletions.
*   Moving files to other storage pools.

## Acceptance Criteria
*   Running the tool in dry-run mode returns a list of candidate files for deletion.
*   The disk monitor accurately measures free space.
*   Deletions are logged and auditable in the SQLite database.
