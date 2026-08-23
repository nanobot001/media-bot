# Block 4.7: TV Mid-Season Backfill Engine

## Objective
Implement an automated backlog detection and backfill engine that scans for missing episodes when an ongoing show is added to the watchlist mid-season. Supports both full-season backlog backfill and granular single/selected episode backfills, with dry-run safety gates.

## Requirements
- Gap Analysis:
  - When a show is added at episode `N` (e.g. current episode 8), query TMDb via `get_tv_season_facts` (from Block 4-3) for total episode count and air dates.
  - Query `tvbot.sqlite3` / Plex mirror (from Block 4-3b) for already-owned episodes.
  - Compute the exact list of missing episodes (e.g. episodes 1, 2, 3, 4, 5, 6, 7).
- Backfill Resolution:
  - **Full-Backlog Mode (`backfill_show_tool`)**: Searches Prowlarr for single episode releases or partial season packs covering all missing episodes, verifies `⚡ Lightning (Instant Cache)` on AllDebrid, and queues all missing episodes to IDM in batch.
  - **Granular Episode Mode (`backfill_episodes_tool`)**: Allows selecting specific episode numbers (e.g. only episode 3, or episodes 3 and 5) to search and download individually.
- Reusable Core Function:
  - `async def resolve_missing_episodes(show_tmdb_id, season, missing_episodes: List[int], quality: str, dry_run: bool = False) -> Dict[str, Any]` — shared by Block 4-8 (airing monitor).
- Provide dry-run-first preview and safety gates.

## Dependencies
- Block 4-3 (TMDb TV season/episode facts)
- Block 4-3b (TV Plex library mirror and owned episode check)
- Block 4-4 (TV Prowlarr search)
- Block 4-5 (TV download pipeline)
- Block 4-6 (TV watchlist state)

## Acceptance Criteria
- [ ] Gap detection accurately identifies missing episodes from 1 to `N` against Plex library records.
- [ ] Full-backlog mode enqueues all missing episodes in one operation.
- [ ] Granular mode allows targeting specific individual episodes.
- [ ] Dry-run option previews the backfill queue without triggering downloads.
- [ ] `resolve_missing_episodes` is importable and testable independently.
- [ ] Unit tests verify backfill calculation, search routing, and batch enqueueing.
