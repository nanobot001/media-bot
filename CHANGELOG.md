# Changelog

## Unreleased

- **Block 05 — MCP Server Integration**:
  - Implemented an MCP server (`src/moviebot/cli/mcp_server.py`) using `FastMCP` exposing all 8 core/advanced system tools.
  - Standardized input arguments and type annotations for easy registration and AI agent discovery.
  - Added a dedicated test suite `tests/test_mcp_server.py` verifying correct schema registration and delegation.
  - Introduced local `Dockerfile` and updated `docker-compose.yml` to compile Python and packages locally to avoid remote image registry issues.
- **Block 04-1 — Active Jobs & Diagnostics**:
  - Extended `DownloadJobRepository` in `repositories.py` with `get_active_jobs()`, `get_all_jobs()`, and `update_job_details()`.
  - Added new core tools: `get_download_jobs_tool`, `resolve_pending_jobs_tool`, and `get_error_logs_tool` to list jobs, perform debrid sweeps, and access error logs.
  - Implemented automatic resolution background loop in `discord_app.py` for pending downloads, polling debrid at customizable intervals (`JOB_RESOLVER_POLL_INTERVAL`).
  - Added Discord slash commands `/jobs`, `/resolve`, and `/errors` (restricted to bot managers).
  - Added matching subcommands (`jobs`, `resolve-pending`, `errors`) to developer tool CLI `tool_cli.py`.
  - Created a comprehensive test suite in `tests/test_jobs_and_diagnostics.py` verifying all database operations, resolution heuristic outcomes, and check predicates.
- **Block 03 — Tautulli Webhooks**:
  - Implemented a FastAPI webhook listener on port 8000.
  - Added webhook security authentication using a shared API key/token (`TAUTULLI_WEBHOOK_SECRET`) supporting both `Authorization: Bearer` headers and query parameter `?token=`.
  - Created a database schema and `EventRepository` to log incoming Tautulli webhook events to the SQLite `events` table.
  - Implemented selective Plex library database syncs for `watched` events, using the Plex rating key to retrieve movie details via a new `PlexClient().fetch_movie_details` endpoint and update `library_items`.
  - Added a complete unit/integration test suite (`tests/test_tautulli_webhook.py`) verifying webhook authentication, db events logger, and Plex database sync.
- **Block 02 — Discord Gateway, Constraints & Audits**:
  - Implemented channel restrictions for Discord slash commands using `@in_allowed_channel()` decorator.
  - Added structured SQLite database error logging (`errors` table) and routing alerts to a designated Discord admin channel.
  - Integrated auto-pruning logic in `ErrorLogRepository` to cap recorded errors to 500.
  - Created a robust pytest suite in `tests/test_discord_app.py` covering constraints, error handling, alerts, and database pruning.
- Initial project scaffold.
