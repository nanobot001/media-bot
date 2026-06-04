# Changelog

## [Unreleased]

## [1.3.0] - 2026-06-04

- **Composite Document Search Embeddings**:
  - Implemented metadata-enriched composite search document builder (`Title + Genres + Tones + Themes + Synopsis`) to prevent false-positives and improve subjective classification.
  - Configured deterministic SHA256 hashing of composite documents to serve as the cache invalidation key, triggering automatic re-embedding on the next sync if any field changes.
  - Updated webhook sync pipeline and enrichment runner to generate and persist composite document embeddings.
- **Library-Wide Vector Backfill**:
  - Developed `scripts/run_embeddings_backfill.py` providing a rate-limited, batched runner for library-wide vector updates.
  - Created orchestration runner `scripts/run-embeddings-backfill.ps1` that performs automated database backups before running updates.
- **Verification & Regression Testing**:
  - Activated subjective query routing regression tests (`tests/test_query_library_semantic_regression.py`) to confirm strict isolation of query intent.
  - Refactored `tests/test_intelligence.py` to align with the new composite document structure and caching logic.

## [1.2.0] - 2026-06-04

- **TMDb Franchise & Brand Enrichment**:
  - Implemented rate-limited `TMDbFactProvider` and deterministic alias resolver rules for canonical brand, franchise, and universe tags extraction.
  - Refined James Bond franchise matching patterns to support relaxed query routing rules (e.g. "bond movies").
  - Modified DB enrichment pipeline to run self-healing sqlite migrations automatically and support `--only-missing-brands` targeting.
- **Discord Search & UI Transparency**:
  - Enhanced `/library` search command to explicitly visualize active search criteria and inferred routing filters (e.g., brand, franchise, universe, locations).
  - Appended canonical TMDB franchise, brand, and universe metadata tags to search results in Discord.
  - Integrated tagline and truncated synopsis previews for all matching results.
  - Enriched `/movie` details card with dedicated `Brand`, `Franchise`, and `Universe` tag fields in the Enrichment block.
- **Testing & Verification**:
  - Extended testing regression suites to verify new formatting layout, search isolation, and query routing, with all 150 tests passing.

## [1.1.1] - 2026-06-01

- Added `/movie` to show a detailed movie database card with synopsis, core metadata, library quality details, cast/crew, enrichment tags, hard facts, content warnings, and provenance fields. (2026-06-01)
- Added pipeline-triggered auto-enrichment notifications so media-bot downloads post the rich "New Movie Added" card when the pipeline reaches Plex, without requiring Tautulli; webhook notifications now share the same duplicate-post guard. (2026-06-01)
- Updated `/help` to include the latest library/enrichment commands and added test coverage so help text stays aligned with future command changes. (2026-06-01)

## [1.1.0] - 2026-05-31

- **Media Intelligence Layer (Phase 2)**:
  - **Block 2-4 — Unified Discord, CLI & MCP Interface**:
    - Integrated `/library`, `/recommend`, and `/audit` slash commands exposing advanced FTS5 search, vector-based semantic search, personalized recommendations, and sequel gap auditing to Discord.
    - Designed interactive `CollectionAuditView` and `SearchMissingButton` allowing users to trigger Prowlarr searches and AllDebrid download handoffs for missing sequel gaps in one click.
    - Exposed new intelligence tools (`query_library_tool`, `recommend_movies_tool`, `audit_collections_tool`) through the FastMCP server.
  - **Block 2-3 — Collection Gap Auditor**:
    - Built heuristic sequel/prequel analysis auditing collections against owned library items.
  - **Block 2-2 — Taste Profiler Recommendation Engine**:
    - Built vector-similarity personalized taste recommendation scorer mapping Tautulli watch history profiles to unwatched movies.
  - **Block 2-1 — Media Intelligence Schema & Backfill**:
    - Evolved database layer to support media intelligence by adding 17 new columns and FTS5 indexing to the `library_items` table.
    - Implemented self-healing migrations in `init_db()` and a CLI backfill command `sync-intelligence` supporting Google Gemini (`text-embedding-004`) and local Ollama embeddings.
  - **Plex Library Filtering & Sync Cleanup**:
    - Added `ignored_plex_sections` to settings/`.env` to exclude non-movie Plex sections (like `Learning`, `Workouts`, `Raptors`).
    - Updated `PlexClient` and the sync subcommands to filter out ignored sections and delete old, now-ignored movie records from the database.
  - **Webhook-Based Intelligent Sync**:
    - Enhanced the Tautulli FastAPI webhook handler to automatically perform detailed metadata extraction and vector embedding generation (`text-embedding-004`) on the fly when new movies are added to Plex.

## [1.0.0] - 2026-05-30

- **Block 08 — Pipeline Status Card & Media Watcher State Bridge**:
  - Implemented the `/status` interactive slash command, allowing users to query job status cards by title or browse recent jobs. (2026-05-30)
  - Added interactive Discord UI components `StatusDropdown` and `StatusSelectView` to handle job selection when multiple search results exist or no title is provided. (2026-05-30)
  - Integrated `PipelineStatusService` to reconstruct and display live status cards in response to slash commands. (2026-05-30)
  - Added unit test cases verifying the `/status` command, dropdown callbacks, and search matches. (2026-05-30)

- **Discord Help Command**:
  - Implemented `/help` slash command dynamically presenting a role-based list of available commands and a workflow guide.
  - Users are presented with a clean overview of standard user commands (search, download, status, history, sync) and a step-by-step pipeline workflow.
  - Authorized **Bot Managers** dynamically see system, diagnostic, and logs tailing command definitions in the response.
  - Added unit test cases verifying correct response embeds and role-based fields visibility for both bot managers and regular users.

- **Block 07 — Discord Observability & Match Doctor**:
  - Extended `PlexClient` with `unmatch_item`, `get_matches`, and `match_item` methods for programmatic Plex metadata correction via the Plex HTTP API.
  - Implemented `MismatchGuard` engine (`core/mismatch_guard.py`) using `rapidfuzz` for string similarity auditing between download job filenames and Plex-matched metadata.
  - Built hybrid auto-correction logic: high-confidence mismatches are auto-rematched via the Plex search agent; low-confidence conflicts surface as interactive Discord alerts.
  - Added interactive Discord UI components: `RematchSearchModal`, `RematchCandidateSelect`, `MismatchAlertView` with Fix/Keep buttons for manual metadata repair.
  - Added `/debug <rating_key>` slash command for on-demand MismatchGuard audits with rich embed status cards.
  - Connected MismatchGuard execution to the Tautulli webhook handler, triggering on both `watched` and `library-add` events.
  - Added `post_mismatch_alert()` helper to push mismatch warnings to the configured Discord channel with interactive repair buttons.
  - Created comprehensive test suites: `tests/test_mismatch_guard.py` (8 tests) and `tests/test_plex_client.py` (4 tests) covering similarity utils, audit logic, and Plex API endpoints.
  - Updated `test_tautulli_webhook.py` to verify MismatchGuard integration on webhook sync events.
  - Added `rapidfuzz` and `respx` as project dependencies.

- **Block 06 — Diagnostics & Observability Stabilization**:
  - Stabilized the host-side `idm-bridge` PM2 process by implementing a Node.js hidden-window parent wrapper (`scripts/idm_bridge_launcher.js`) and adding a `/health` endpoint to the PowerShell listener.
  - Stabilized the FastAPI webhook server lifecycle (`webhook.py`) and log stream buffering.
  - Implemented `/health` and `/status` Discord slash commands, and exposed SQLite events query and log tailing tools (`get_recent_events_tool` and `tail_logs_tool`).
  - Added new `/events [limit]` and `/logs <source> [lines]` Discord slash commands to allow bot managers to query SQLite event records and tail log streams.
  - Expanded unit test coverage in `tests/test_discord_app.py` for `/events` and `/logs` commands, passing a total of 39 tests.
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
