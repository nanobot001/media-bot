# Block 4.6: TV Watchlist State & Storage

## Objective
Implement a persistent SQLite repository and tool interface for managing tracked TV series with subscription statuses (`watching`, `completed`, `archived`, `paused`), scheduled release days for calendar rendering, and autopilot monitoring flags.

## Requirements
- Create `tv_watchlist` SQLite schema (in the main database since it is a user tracking repository):
  - `id` (TEXT PRIMARY KEY), `show_title` (TEXT), `tmdb_id` (TEXT/INT), `tvdb_id` (TEXT/INT), `imdb_id` (TEXT).
  - `status` (TEXT: `watching`, `completed`, `archived`, `paused`).
  - `quality_preference` (TEXT: `1080p`, `4k`, `720p`, default `1080p`).
  - `preferred_release_group` (TEXT, optional).
  - `current_season` (INT), `last_downloaded_episode` (INT), `total_episodes_expected` (INT).
  - `release_day` (TEXT, e.g. `Monday`, `Tuesday`, `Wednesday`, `Thursday`, `Friday`, `Saturday`, `Sunday`).
  - `air_time` (TEXT, optional, e.g. `21:00`), `network` (TEXT, e.g. `HBO`, `FX`, `Prime Video`).
  - `is_monitored` (BOOLEAN default 1).
  - `created_at`, `updated_at`, `archived_at`.
- Tool interface:
  - `add_to_tv_watchlist_tool(show_title, tmdb_id, season, quality, is_monitored)`
  - `get_tv_watchlist_tool(status: Optional[str] = None)`
  - `get_tv_airing_schedule_tool(day: Optional[str] = None)` — returns monitored shows grouped by broadcast day for the calendar UI.
  - `update_tv_watchlist_status_tool(id, status, current_season, last_downloaded_episode)`
  - `archive_tv_show_tool(id)`
- FastMCP tools and CLI commands for watchlist and schedule querying.

## Dependencies
- **None on Blocks 4-4 or 4-5** — this is pure CRUD and can be implemented in parallel with the search/download pipeline.
- Consumed by: Block 4-7 (Backfill), Block 4-8 (Airing Monitor), and Phase 5 Web UI Airing Calendar.

## Acceptance Criteria
- [ ] Schema migrations create `tv_watchlist` table with `release_day`, `network`, and `is_monitored` columns.
- [ ] Shows can be added, queried, updated, and archived via tools.
- [ ] `get_tv_airing_schedule_tool` accurately groups monitored shows by day of the week.
- [ ] Status transitions (`watching` -> `completed` -> `archived`) are event-logged.
- [ ] Full unit test coverage for repository and tool methods.
