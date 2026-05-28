# Block 04: Space Management Guard & Disk Monitor

**Status: PLANNED**

## Goal
Implement a scheduled worker or command utility that monitors storage disk capacity at `F:\_temp\movies` and automatically prunes old or already-watched media files to prevent drive exhaustion.

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
