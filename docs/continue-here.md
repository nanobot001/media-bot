# Continue Here

## 2026-08-25

Current State:
- **Phase 2 Complete**: All media intelligence blocks (2-1 through 2-12) implemented, verified, and merged.
- **Phase 3 Complete**: Conversational library RAG, AI user memory, external recommendations, persona settings, multi-user context, and Tautulli playback notifications implemented, verified, and merged.
- **Phase 4 (Stage 1: Interactive Foundation) COMPLETE**:
  - **Block 4-0 to 4-5**: All backend multi-domain infrastructure (router, Plex mirror, Prowlarr TV search, and download pipeline with 3-way routing) completed and verified.
- **Phase 5 (Stage 2: The Revamped Web UI Cockpit) COMPLETE**:
  - **Block 5-1 (Web UI Discovery Feeds, 3-Domain Switcher & Live Ingest Sidebar)**: Completed.
  - **Block 5-2 (Web UI Search & ⚡ Lightning Cache Badging)**: Completed.
  - **Block 5-3 (Web UI Ingestion Modals & Telemetry)**: Built 1-click movie downloads (`POST /api/ingest`), interactive TV season/episode picker checklist modal (`GET /api/tv/series-manifest`, `POST /api/tv/ingest-episodes`) with live Plex inventory cross-referencing, and floating bottom live SSE download telemetry dock (`/api/stream`). Completed and verified.
  - **Block 5-4 (3-Tier Media Lifecycle, Cloud Pre-Caching & Instant Streaming Player)**: Completed in the current feature branch, including cloud stream unlock, progress/history tracking, pre-caching, browser playback, and external-player launchers.
- **Verification**: Block 5-4 records 312/312 pytest tests passing. A fresh full-suite rerun remains pending because the available Python 3.12 runtime does not include pytest and the system launcher has no Python 3.12 installation.
- **Publication**: The completed web-cockpit work is pushed on `feat/block-5-3-web-ui-ingestion-modals-telemetry`; `main` is still awaiting integration.

---

## 3-Stage Master Implementation Plan

### Stage 1: Interactive Foundation (Backend Core for Web UI) — COMPLETED
1. **[Block 4-3: Discovery Engine & TMDb TV Extension](docs/blocks/block-4-3-discovery-engine-tmdb-tv.md)** (Completed)
2. **[Block 4-3b: TV & Classic TV Plex Library Sync & Mirror](docs/blocks/block-4-3b-tv-plex-library-sync.md)** (Completed)
3. **[Block 4-4: TV & Classic TV Prowlarr Search & Category Routing](docs/blocks/block-4-4-tv-search-category-routing.md)** (Completed)
4. **[Block 4-5: TV Episode Parsing & Download Pipeline](docs/blocks/block-4-5-tv-episode-parsing-download-pipeline.md)** (Completed)

### Stage 2: The Revamped Web UI Cockpit (Phase 5) — COMPLETED
5. **[Block 5-1: Web UI Discovery & 3-Domain Switcher](docs/blocks/block-5-1-web-ui-discovery-domain-switcher.md)** (Completed)
6. **[Block 5-2: Web UI Search & ⚡ Lightning Cache Badging](docs/blocks/block-5-2-web-ui-search-lightning-badges.md)** (Completed)
7. **[Block 5-3: Web UI Ingestion Modals & Telemetry](docs/blocks/block-5-3-web-ui-ingestion-modals-telemetry.md)** (Completed)
   - 1-click Movie grabs, TV season/episode picker checklist modal, and live floating SSE download telemetry dock.
8. **[Block 5-4: Web UI Instant Cloud Streaming & Media Player](docs/blocks/block-5-4-web-ui-instant-cloud-streaming.md)** (Completed)
   - In-browser video player modal (Plyr.js / Video.js) and 1-click desktop streaming launchers (VLC / Infuse / PotPlayer) for instant-cached AllDebrid releases.

### Stage 3: Autonomous Background Engines (Post-UI Automation)
9. **[Block 4-6: TV Watchlist State & Storage](docs/blocks/block-4-6-tv-watchlist-storage.md)**
   - SQLite `tv_watchlist` repository (`watching`, `completed`, `archived`), `release_day` calendar schedules, and management tools.
10. **[Block 4-7: TV Mid-Season Backfill Engine](docs/blocks/block-4-7-tv-backfill-engine.md)**
    - Gap analysis using Plex episode inventory, full-backlog + granular per-episode backfill, reusable `resolve_missing_episodes` function, and dry-run safety.
11. **[Block 4-8: TV Airing Monitor & Auto-Archiving](docs/blocks/block-4-8-tv-airing-monitor.md)**
    - Autopilot sweep for newly aired episodes on broadcast days, automatic IDM queueing, finale detection, and auto-archiving.
12. **[Block 4-9: Weekly Release Discord Notifier & In-Line Ingest](docs/blocks/block-4-9-discord-weekly-digest.md)**
    - Discord digest reusing 4-3's discovery engine, interactive `⚡ Ingest` / `🚫 Ignore` buttons, and weekly cron.

---

### Staging Directories Reference
- **Movies**: `F:\_temp\movies` (`settings.output_dir`)
- **TV**: `F:\_temp\tv` (`settings.tv_output_dir`)
- **Classic TV**: `F:\temp\Classic TV` (`settings.tv_classic_output_dir`)

---

### Immediate Next Step for Resuming
- Finish the recorded Python 3.12 verification and integrate the current feature branch into `main`.
- After that publication gate, **Block 4-6: TV Watchlist State & Storage** is the next implementation block. Do not begin 4-7, 4-8, or 4-9 until 4-6 is independently verified.
