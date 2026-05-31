# Block 2-1: Media Intelligence Schema, FTS5 Indexing & Backfill

> Status: Proposed
> Result: Pending
> Verification: Run `pytest tests/test_intelligence.py` and inspect database structure using a sqlite helper.

## Goal
Extend the SQLite database schema with durable intelligence fields, establish trigger-based FTS5 full-text indexing, and add a dry-run-safe backfill path for enriching existing Plex library rows.

## Scope
* **Self-Healing Migrations**:
  * In `moviebot/db/connection.py`, update `init_db` to inspect `library_items` and run `ALTER TABLE` for missing columns:
    * `genres` (TEXT - JSON array string)
    * `directors` (TEXT - JSON array string)
    * `rating` (REAL - rating score)
    * `runtime` (INTEGER - duration in minutes)
    * `collections` (TEXT - JSON array string)
    * `resolution` (TEXT - e.g. '2160p', '1080p')
    * `bitrate_kbps` (INTEGER)
    * `watch_status` (TEXT - 'watched', 'unwatched')
    * `watch_count` (INTEGER DEFAULT 0)
    * `last_watched_at` (TEXT - ISO timestamp)
    * `synopsis` (TEXT)
    * `synopsis_hash` (TEXT - stable hash used to detect stale embeddings)
    * `metadata_refreshed_at` (TEXT - ISO timestamp for last rich metadata refresh)
    * `synopsis_vector` (BLOB - raw float array)
    * `synopsis_vector_model` (TEXT - embedding provider/model name)
    * `synopsis_vector_dim` (INTEGER - vector dimension)
    * `synopsis_vector_updated_at` (TEXT - ISO timestamp)
* **FTS5 Virtual Table & Triggers**:
  * Create virtual table `library_items_fts` using `fts5(title, genres, directors, collections, synopsis, content='library_items', content_rowid='rowid')`.
  * Implement three triggers (`library_items_ai`, `library_items_ad`, `library_items_au`) to synchronize inserts, deletes, and updates from `library_items` into `library_items_fts` using the source table `rowid`.
* **Repository Enriched Ingest**:
  * Update `LibraryItemRepository.upsert` inside `moviebot/db/repositories.py` to persist all new columns.
  * Update `PlexClient` metadata parsing in `moviebot/adapters/plex_client.py` (`fetch_all_movies` / `fetch_movie_details`) to parse these attributes from the Plex XML/JSON API response.
* **Backfill Command**:
  * Add `sync-intelligence` to `moviebot/cli/tool_cli.py`.
  * Support `--dry-run` by default for previewing metadata, FTS, and future embedding work without writing.
  * Real mode should refresh metadata fields and FTS rows without changing download state or queue behavior.

## Out Of Scope
* Implementing vector embeddings calculation API calls.
* Building Discord UI views or slash commands.
* Implementing recommendation taste algorithms.
* Changing duplicate/download blocking behavior; quality-upgrade dedupe belongs to Block 2-1b.

## Implementation Instructions
1. Edit `src/moviebot/db/connection.py` to check for column existence (via `PRAGMA table_info(library_items)`) and dynamically execute `ALTER TABLE library_items ADD COLUMN <name> <type>` for any missing columns.
2. Add triggers to `init_db()` to automatically populate `library_items_fts` on write.
3. Update `LibraryItemRepository.upsert` to include the new column values in the insert/update SQL statements.
4. Add deterministic hashing for synopsis text so later embedding work can detect stale vectors.
5. Add the dry-run-safe `sync-intelligence` command as the cheap operator-facing verification path.

## Acceptance Criteria
* Running database initialization automatically applies schema updates to an existing database without data loss.
* Adding a movie to `library_items` automatically registers its title, genres, and directors in `library_items_fts`.
* Querying `library_items_fts` with FTS syntax (e.g. `title MATCH 'Matrix'`) successfully returns matching records.
* Updating or deleting a movie keeps the external-content FTS5 table synchronized by `rowid`.
* `sync-intelligence --dry-run` returns a structured preview and performs no writes.

## Verification Commands
```powershell
$env:PYTHONPATH="src"
pytest tests/test_intelligence.py -k "test_migrations_and_fts"
pytest tests/test_intelligence.py -k "test_sync_intelligence_dry_run"
```
