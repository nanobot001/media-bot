# Tool Adapter Memory

## Project Role

`media-bot` is a modular, stateful Discord automation assistant and tool server that allows users and AI agents to:
1. Search and cross-reference Plex libraries to avoid duplicate downloads.
2. Search movie indexers on Prowlarr.
3. Queue high-speed direct downloads using AllDebrid and Windows Internet Download Manager (IDM).
4. Run diagnostics on active downloads and system exceptions.

## Classification

New tool-friendly project built from scratch using decoupled, parameter-driven JSON tool boundaries with a Discord gateway presentation layer.

## Runtime Model

- **PM2-supervised host process (Windows)**: Starts via Node.js supervisor (`scripts/launcher.js`) using `pm2 start scripts/launcher.js --name media-bot`, which prefers the project `.venv\Scripts\python.exe`, validates Python 3.12 plus the required imports before launch, skips broken system executables, supports `MEDIABOT_PYTHON` / `MEDIABOT_PYTHONHOME` overrides, runs the module in a hidden window (`windowsHide: true`), and forwards termination signals to prevent orphaned processes.
- **Docker service**: A python:3.12-slim based container running on Docker compose alongside Prowlarr and Flaresolverr.
- **Web service**: FastAPI webhook listener running on port `8000` to receive Tautulli notifications.
- **MCP server**: A `FastMCP` stdio-based server (`src/moviebot/cli/mcp_server.py`) exposing the tools to AI assistants.

## Source Of Truth

A local SQLite database stored at `data/moviebot.sqlite3` containing Plex cache mirrors, search logs, download job tracks, and exception logs.

## Instant Stream Readiness Contract

- `available_now` is a TMDb release-window classification only; it is not evidence of an AllDebrid cache.
- Discovery stream fields are derived from recent pre-warm verification: `cloud_cached`, `instant_download_ready`, `instant_cached`, `browser_stream_ready`, `instant_stream_status`, and `stream_reference_id`.
- `instant_cached` means a verified browser-streamable cached release only. The raw provider cache bit remains available as `cloud_cached` / `cached` for instant downloading, even when the release requires an external player.
- Each durable `prewarmed_cache` media record keeps the cached download candidate in `reference_id` / `release_title` and the preferred browser-stream candidate in `browser_stream_reference_id` / `browser_stream_release_title`; Discover uses the latter when opening a stream.
- Browser one-click playback requires an explicitly identified MP4/M4V release with H.264-family video and AAC/MP3 audio; cached MKV, HEVC/AV1, DDP/DTS/TrueHD, or unknown-audio releases remain external-player candidates and must not receive the browser-ready lightning state.
- Discover keeps `Stream Now` disabled until that browser candidate is verified. `POST /api/stream/prepare` is the explicit browser-only acquisition path: it enforces exact movie title/year (or TV season/episode), verifies cached candidates against the actual AllDebrid filename, and otherwise queues only a release that explicitly advertises MP4/M4V + H.264/AVC + AAC/MP3. The unrestricted Search/IDM path remains separate.
- `cloud_transfer_intents` is the durable ownership boundary for AllDebrid operations initiated manually through Media Bot. `/api/cloud/transfers` and `/api/cloud/notifications` merge provider status only for these locally owned transfer IDs; account-wide AllDebrid history and passive pre-warm checks must stay silent.
- `generic_cloud_cache` means ready for instant AllDebrid download only. `browser_stream` may become browser-ready only after completed-file verification; the UI and notifications must not claim browser playback for a generic cached release.
- Movie pre-warming maintains separate durable SQLite-KV cursors for a recent release-year frontier (current year down through 1980) and a TMDB all-time popularity frontier. Existing cache records are reverified before new candidates are scanned; pre-1980 titles are reached through the all-time popularity lane rather than an oldest-first crawl.

## Existing Pieces Reused

Reuses regex/heuristic models and powerShell-bridge configurations (`run_idm_bridge.ps1`) derived from the adjacent `anime-pipe` project to delegate downloads from Docker containers to host Windows systems.

## Adaptation Gaps Filled

Successfully migrated to the AllDebrid `/v4.1` API. Implemented recursive dictionary-based directory flattening (`_flatten_files`) in the adapter to translate nested folders/files arrays to sequential flat IDs, maintaining 100% backward compatibility with downstream file selector tools.

## Tool Surface

All tools return standard JSON envelopes (`{ "ok": bool, "tool": str, "timestamp": str, "data": {} }` or `{ "ok": false, ... "error": {} }`):
1. `search_library`: Queries local Plex cache mirror.
2. `dedupe_check`: Normalizes titles and applies fuzzy Matching/IMDb checks to identify library duplicates.
3. `search_sources`: Searches Prowlarr indexers for category 2000 torrents, returning hashes instead of raw magnet keys.
4. `enqueue_download`: Initiates download pipeline in AllDebrid and hands off direct stream links to the IDM host bridge.
5. `get_download_jobs`: Returns current or past active job states.
6. `get_error_logs`: Lists recent database exceptions for audit.
7. `query_watch_history`: Fetches viewing timelines from Tautulli.
8. `resolve_pending_jobs`: Resolves AllDebrid jobs in `pending` status, pushes unlocked links to IDM, and moves states.

## Permission Boundaries

- `public_read`: `search_library`, `dedupe_check`, `search_sources`
- `trusted_read`: `get_download_jobs`, `get_error_logs`, `query_watch_history`
- `write_action`: `enqueue_download` (supports `dry_run`), `resolve_pending_jobs` (supports `dry_run`)

## State/Event Schema

- `library_items`: Normalised Plex media inventory.
- `search_results`: Tracked query caches with obfuscated magnet URLs.
- `download_jobs`: Download states (`pending`, `downloading`, `requires_selection`, `completed`, `failed`).
- `errors`: Pruned exception logs (max 500 records).
- `events`: Tautulli watch activities.
- `kv_store`: System cursors and state flags.

## Bot Usage Notes

- Discord slash commands validate constraints using `@in_allowed_channel()` decorator.
- Errors in commands auto-alert admins inside the `#media-errors` channel using Discord Embeds while logging stack traces to the SQLite `errors` table.
- A background worker runs every 60s in `discord_app.py` to auto-resolve pending torrent downloads.

## Do Not Break

- **Obfuscation**: Never expose raw magnet URLs or API keys in search tool return payloads.
- **Dry-run**: Always respect `dry_run=True` to allow pipeline logic validation without pushing actual links to IDM/AllDebrid.
- **Two-Step Debrid Resolve**: AllDebrid v4.1 requires checking `/magnet/status` (looking for `statusCode == 4`) followed by fetching file paths from `/magnet/files`.

## Known Limitations

- Limited to Movie downloads (Category 2000). TV shows are out-of-scope.
- Cannot organize, rename or relocate completed downloads (handled by separate `media-watcher` process).

## Verification Commands

- **Unit tests (Host)**: `$env:PYTHONPATH="src"; .\.venv\Scripts\python.exe -m pytest --ignore=tests/test_mcp_server.py`
- **CLI dry-run**: `.\.venv\Scripts\python.exe -m moviebot.cli.tool_cli download --id "<obfuscated_id>" --dry-run`
