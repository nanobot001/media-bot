# Changelog

## [Unreleased]

## [1.5.2] - 2026-06-05

- **Block 3-3 — External Parametric Recommendations & Search Integration**:
  - Extended the conversational RAG prompt to allow the LLM to suggest movies not present in the library using `[External Recommendation: Title (Year)]` markers when a user asks what to add next.
  - Implemented `parse_external_recommendations()` and `remove_filtered_external_markers()` to extract, validate, and clean LLM-emitted external suggestion markers from generated answers.
  - Implemented `filter_external_recommendations()` with a multi-gate filter pipeline:
    - **Ownership gate (zero prompt-token cost):** Wires the existing `evaluate_deduplication()` engine (4-tier: IMDb ID → exact normalized title+year → fuzzy Levenshtein ≥ 0.90 → not_found) to silently drop any external rec the user already owns. No library manifest is injected into the prompt — the check happens entirely in Python post-generation.
    - **Content rating gate:** Verifies suggestions against the user's `max_content_rating` profile setting via TMDb API.
    - **Genre exclusion gate:** Drops suggestions matching the user's `excluded_genres` profile list.
  - Added strict alphanumeric title sanitization (`sanitize_external_title`) to prevent injection via LLM-emitted titles before they reach search query execution.
  - Added `🔍 Search & Add` Discord buttons next to external recommendations, gated behind a two-step Yes/No confirmation flow to prevent accidental download triggers.
  - Added domain lock (`is_media_domain_question`) to refuse non-media queries before they reach the LLM.
  - Added unit/integration test suite `tests/test_external_recommendations.py` (6 tests) verifying parsing, sanitization, content gate, ownership gate, and button flow.

## [1.5.1] - 2026-06-05

- **Movie Poster Integration**:
  - Added a `poster_url` column to the `library_items` table in the database schema.
  - Updated `LibraryItemRepository.upsert` and `LibraryItemRepository.update_tmdb_enrichment` to handle `poster_url` storage, employing a `COALESCE` fallback pattern to preserve existing poster URLs when Plex updates library items.
  - Updated `TMDbFactProvider` to retrieve `poster_path` from the TMDb API movie details.
  - Updated `sync_enrichment_tool.py` to construct and save the full `w500` poster URLs during scheduled enrichment sweeps.
  - Enhanced the Discord `/movie` command detail embeds to display movie posters using `set_image(url=poster_url)`.
  - Implemented dynamic poster resolution in the background using a thread executor if the database entry lacks a poster URL.

## [1.5.0] - 2026-06-04

- **AI User Working Memory & Plex Mapping**:
  - **Block 3-2 — AI User Working Memory & Plex Mapping**:
    - Implemented Discord user profile mapping `/profile show` to link Discord accounts to Plex/Tautulli usernames.
    - Designed interactive `ProfileMainView` featuring modals for claim-locking Plex accounts, updating custom taste preferences manually, resetting/deleting memories, and choosing specific memory facts to prune.
    - Created the `UserMemoryManager` to organically extract atomic user taste preferences (likes, dislikes, general preferences) from chat messages using Gemini.
    - Updated conversational RAG to personalize results by automatically retrieving and compiling active user preferences and memories.
    - Added database schemas for user profiles (`user_profiles`), atomic memories (`user_memories`), and query history (`user_interaction_memory`).
    - Added unit and integration test suite `tests/test_user_profile.py` verifying profile CRUD operations, memory extraction, context compilation, and profile resets.

## [1.4.0] - 2026-06-04

- **Conversational Library RAG (Phase 3)**:
  - **Block 3-1 — Conversational Library RAG & Ask Command**:
    - Implemented the `ask` subcommand in developer CLI `tool_cli.py` to route natural language queries to the conversational RAG engine.
    - Implemented the `/ask` slash command in `discord_app.py` returning conversational RAG answers with citations (titles/years) formatted as interactive embeds.
    - Added `LibraryItemRepository.get_by_id` static method to `repositories.py` for looking up details of cited library items.
    - Exposed the `ask_library` tool via the FastMCP server.
    - Added unit test cases verifying `/ask` CLI routing, Discord slash command embeds, MCP ask_library tool invocation, and mock databases.
  - **Block 3-0 — RAG Infrastructure & Caching**:
    - Implemented centralized `generate_gemini_content` API client in `src/moviebot/core/gemini_client.py` with exponential backoff retry logic and automatic error logging to the database via `ErrorLogRepository`.
    - Developed `minimize_movie_metadata` in `src/moviebot/core/conversational_rag.py` for token-efficient pruning of library items to fit conversational contexts.
    - Implemented thread-safe, async-capable, in-memory TTL query cache `RAGQueryCache` to cache generation results.
    - Added unit test suite `tests/test_conversational_rag.py` verifying all core functionalities with 100% success.

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
    - Implemented self-healing migrations in `init_db()` and a CLI backfill command `sync-intelligence` supporting Google Gemini (`gemini-embedding-001`) and local Ollama embeddings.
  - **Plex Library Filtering & Sync Cleanup**:
    - Added `ignored_plex_sections` to settings/`.env` to exclude non-movie Plex sections (like `Learning`, `Workouts`, `Raptors`).
    - Updated `PlexClient` and the sync subcommands to filter out ignored sections and delete old, now-ignored movie records from the database.
  - **Webhook-Based Intelligent Sync**:
    - Enhanced the Tautulli FastAPI webhook handler to automatically perform detailed metadata extraction and vector embedding generation (`gemini-embedding-001`) on the fly when new movies are added to Plex.

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
