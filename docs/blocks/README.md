# Blocks Index: Media Bot

This folder contains numbered, bounded, and verifiable tickets for developing the `media-bot` MVP.

---

## 📋 Block Status Index

| Block ID | Title | Status | Main Deliverables |
| :--- | :--- | :--- | :--- |
| **[Block 00](completed/block-00-project-definition.md)** | Project Definition | Done | Charter, design principles, and locked rules. |
| **[Block 01](completed/block-01-integration-verification.md)** | Integration Verification | Done | Automated validation checks and API token configurations. |
| **[Block 02](completed/block-02-discord-gateway.md)** | Discord Gateway | Done | Slash commands registration, channel constraints, status cards. |
| **[Block 03](completed/block-03-tautulli-webhooks.md)** | Tautulli Webhooks | Done | Webhook receiver to sync library on media events. |
| **[Block 04](completed/block-04-space-management.md)** | Space Management Guard | Deprecated | Disk monitor with auto-cleanup of watched files (Handled by external media-watcher). |
| **[Block 04-1](completed/block-04-1-jobs-and-diagnostics.md)** | Active Jobs & Diagnostics | Completed | Job tracking, debrid resolver background loop, error log inspector. |
| **[Block 05](completed/block-05-mcp-integration.md)** | MCP Server Wrapper | Completed | Exposing tools to AI agents using Model Context Protocol. |
| **[Block 06](completed/block-06-system-diagnostics.md)** | System Diagnostics | Completed | Observability tools, FastAPI telemetry routes, slash commands `/status` & `/health`, unit tests. |
| **[Block 07](completed/block-07-discord-observability-matchdoctor.md)** | Discord Match Doctor | Completed | Mismatch Guard engine, Plex rematching API, interactive Discord repair UI, `/debug` command. |
| **[Block 08](completed/block-08-pipeline-status-card.md)** | Pipeline Status Card | Done | Live Discord status card tracking each download across Debrid → IDM → media-watcher → Plex. |
| **[Block 2-1](completed/block-2-1-library-schema-fts5.md)** | Media Intelligence Schema & FTS5 | Completed | SQLite schema migrations, trigger-backed FTS5 virtual tables, metadata hashing, and dry-run intelligence backfill. |
| **[Block 2-1b](completed/block-2-1b-quality-upgrade-dedupe.md)** | Quality Upgrade Deduplication | Completed | Conservative quality-upgrade allowance while preserving duplicate protection. |
| **[Block 2-2](completed/block-2-2-embeddings-similarity.md)** | Vector Embedding & Similarity Engine | Completed | Google Gemini / local Ollama embedding retrieval with caching, and cosine-similarity math. |
| **[Block 2-3](completed/block-2-3-recommendation-taste-vector.md)** | Taste Recommender & Collection Audit | Completed | Tautulli statistics taste vectors, cosine-similarity recommendations, and series gap auditing. |
| **[Block 2-4](completed/block-2-4-discord-library-interface.md)** | Unified Discord & MCP Interface | Completed | `/library`, `/recommend`, and `/audit` Discord commands with gap search buttons, MCP tools, and CLI subcommands. |
| **[Block 2-5](completed/block-2-5-structured-enrichment-metadata.md)** | Structured Enrichment Metadata | Completed | Evidence-backed setting, premise, character, theme, tone, craft, and content-warning metadata for factual and descriptive library queries. |
| **[Block 2-6](completed/block-2-6-typed-enrichment-metadata-v2.md)** | Typed Enrichment Metadata v2 | Completed | Typed story/event locations, central/minor themes, dominant/secondary tone, craft facets, and depicted/discussed content-warning helper fields. |
| **[Block 2-7](completed/block-2-7-gemini-enrichment-source.md)** | Gemini Enrichment Source | Completed | Optional Gemini metadata generation for the typed enrichment v2 contract, with rule fallback and dry-run-first sync behavior. |
| **[Block 2-8](completed/block-2-8-plex-factual-discovery-fields.md)** | Plex Factual Discovery Fields | Completed | Plex-backed studios, writers, producers, cast, countries, content rating, audience rating, tagline, release date, and labels. |
| **[Block 2-9](completed/block-2-9-hard-fact-discovery-fields.md)** | Hard-Fact Discovery Fields | Completed | Sourced awards, source material, popularity, cultural impact, and query routing fields for future authority-backed enrichment. |
| **[Block 2-10](completed/block-2-10-authority-backed-hard-fact-population.md)** | Authority-Backed Hard-Fact Population | Completed | Dry-run-first coverage audit and sourced population of awards, source material, popularity, and cultural impact facts. |
| **[Block 2-11](completed/block-2-11-tmdb-brand-franchise-enrichment-regression.md)** | TMDb Franchise & Brand Enrichment Regression | Completed | TMDb-backed franchise, brand, universe, and source-property facts with a deterministic semantic regression harness. |
| **[Block 2-12](completed/block-2-12-enriched-search-embeddings.md)** | Enriched Search Embeddings & Backfill | Completed | Composite search document embeddings (Title + Genres + Tones + Themes + Synopsis) to eliminate subjective search false-positives. |
| **[Block 3-0](completed/block-3-0-rag-infrastructure.md)** | RAG Infrastructure & Caching | Completed | Unified Gemini client, query TTL cache, and compact movie metadata serialization. |
| **[Block 3-1](completed/block-3-1-conversational-rag.md)** | Conversational Library RAG & Ask Command | Completed | Two-stage retrieval RAG pipeline (semantic retrieval + LLM reranking/explanation) for Discord, CLI, and MCP. |
| **[Block 3-2](completed/block-3-2-ai-user-working-memory.md)** | AI User Working Memory & Plex Mapping | Completed | User profiles, Plex account mapping, interactive profile modal, user query logs. |
| **[Block 3-3](completed/block-3-3-external-recommendations.md)** | External Parametric Recommendations | Completed | Suggesting external non-db movies, TMDb safety gates, interactive Search & Add buttons. |
| **[Block 3-3b](completed/block-3-3b-persona-settings.md)** | Persona Settings & Conversational History | Completed | Persistent custom RAG personas, slash commands, MCP tools, and scaled memory limits. |
| **[Block 3-4](completed/block-3-4-multi-user-context-privacy.md)** | Multi-User Context & Privacy Guards | Completed | Multi-user thread log parsing, local privacy interception, joint recommendation sessions. |
| **[Block 3-5](completed/block-3-5-rich-tautulli-playback-notifications.md)** | Rich Tautulli Playback Notifications | Completed | Session-aware Discord playback cards for Tautulli start/stop/watched events without full TV/anime domain sync. |
| **[Block 4-0](completed/block-4-0-roadmap-charter-multi-library-realignment.md)** | Roadmap & Charter Multi-Library Realignment | Completed | Lock anime, TV, and TV Classic as first-class domains with phase MVPs and movie-derived implementation rules. |
| **[Block 4-1](completed/block-4-1-domain-database-router.md)** | Domain Database Router | Completed | Add domain-aware SQLite routing for movies, TV, and TV Classic while preserving existing movie behavior. |
| **[Block 4-2](completed/block-4-2-plex-section-domain-mapping.md)** | Plex Section Domain Mapping | Completed | Map Plex sections to media domains and prepare domain-routed sync behavior. |
| **Stage 1** | **Interactive Foundation** | *Completed* | *Backend tools required for Web UI browsing and 1-click downloading.* |
| **[Block 4-3](block-4-3-discovery-engine-tmdb-tv.md)** | Discovery Engine & TMDb TV Extension | Completed | Unified domain-parameterized discovery tool (Movies, TV, Classic TV) with TMDb TV endpoints, library dedup, and era/network filters. |
| **[Block 4-3b](block-4-3b-tv-plex-library-sync.md)** | TV & Classic TV Plex Library Sync & Mirror | Completed | Mirror Plex TV and Classic TV sections into `tvbot.sqlite3` and `tvclassicbot.sqlite3` with show and episode inventories. |
| **[Block 4-4](block-4-4-tv-search-category-routing.md)** | TV Prowlarr Search & Category Routing | Completed | Generalize Prowlarr adapter for Category 5000 (TV), structured season/episode query parsing, and token caching. |
| **[Block 4-5](block-4-5-tv-episode-parsing-download-pipeline.md)** | TV Episode Parsing & Download Pipeline | Completed | SxxExx manifest parsing, batch AllDebrid unlock, batch IDM enqueue, and 3-way destination folder routing (`F:\_temp\movies`, `F:\_temp\tv`, `F:\temp\Classic Tv`). |
| **Stage 2** | **The Revamped Web UI Cockpit** | *Completed* | *Interactive 3-domain browser cockpit with ⚡ Lightning badges and 1-click downloads.* |
| **[Block 5-1](block-5-1-web-ui-discovery-domain-switcher.md)** | Web UI Discovery & 3-Domain Switcher | Completed | Top-level `[Movies / TV / Classic TV]` switcher and trending/popular poster feeds with filter pills. |
| **[Block 5-2](block-5-2-web-ui-search-lightning-badges.md)** | Web UI Search & ⚡ Lightning Cache Badging | Completed | Prowlarr search integration with real-time AllDebrid instant cache checks and glowing ⚡ badges. |
| **[Block 5-3](block-5-3-web-ui-ingestion-modals-telemetry.md)** | Web UI Ingestion Modals & Telemetry | Completed | 1-click Movie grabs, TV season/episode picker modal, and live SSE download speed telemetry bar. |
| **[Block 5-4](block-5-4-web-ui-instant-cloud-streaming.md)** | Web UI Instant Cloud Streaming & Media Player | Completed | In-browser player modal and 1-click VLC/Infuse streaming for instant-cached AllDebrid releases. |
| **Stage 2A** | **Stream Readiness Hardening** | *In Progress* | *Authoritative AD file verification, browser-transcoding qualification, adaptive popular-catalog coverage, and honest browser-readiness milestones.* |
| **[Block 5-5](block-5-5-authoritative-browser-stream-verification.md)** | Authoritative Browser-Stream Verification | Completed | Probe cached exact-identity candidates from AD file evidence, use bounded `ffprobe` fallback, persist Search verification, and protect existing AD entries. |
| **[Block 5-5b](block-5-5b-mediaflow-browser-transcoding-capability-pilot.md)** | MediaFlow Browser Transcoding Capability Pilot | Implemented with limitations | `adopt_with_bounded_adapter` for the localhost pilot; safe HLS fallback, NVENC transcode, fixture playback, seeking, and subtitle checks recorded. |
| **[Block 5-5d](block-5-5d-universal-movie-quality-gate.md)** | Universal Movie Release-Window Quality Gate | Implemented | Enforce the authoritative movie release-date gate across discovery, search, ranking, pre-warming, cache, ingest, and playback; retain a separate TV follow-up plan. |
| **[Block 5-5e](block-5-5e-durable-prewarm-runtime-ledger.md)** | Durable Prewarm Runtime Ledger | Implemented | Persists cycle lifecycle and next-run evidence, recovers safely across PM2 restarts, decouples scheduling from Plex sync, prevents overlap, and exposes the latest ten cycles in the UI. |
| **[Block 5-5f](block-5-5f-release-variant-availability-catalog.md)** | Release-Variant Availability Catalog | Implemented | Preserves multiple exact variants per media scope, migrates legacy cache evidence conservatively, and derives canonical unknown/A/B/C state while keeping MediaFlow separate from direct-play C. |
| **[Block 5-5g](block-5-5g-catalog-population-provider-truth.md)** | Catalog Population & Provider-Check Truth | Implemented | Populate all bounded exact variants from Search/prewarm, retain cycle/source history, distinguish uncached from unknown/provider errors, and expose reconciled cycle counts. |
| **[Block 5-5h](block-5-5h-unified-availability-projection.md)** | Unified Availability Projection | Planned | Make Discovery, Search, pre-warm APIs, CLI, MCP, and UI expose one catalog-derived state with canonical domain and TV scope. |
| **[Block 5-5c](block-5-5c-mediaflow-production-browser-adapter.md)** | MediaFlow Production Browser-Stream Adapter | Planned after 5-5e–5-5h | Route an exact cached catalog variant through MediaFlow while direct play remains C, with a minimal cached-version selector and reversible rollout. |
| **[Block 5-6](block-5-6-adaptive-controlled-prewarming.md)** | Adaptive Controlled Prewarming | Planned | Preserve frontier vectors while scaling movie lanes adaptively to 10/20/30 targets with bounded deep verification. |
| **[Block 5-7](block-5-7-browser-readiness-scoreboard-semantics.md)** | Browser-Readiness Scoreboard Semantics | Planned | Preserve milestone values while basing progress and frontier-to-go on verified browser-ready records. |

| **Stage 3** | **Autonomous Background Engines** | *Planned* | *Post-UI background automation daemons, backfill, daily sweeps, and Discord digests.* |
| **[Block 4-6](block-4-6-tv-watchlist-storage.md)** | TV Watchlist State & Storage | Planned | SQLite `tv_watchlist` repository (`watching`, `completed`, `archived`), `release_day` calendar schedules, and management tools. |
| **[Block 4-7](block-4-7-tv-backfill-engine.md)** | TV Mid-Season Backfill Engine | Planned | Gap analysis using Plex episode inventory, full-backlog + granular per-episode backfill, and dry-run safety. |
| **[Block 4-8](block-4-8-tv-airing-monitor.md)** | TV Airing Monitor & Auto-Archiving | Planned | Anime-pipe style autopilot sweep for newly aired episodes on broadcast days, automatic IDM queueing, finale detection, and auto-archiving. |
| **[Block 4-9](block-4-9-discord-weekly-digest.md)** | Weekly Release Discord Notifier & In-Line Ingest | Planned | Discord digest reusing 4-3's discovery engine, interactive `⚡ Ingest` / `🚫 Ignore` buttons, and weekly cron. |
| *Anime Blocks (6-1 to 7-7)* | *Anime Library & Downloads* | *Deprecated* | *Delegated to the dedicated `anime-pipe` ecosystem. Archived in `docs/blocks/deprecated/`.* |

---

## 🤝 Block Guidelines

1. **Implement One Block at a Time**: Use the global `implement-block` skill. Do not write code for subsequent blocks until the active block is verified.
2. **Preserve JSON Envelopes**: Maintain strict separation of concerns; presentation layers must invoke the JSON tools, not execute raw adapter commands.
3. **Verify Every Step**: Write unit or integration tests for each block.
4. **Ship Phase MVPs**: Each roadmap phase must end with a demonstrable user-facing capability, not only internal plumbing.
5. **Reuse Movie Lessons**: New domains should follow staged enrichment ladders: schema, Plex facts, typed metadata, authority-backed facts, structured query routing, regression tests, composite embeddings, then RAG.
6. **Gate Autonomy**: Autonomous monitors are future opt-in behavior and must start as dry-run/monitor-only flows before any approval-required or trusted auto-enqueue mode.
