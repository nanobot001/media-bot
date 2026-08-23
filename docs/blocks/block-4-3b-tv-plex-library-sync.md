# Block 4.3b: TV & Classic TV Plex Library Sync & Mirror

> Status: Implemented on 2026-08-22.
> Result: Implemented.
> Verification: `pytest tests/test_tv_library_sync.py tests/test_discover_media.py tests/test_mcp_server.py` and `pytest` - 275 passed.
> Notes: Implemented Plex TV series and episode leaf ingestion, 3-tier TV schema (tv_shows, tv_seasons, tv_episodes, tv_shows_fts) in tvbot.sqlite3 and tvclassicbot.sqlite3, TVLibraryRepository CRUD, sync_tv_library_tool, CLI sync-tv, FastMCP sync_tv_library, Discord /sync domain selection, and canonical is_show_or_episode_owned deduplication.

## Objective
Implement Plex library synchronization and SQLite mirroring for `tv` and `tv_classic` domains, populating `tvbot.sqlite3` and `tvclassicbot.sqlite3` with show hierarchies, season inventories, and owned episode records for accurate deduplication and gap analysis.

## Requirements
- **Plex TV Ingestion (`adapters/plex_client.py`)**:
  - Implement `fetch_all_tv_shows(domain: str) -> List[Dict[str, Any]]`:
    - Sweeps Plex sections mapped to the target domain (`tv` or `tv_classic`).
    - Retrieves series metadata (Title, Year, TMDb/TVDB/IMDb GUIDs, Content Rating, Genres, Studios/Networks, Total Seasons/Episodes).
    - Queries show children to inventory owned seasons and episodes with file paths and video resolutions.
- **SQLite TV Schema & Repository (`db/repositories.py` & `db/connection.py`)**:
  - Bootstrap `tv_shows`, `tv_seasons`, and `tv_episodes` tables (with FTS5 virtual tables) in domain-specific databases (`tvbot.sqlite3`, `tvclassicbot.sqlite3`).
  - Implement `TVLibraryRepository` with upsert, query by title/year, GUID lookups, and owned episode set retrieval.
- **Tool & CLI Interface**:
  - Tool: `sync_tv_library_tool.py(domain: str, dry_run: bool = False)`
  - CLI: `python -m moviebot.cli.tool_cli sync-tv --domain tv|tv_classic [--dry-run]`
  - Discord: `/sync domain:tv` and `/sync domain:tv_classic`
- **Deduplication Gate Integration**:
  - Expose helper `is_show_or_episode_owned(title, year, season, episode, domain)` for `discover_media_tool` and the backfill engine.

## Acceptance Criteria
- [x] `PlexClient.fetch_all_tv_shows` retrieves structured series and episode inventories from mapped TV sections.
- [x] `init_db("tv")` and `init_db("tv_classic")` create TV tables, indices, and FTS5 triggers cleanly.
- [x] Running sync on `tv` populates `tvbot.sqlite3` with zero regressions to `moviebot.sqlite3`.
- [x] Running sync on `tv_classic` populates `tvclassicbot.sqlite3`.
- [x] Owned episode check correctly identifies present vs missing episodes.
- [x] Unit tests cover Plex TV response parsing, repository CRUD, and sync tool execution.

