# Continue Here

## 2026-08-23

Current State:
- **Phase 2 Complete**: All media intelligence blocks (2-1 through 2-12) implemented, verified, and merged.
- **Phase 3 Complete**: Conversational library RAG, AI user memory, external recommendations, persona settings, multi-user context, and Tautulli playback notifications implemented, verified, and merged.
- **Phase 4 (Stage 1: Interactive Foundation) COMPLETE**:
  - **Block 4-0 (Roadmap & Charter Multi-Library Realignment)**: Supported `movies`, `tv`, and `tv_classic` as first-class domains. Completed.
  - **Block 4-1 (Domain Database Router)**: Configured per-domain SQLite DB paths in settings and routed connections/initializations safely. Completed.
  - **Block 4-2 (Plex Section Domain Mapping)**: Mapped Plex sections to media domains, prepared domain-routed sync behavior, preview CLI and FastMCP tools. Completed.
  - **Block 4-3 (Discovery Engine & TMDb TV Extension)**: Unified domain-parameterized discovery tool (Movies, TV, Classic TV) with TMDb TV endpoints, library dedup, and era/network filters. Completed.
  - **Block 4-3b (TV & Classic TV Plex Library Sync & Mirror)**: Ingested Plex TV shows and episode inventories into `tvbot.sqlite3` and `tvclassicbot.sqlite3`, built `TVLibraryRepository`, `sync_tv_library_tool`, CLI `sync-tv`, FastMCP `sync_tv_library`, and canonical `is_show_or_episode_owned` deduplication helper. Completed.
  - **Block 4-4 (TV & Classic TV Prowlarr Search & Category Routing)**: Generalized Prowlarr adapter with Category 5000/5030/5040/5045, structured season/episode query formatting, real-time AllDebrid instant cache verification, domain-isolated token caching in SQLite, CLI `search-tv`, and FastMCP `search_sources` extension. Completed.
  - **Block 4-5 (TV Episode Parsing & Download Pipeline)**: Built `tv_file_selection.py` (SxxExx regex parsing and junk exclusions), batch AllDebrid stream `unlock_links`, batch IDM `send_batch_to_idm`, 3-way destination folder routing (`F:\_temp\movies`, `F:\_temp\tv`, `F:\temp\Classic Tv`), per-episode SQLite `download_jobs` tracking across domains, and Just-In-Time Show-Level TMDb enrichment. Completed.
- **Verification**: Clean run of the test suite (288/288 pytest tests passing successfully).

---

## 3-Stage Master Implementation Plan

### Stage 1: Interactive Foundation (Backend Core for Web UI) — COMPLETED
1. **[Block 4-3: Discovery Engine & TMDb TV Extension](docs/blocks/block-4-3-discovery-engine-tmdb-tv.md)** (Completed)
2. **[Block 4-3b: TV & Classic TV Plex Library Sync & Mirror](docs/blocks/block-4-3b-tv-plex-library-sync.md)** (Completed)
3. **[Block 4-4: TV & Classic TV Prowlarr Search & Category Routing](docs/blocks/block-4-4-tv-search-category-routing.md)** (Completed)
4. **[Block 4-5: TV Episode Parsing & Download Pipeline](docs/blocks/block-4-5-tv-episode-parsing-download-pipeline.md)** (Completed)

### Stage 2: The Revamped Web UI Cockpit (Phase 5) — NEXT
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
    - Autopilot sweep for newly aired episodes on broadcast days, automatic IDM queueing, finale detection, and auto-archiving.
11. **[Block 4-9: Weekly Release Discord Notifier & In-Line Ingest](docs/blocks/block-4-9-discord-weekly-digest.md)**
    - Discord digest reusing 4-3's discovery engine, interactive `⚡ Ingest` / `🚫 Ignore` buttons, and weekly cron.

---

### Staging Directories Reference
- **Movies**: `F:\_temp\movies` (`settings.output_dir`)
- **TV**: `F:\_temp\tv` (`settings.tv_output_dir`)
- **Classic TV**: `F:\temp\Classic Tv` (`settings.tv_classic_output_dir`)

---

### Immediate Next Step for Resuming
- Prepare and implement **`docs/blocks/block-5-1-web-ui-discovery-domain-switcher.md`** (Phase 5: Stage 2 Web UI Cockpit).
