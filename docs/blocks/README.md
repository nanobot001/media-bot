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
| **[Block 4-1](completed/block-4-1-domain-database-router.md)** | Domain Database Router | Completed | Add domain-aware SQLite routing for movies, anime, TV, and TV Classic while preserving existing movie behavior. |
| **[Block 4-2](completed/block-4-2-plex-section-domain-mapping.md)** | Plex Section Domain Mapping | Completed | Map Plex sections to media domains and prepare domain-routed sync behavior. |
| **[Block 5-1](block-5-1-anime-schema-plex-mirror.md)** | Anime Schema & Plex Mirror | Planned | Create anime show/season-or-arc/episode/special state and sync anime Plex sections into the anime DB. |
| **[Block 5-2](block-5-2-anime-factual-metadata.md)** | Anime Factual Metadata | Planned | Mirror Plex factual anime fields and define source-backed anime facts before LLM enrichment. |
| **[Block 5-3](block-5-3-anime-query-surface.md)** | Anime Query Surface & Structured Search | Planned | Query anime shows, episodes, specials, watched state, and factual fields with structured JSON citations. |
| **[Block 5-4](block-5-4-anime-regression-harness.md)** | Anime Regression Harness | Planned | Lock deterministic anime identity, alias, special, watched-state, and citation behavior before RAG. |
| **[Block 5-5](block-5-5-anime-typed-metadata-query-routing.md)** | Anime Typed Metadata & Query Routing | Planned | Add typed anime metadata and route exact factual questions through SQL-backed lookups before semantic search. |
| **[Block 5-6](block-5-6-anime-composite-embeddings.md)** | Anime Composite Embeddings | Planned | Generate metadata-rich anime embeddings and semantic retrieval while preserving structured-route precedence. |
| **[Block 5-7](block-5-7-anime-rag-ask.md)** | Anime RAG & Ask Support | Planned | Complete the Phase 5 MVP with anime show/episode answers grounded in citations. |
| **[Block 6-1](block-6-1-anime-search-source-routing.md)** | Anime Search Source Routing | Planned | Generalize Prowlarr source search to anime categories while preserving movie search compatibility. |
| **[Block 6-2](block-6-2-anime-episode-request-parser.md)** | Anime Episode Request Parser | Planned | Parse anime episode, special, absolute episode, whole-season, and season-pack requests into structured intents. |
| **[Block 6-3](block-6-3-anime-result-matching-dedupe.md)** | Anime Result Matching & Deduplication | Planned | Rank safe anime source candidates and reject wrong-show, wrong-episode, ambiguous, or already-owned matches. |
| **[Block 6-4](block-6-4-anime-file-selection-pack-handling.md)** | Anime File Selection & Pack Handling | Planned | Select episode, special, absolute episode, whole-season, or season-pack files from debrid manifests with ambiguity prompts. |
| **[Block 6-5](block-6-5-anime-download-confirmation-flow.md)** | Anime Download Confirmation Flow | Planned | Expose manual confirmation-first anime downloads through CLI, MCP, and Discord surfaces. |
| **[Block 6-6](block-6-6-anime-download-regression-harness.md)** | Anime Download Regression Harness | Planned | Lock dry-run, matching, dedupe, file-selection, privacy, and structured-error behavior for anime downloads. |
| **[Block 6-7](block-6-7-anime-download-mvp-integration.md)** | Anime Download MVP Integration | Planned | Complete the Phase 6 MVP with verified anime episode, special, absolute episode, whole-season, and season-pack enqueue flows. |
| **[Block 10-0](block-10-0-domain-specific-autonomous-monitors.md)** | Domain-Specific Autonomous Monitors | Future | Define opt-in movie release-window, anime cour, and continuing-TV watchlist monitors with dry-run-first safety gates. |
| **Block 10-1** | Monitor State Schema & Admin Tools | Future | Store monitor definitions, runs, candidates, ownership, cadence, and pause/delete controls without search behavior yet. |
| **Block 10-2** | Monitor Sweep Engine | Future | Add dry-run sweep lifecycle, cadence checks, quota checks, structured events, and mocked candidate plumbing. |
| **Block 10-3** | Movie Release-Window Monitor | Future | Weekly movie availability and quality-upgrade sweeps for wanted movies and external recommendations. |
| **Block 10-4** | Anime Cour Watchlist Monitor | Future | Seasonal/cour anime tracking, expected episodes, absolute numbering, release preferences, and batch checks. |
| **Block 10-5** | TV Continuing Show Monitor | Future | Active-show watchlists for new/missing episodes with ended-show pause behavior. |
| **Block 10-6** | Discord Review & Approval Flow | Future | Review cards, approve/reject/snooze/ignore controls, and approval handoff to the existing download path. |
| **Block 10-7** | Trusted Auto-Enqueue Rules | Future | Strict opt-in confidence gates, trusted indexers, per-domain caps, rollback/pause controls, and ambiguity fallback to approval. |

---

## 🤝 Block Guidelines

1. **Implement One Block at a Time**: Use the global `implement-block` skill. Do not write code for subsequent blocks until the active block is verified.
2. **Preserve JSON Envelopes**: Maintain strict separation of concerns; presentation layers must invoke the JSON tools, not execute raw adapter commands.
3. **Verify Every Step**: Write unit or integration tests for each block.
4. **Ship Phase MVPs**: Each roadmap phase must end with a demonstrable user-facing capability, not only internal plumbing.
5. **Reuse Movie Lessons**: New domains should follow staged enrichment ladders: schema, Plex facts, typed metadata, authority-backed facts, structured query routing, regression tests, composite embeddings, then RAG.
6. **Gate Autonomy**: Autonomous monitors are future opt-in behavior and must start as dry-run/monitor-only flows before any approval-required or trusted auto-enqueue mode.
