# Continue Here

## 2026-08-26

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
- **Stream readiness follow-up**: Implemented in the current worktree: authoritative pre-warm readiness for Discover, separate durable browser-stream and cached-download candidates per media record, browser-compatible cached-release selection for movies and TV, year-safe movie cache identity, resumable recent-to-1980 plus all-time-popularity movie pre-warm queues, and conservative browser audio/container gating.
- **Manual browser-copy follow-up**: Discovery keeps `Stream Now` disabled until verified and exposes `Cache Browser Copy` as an exact title/year browser-only acquisition path. Durable `cloud_transfer_intents` state limits Cloud Transfers and Notifications to manual Media Bot requests, while generic AllDebrid caching remains download-only and Search remains unrestricted.
- **Planned Phase 5 hardening sequence**: [Block 5-5](blocks/block-5-5-authoritative-browser-stream-verification.md) will use authoritative AD file evidence and bounded `ffprobe` fallback; [Block 5-6](blocks/block-5-6-adaptive-controlled-prewarming.md) will preserve existing frontiers while increasing movie throughput adaptively; [Block 5-7](blocks/block-5-7-browser-readiness-scoreboard-semantics.md) will make milestone progress count verified browser readiness. Implement and verify one block at a time in that order.
- **Verification**: 306 tests pass under Python 3.12 (excluding `tests/test_mcp_server.py`); only the existing 3 deprecation warnings remain.
- **Publication**: The foundation is committed as three scoped changes on `codex/stream-confirmation-gate`; keep `main` unchanged until this branch is separately reviewed and integrated.

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

### Stage 2A: Stream Readiness Hardening — PLANNED
9. **[Block 5-5: Authoritative Browser-Stream Verification](blocks/block-5-5-authoritative-browser-stream-verification.md)**
   - Inspect exact cached candidates using actual AD file evidence, bounded `ffprobe`, durable Search-to-Discovery promotion, and ownership-safe temporary cleanup.
10. **[Block 5-6: Adaptive Controlled Prewarming](blocks/block-5-6-adaptive-controlled-prewarming.md)**
   - Preserve all current vectors/cursors while adapting recent and all-time movie lanes between 10, 20, and 30 candidates.
11. **[Block 5-7: Browser-Readiness Scoreboard Semantics](blocks/block-5-7-browser-readiness-scoreboard-semantics.md)**
   - Keep existing milestone values but count only verified browser-ready records toward progress and frontier-to-go.

### Stage 3: Autonomous Background Engines (Post-UI Automation)
12. **[Block 4-6: TV Watchlist State & Storage](docs/blocks/block-4-6-tv-watchlist-storage.md)**
   - SQLite `tv_watchlist` repository (`watching`, `completed`, `archived`), `release_day` calendar schedules, and management tools.
13. **[Block 4-7: TV Mid-Season Backfill Engine](docs/blocks/block-4-7-tv-backfill-engine.md)**
    - Gap analysis using Plex episode inventory, full-backlog + granular per-episode backfill, reusable `resolve_missing_episodes` function, and dry-run safety.
14. **[Block 4-8: TV Airing Monitor & Auto-Archiving](docs/blocks/block-4-8-tv-airing-monitor.md)**
    - Autopilot sweep for newly aired episodes on broadcast days, automatic IDM queueing, finale detection, and auto-archiving.
15. **[Block 4-9: Weekly Release Discord Notifier & In-Line Ingest](docs/blocks/block-4-9-discord-weekly-digest.md)**
    - Discord digest reusing 4-3's discovery engine, interactive `⚡ Ingest` / `🚫 Ignore` buttons, and weekly cron.

---

### Staging Directories Reference
- **Movies**: `F:\_temp\movies` (`settings.output_dir`)
- **TV**: `F:\_temp\tv` (`settings.tv_output_dir`)
- **Classic TV**: `F:\temp\Classic TV` (`settings.tv_classic_output_dir`)

---

### Immediate Next Step for Resuming
- Confirm the remote `codex/stream-confirmation-gate` publication, then retain the branch for review. Live localhost API smoke passed after the PM2 restart; the in-app browser could not perform visual QA because its URL safety policy blocked localhost reload.
- Then implement **Block 5-5** only. Do not begin 5-6 until 5-5 passes its automated suite and ownership-guarded `Scary Movie` (2026) live canary; do not begin 5-7 until 5-6 is independently verified.
- After the Phase 5 hardening sequence is complete, **Block 4-6: TV Watchlist State & Storage** resumes as the next Stage 3 implementation block.
