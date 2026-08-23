# Continue Here

## 2026-06-04

Current State:
- **Phase 2 Complete**: All media intelligence blocks (2-1 through 2-12) have been successfully implemented, verified, and merged.
  - **Block 2-1 (Media Intelligence Schema & FTS5)**: Added 17 new columns to `library_items` table and FTS5 search indexing.
  - **Block 2-1b (Quality Upgrade Deduplication)**: Added quality-upgrade logic while maintaining duplicate protection.
  - **Block 2-2 (Vector Embedding & Similarity Engine)**: Setup Gemini API embedding integration with cache.
  - **Block 2-3 (Taste Recommender & Collection Audit)**: Developed personalized movie recommendations based on Tautulli watch history and franchise series gap analysis.
  - **Block 2-4 (Unified Discord & MCP Interface)**: Deployed `/library`, `/recommend`, and `/audit` Discord commands and exposed them as MCP tools.
  - **Block 2-5 & 2-6 (Structured/Typed Enrichment Metadata)**: Implemented structured settings, themes, tones, craft facets, and content-warning metadata.
  - **Block 2-7 (Gemini Enrichment Source)**: Added optional automated LLM-based metadata generation with rules-based fallback.
  - **Block 2-8 & 2-9 (Plex & Hard-Fact Discovery)**: Sourced credits, awards, source material, cultural impact, and popularity facts.
  - **Block 2-10 (Authority-Backed Hard-Fact Population)**: Built dry-run-first Wikidata/Gemini population pipeline for hard facts.
  - **Block 2-11 (TMDb Franchise & Brand Enrichment)**: Sourced canonical franchise/universe names and resolved aliases.
  - **Block 2-12 (Enriched Search Embeddings & Backfill)**: Migrated to metadata-enriched composite search embeddings, resolving descriptive/subjective search false positives. Activated and verified the subjective search regression harness.
- **Tidy Blocks Layout**: Moved all completed Phase 2 block files into `docs/blocks/completed/` directory.
- **Verification**: Clean run of the test suite (150/150 pytest tests passing successfully).

- **Phase 3: Conversational Library RAG & Ask Command**:
  - **Block 3-0 (RAG Infrastructure & Caching)**: Completed the unified Gemini API completion client with exponential backoff retry and DB error logging, token-efficient metadata minifier, and thread-safe async TTL cache.
  - **Block 3-1 (Conversational Library RAG & Ask Command)**: Exposed conversational search via developer CLI subcommand `ask`, FastMCP server tool `ask_library`, and Discord slash command `/ask` with citations. Completed full testing & verification.
  - **Block 3-2 (AI User Working Memory & Plex Mapping)**: Implemented `/profile` commands, Plex username mapping with claim locking, taste modals, organic memory extraction, and conversational RAG tailoring based on active preferences. Completed full testing & verification (all 179 tests pass).
  - **Block 3-3 (External Parametric Recommendations)**: Implemented non-db movie recommendation suggestions using TMDb, with verification safety gates and interactive "Search & Add" button confirmation flows.
  - **Block 3-3b (Persona Settings & Conversational History)**: Added persistent bot persona overrides, slash commands, FastMCP server tools, CLI commands, multi-turn conversational history injection (last 10 turns), and SQLite user memory database limits pruning to 1,000 entries.
  - **Block 3-4 (Multi-User Context & Privacy Guards)**: Added multi-user thread parsing with speaker tags and PII masking, local privacy interception to prevent cross-user details snooping, and interactive Discord joint session consent modals.
  - **Block 3-5 (Rich Tautulli Playback Notifications)**: Added session-aware playback start/stop/watched Discord card updates, automatic Plex thumbnail upload attachments, non-secret message tracking, and structured logging.
- **Phase 4: Multi-Library Realignment**:
  - **Block 4-0 (Roadmap & Charter Multi-Library Realignment)**: Formally realigned the project charter and block indexes to support `movies`, `tv`, and `tv_classic` as first-class domains, with defined MVPs and movie-derived engineering lessons (anime delegated to `anime-pipe`). Completed.
  - **Block 4-1 (Domain Database Router)**: Configured per-domain SQLite DB paths in settings and routed connections/initializations safely, keeping movie backward compatibility intact. Completed.
  - **Block 4-2 (Plex Section Domain Mapping)**: Map Plex sections to media domains, prepare domain-routed sync behavior, and add preview CLI commands and FastMCP tools. Completed.
  - **Block 4-3 (Discovery Engine & TMDb TV Extension)**: Unified domain-parameterized discovery tool (Movies, TV, Classic TV) with TMDb TV endpoints, library deduplication, and era/network filters. FastMCP `discover_media` tool and CLI `discover` subcommand deployed. Completed.
  - **Block 4-3b (TV & Classic TV Plex Library Sync & Mirror)**: Ingested Plex TV shows and episode leaf inventories into `tvbot.sqlite3` and `tvclassicbot.sqlite3`, built `TVLibraryRepository`, `sync_tv_library_tool`, CLI `sync-tv`, FastMCP `sync_tv_library`, and canonical `is_show_or_episode_owned` deduplication helper. Completed.

## 3-Stage Master Implementation Plan

### Stage 1: Interactive Foundation (Backend Core for Web UI)
1. **[Block 4-3: Discovery Engine & TMDb TV Extension](docs/blocks/block-4-3-discovery-engine-tmdb-tv.md)** (Completed)
   - Unified domain-parameterized discovery tool (Movies, TV, Classic TV) with TMDb TV endpoints, library dedup, and era/network filters.
2. **[Block 4-3b: TV & Classic TV Plex Library Sync & Mirror](docs/blocks/block-4-3b-tv-plex-library-sync.md)** (Completed)
   - Mirror Plex TV and Classic TV sections into `tvbot.sqlite3` and `tvclassicbot.sqlite3` with show hierarchies and episode inventories for deduplication.
3. **[Block 4-4: TV & Classic TV Prowlarr Search & Category Routing](docs/blocks/block-4-4-tv-search-category-routing.md)**
   - Generalize Prowlarr adapter for Category 5000 (TV), structured season/episode query parsing, and token caching.
4. **[Block 4-5: TV Episode Parsing & Download Pipeline](docs/blocks/block-4-5-tv-episode-parsing-download-pipeline.md)**
   - SxxExx manifest parsing, batch AllDebrid unlock, batch IDM enqueue, and 3-way destination folder routing (`F:\_temp\movies`, `F:\_temp\tv`, `F:\temp\Classic Tv`).

### Stage 2: The Revamped Web UI Cockpit (Phase 5)
5. **[Block 5-1: Web UI Discovery & 3-Domain Switcher](docs/blocks/block-5-1-web-ui-discovery-domain-switcher.md)**
   - Top-level `[Movies / TV / Classic TV]` switcher and trending/popular poster feeds with filter pills.
6. **[Block 5-2: Web UI Search & ⚡ Lightning Cache Badging](docs/blocks/block-5-2-web-ui-search-lightning-badges.md)**
   - Prowlarr search integration with real-time AllDebrid instant cache checks and glowing ⚡ badges.
7. **[Block 5-3: Web UI Ingestion Modals & Telemetry](docs/blocks/block-5-3-web-ui-ingestion-modals-telemetry.md)**
   - 1-click Movie grabs, TV season/episode picker modal, and live SSE download speed telemetry bar.

### Stage 3: Autonomous Background Engines (Post-UI Automation)
8. **[Block 4-6: TV Watchlist State & Storage](docs/blocks/block-4-6-tv-watchlist-storage.md)**
   - SQLite `tv_watchlist` repository (`watching`, `completed`, `archived`), `release_day` calendar schedules, and management tools.
9. **[Block 4-7: TV Mid-Season Backfill Engine](docs/blocks/block-4-7-tv-backfill-engine.md)**
   - Gap analysis using Plex episode inventory, full-backlog + granular per-episode backfill, reusable `resolve_missing_episodes` function, and dry-run safety.
10. **[Block 4-8: TV Airing Monitor & Auto-Archiving](docs/blocks/block-4-8-tv-airing-monitor.md)**
    - Anime-pipe style autopilot sweep for newly aired episodes on broadcast days, automatic IDM queueing, finale detection, and auto-archiving.
11. **[Block 4-9: Weekly Release Discord Notifier & In-Line Ingest](docs/blocks/block-4-9-discord-weekly-digest.md)**
    - Discord digest reusing 4-3's discovery engine, interactive `⚡ Ingest` / `🚫 Ignore` buttons, and weekly cron.

### Staging Directories Reference
- **Movies**: `F:\_temp\movies` (`settings.output_dir`)
- **TV**: `F:\_temp\tv` (`settings.tv_output_dir`)
- **Classic TV**: `F:\temp\Classic Tv` (`settings.tv_classic_output_dir`)

### Immediate Next Step for Resuming
- Execute **`docs/blocks/block-4-4-tv-search-category-routing.md`** using the `$implement-block` skill.

### Future Roadmap / Backlog Reminders
- **Full TV Show-Level AI Semantic Enrichment & Embeddings**: Once Stages 1–3 (download pipeline, Web UI, backfill, and airing autopilot) are completed, revisit extending `sync-enrichment` and Gemini vector embeddings to `tvbot.sqlite3` and `tvclassicbot.sqlite3` at the Show Entity level (enabling deep conversational RAG `/ask` across TV and Classic TV without episode-level token waste).

Do-not-forget checks:
- Maintain rate limits when querying Gemini and TMDb APIs.
- Keep in-memory caches active to optimize vector similarity query times.
- Ensure the Docker-to-host bridge routing via `host.docker.internal` remains active.
- TV & Classic TV enrichment runs just-in-time at first download/ingest at the Show Entity level.



