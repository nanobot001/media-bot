# Continue Here

## 2026-08-23

Current State:
- **Phase 2 Complete**: All media intelligence blocks (2-1 through 2-12) implemented, verified, and merged.
- **Phase 3 Complete**: Conversational library RAG, AI user memory, external recommendations, persona settings, multi-user context, and Tautulli playback notifications implemented, verified, and merged.
- **Phase 4 (Stage 1: Interactive Foundation) COMPLETE**:
  - **Block 4-0 to 4-5**: All backend multi-domain infrastructure (router, Plex mirror, Prowlarr TV search, and download pipeline with 3-way routing) completed and verified.
- **Phase 5 (Stage 2: The Revamped Web UI Cockpit) IN PROGRESS**:
  - **Block 5-1 (Web UI Discovery Feeds, 3-Domain Switcher & Live Ingest Sidebar)**: Built FastAPI REST endpoints (`/api/discover`, `/api/details`, `/api/history`, `/api/domains`), mounted modern responsive SPA at `/`, integrated 3-domain toggle (`[🎬 Movies] [📺 TV Series] [📻 Classic TV]`), TMDb discovery poster grid with Plex ownership badges (`[IN PLEX]` / `[MISSING]`), Major Studio vs Indie & Boutique tier classifications and filtering, centered rich Media Detail Modal with directors, cast avatars, trailers, North American theatrical countdown windows, box office stats & budget ROI, and review quotes, plus live Recent Ingest Activity Sidebar and full Download History table. Completed.
- **Verification**: Clean run of the test suite (299/299 pytest tests passing successfully).

---

## 3-Stage Master Implementation Plan

### Stage 1: Interactive Foundation (Backend Core for Web UI) — COMPLETED
1. **[Block 4-3: Discovery Engine & TMDb TV Extension](docs/blocks/block-4-3-discovery-engine-tmdb-tv.md)** (Completed)
2. **[Block 4-3b: TV & Classic TV Plex Library Sync & Mirror](docs/blocks/block-4-3b-tv-plex-library-sync.md)** (Completed)
3. **[Block 4-4: TV & Classic TV Prowlarr Search & Category Routing](docs/blocks/block-4-4-tv-search-category-routing.md)** (Completed)
4. **[Block 4-5: TV Episode Parsing & Download Pipeline](docs/blocks/block-4-5-tv-episode-parsing-download-pipeline.md)** (Completed)

### Stage 2: The Revamped Web UI Cockpit (Phase 5) — IN PROGRESS
5. **[Block 5-1: Web UI Discovery & 3-Domain Switcher](docs/blocks/block-5-1-web-ui-discovery-domain-switcher.md)** (Completed)
   - Top-level `[Movies / TV / Classic TV]` switcher, trending/popular poster feeds, major vs indie tier filter, centered rich detail modal with theatrical windows & box office financials, live recent ingest activity sidebar, and full download history view.

6. **[Block 5-2: Web UI Search & ⚡ Lightning Cache Badging](docs/blocks/block-5-2-web-ui-search-lightning-badges.md)** — NEXT
   - Instant search modal/view connected to Prowlarr with real-time AllDebrid instant cache checks, glowing ⚡ badges, and cached sorting.
7. **[Block 5-3: Web UI Ingestion Modals & Telemetry](docs/blocks/block-5-3-web-ui-ingestion-modals-telemetry.md)**
   - 1-click Movie grabs, TV season/episode picker checklist modal, and live SSE download speed telemetry bar.

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
- **Classic TV**: `F:\temp\Classic TV` (`settings.tv_classic_output_dir`)

---

### Immediate Next Step for Resuming
- Prepare and implement **`docs/blocks/block-5-2-web-ui-search-lightning-badges.md`** (Phase 5: Web UI Search & ⚡ Lightning Cache Badging).
