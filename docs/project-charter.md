# Project Charter: Media Bot

This is the top-level authority and index for the `media-bot` project. All design, logic, architecture, database schemas, and block implementations flow from this document.

---

## 🎯 Purpose

`media-bot` is a modular, stateful, "tool-first" automation assistant for searching and reasoning over local media libraries, cross-referencing Plex state, deduplicating search listings, and orchestrating multi-stage high-speed downloads from AllDebrid to a native Windows Internet Download Manager (IDM) client.

The current production baseline is movie-first. The next roadmap expands the project into first-class, separately indexed media domains:

* `movies`
* `anime`
* `tv`
* `tv_classic`

Each domain should have its own local SQLite state, enrichment strategy, query/RAG surface, and download-search behavior while preserving the existing movie workflow as the stable baseline.

---

## 👥 Audience / Users

* **Home Server Administrators**: Users running Plex Media Server on local or LAN networks who want an automated, Discord-triggered mechanism to request, verify, and download media files without manually handling torrent files, magnet links, or browser-based downloaders.
* **Co-located Agents**: Agentic bots (like Codex or Antigravity) that need programmatic, deterministic JSON interfaces to search, check, and enqueue downloads.

---

## 🚀 Goals

1. **Tool-First Design**: Decouple business logic (searching, debrid interaction, file heuristics, Plex querying, enrichment, and RAG) from the Discord bot presentation layer. Every core operation is exposed as a functional, parameter-driven tool returning standardized JSON envelopes.
2. **Deterministic Deduplication**: Classify requested media against the active Plex-backed domain database using stable identifiers and conservative title matching to prevent duplicate downloads.
3. **Smart File Selection**: Implement regex-based heuristic pruning to discard sample clips and trailer videos from multi-file torrent sets, automatically resolving the main media file or prompting the user on size ambiguity. For anime and TV, this must evolve to support individual episodes, specials, absolute episode numbering, and season packs.
4. **Container-to-Host Download Delegation**: Support routing direct downloads from a Dockerized bot container to a native Windows IDM client using a lightweight local HTTP-bridge api.
5. **Multi-Library Intelligence**: Build separate, queryable local databases for movies, anime, TV, and TV Classic. Anime is the first non-movie implementation target; TV reuses the anime-proven series architecture; TV Classic receives selective deep episode enrichment for shows where episode-level discovery matters.

---

## 🚫 Non-Goals

* We do not support autonomous monitoring in the Phase 4-9 MVPs. Domain-specific autonomous monitors are a future opt-in capability after manual search/download, domain databases, and matching regression tests are reliable.
* We do not support unrestricted Sonarr/Radarr-style automatic grabs. Any future autonomous monitor must be domain-scoped, quota-limited, admin-visible, dry-run-first, and confidence-gated before trusted auto-enqueue is allowed.
* We do not implement native bittorrent client connections within the bot; all bittorrent activity is delegated to the AllDebrid caching service.
* **No File Migration**: We do not handle final file movement, organization, or renaming into the Plex directory tree. This is handled entirely by the separate, continuously running `media-watcher` script.

---

## 📦 MVP Definition

The original movie Minimal Viable Product consists of:
1. **Deduplication Engine**: Normalizing user search requests and comparing them to a Plex library mirror database.
2. **Search Tool**: Interfacing with Prowlarr to find category 2000 (Movies) torrent listings, obfuscating sensitive magnet URLs with temporary hash tokens.
3. **Enqueue Tool**: Uploading magnet URLs to AllDebrid, scanning the file manifest to find the main video file, unlocking the direct stream link, and sending it to IDM.
4. **Discord Gateway**: Initiating slash commands (`/search`, `/download`, `/check`, `/sync`, `/history`) with rich interactive Button & Dropdown views to handle file choices.
5. **IDM HTTP Bridge**: Running on the Windows host to accept queue requests from the container.

Future phases each have their own mini-MVP. A phase is complete only when it leaves behind a demonstrable user-facing capability, not just internal plumbing.

---

## ⚙️ Constraints

* **Host Environment**: Windows 10/11 with Internet Download Manager (IDMan.exe) installed.
* **Storage Location**: Media files must route to the path `F:\_temp\movies`.
* **Network boundaries**: Docker container running Python must route to the host IP `host.docker.internal` for Prowlarr and the IDM HTTP bridge.
* **Workflow Boundary**: The `media-bot` lifecycle for any media item ends as soon as the enqueued download successfully begins in IDM pointing to `F:\_temp\movies`. The separate `media-watcher` pipeline automatically processes completed items.
* **Runtime Deployment Models**:
  * **Native PM2 Mode (Preferred for Host Sync)**: Running continuously via PM2 using `pm2 start scripts/launcher.js --name media-bot`. The Node launcher acts as a child-process supervisor that forwards OS signal terminations (SIGINT/SIGTERM) to the underlying Python executable, preventing orphaned processes on Windows.
  * **Containerized Docker Mode**: Docker container running Python 3.12-slim with environment configurations loaded from a mounted `.env` file, referencing `host.docker.internal` to connect to Windows-side network boundaries.


---

## 🧭 Development Strategy

The development progresses via bounded implementation blocks. Each block builds on the tool-first foundations:
1. **Foundation & Scaffolding (Completed)**: Bootstrapped codebases, database models, CLI tools, unit tests, and adapter shells.
2. **Verification & Integration (Completed)**: Validating API connectivity, DB sync routines, and dry-run execution pipelines.
3. **Discord Gateway & Webhooks (Completed)**: Custom decorators, command restrictions, FastWebhooks, and Tautulli event logging.
4. **Active Jobs, Diagnostics, and Debrid API v4.1 (Completed)**: Background pending torrent resolution loops, PM2 process lifecycle management on Windows, and v4.1 API migration.
5. **Model Context Protocol Wrapper (Completed)**: FastMCP server registration mapping all core JSON tools.
6. **System Diagnostics and Observability Suite (Completed)**: Observability tools, FastAPI routes, CLI subcommands, slash commands `/status` & `/health`, and a full unit test suite.

* **Leverage Adjacent Tools**: Developers and agent systems are explicitly encouraged to inspect, reference, and reuse operational patterns and helper scripts from the neighboring `anime-pipe` directory to accelerate the AllDebrid/IDM integration.

### How the Blocks Deliver the MVP
The MVP is a containerized movie orchestration pipeline. The block progression ensures this is delivered systematically:
* **Block 00 & 01** establish the core database state mirror, Prowlarr indexing logic, and the IDM download delegation pathway.
* **Block 02** adds Discord commands interface, security checks, and logging capabilities.
* **Block 03** adds FastAPI event-driven syncing with Plex/Tautulli to keep the database mirror accurate.
* **Block 04-1** automates background torrent checking, AllDebrid querying, IDM delegation, and error reporting.
* **Block 05** exposes the tool interfaces to AI agent workflows using Model Context Protocol (MCP).
* **Block 06** completes the stack diagnostics and telemetry controls across API, CLI, and Discord command interfaces.

---

* **Phase 2: Local Media Intelligence, Semantic Search & Taste Profiling**: Evolve the Plex database mirror from a simple deduplication cache to a hybrid search and discovery engine. Extend the schema to store genres, directors, rating, runtime, collections, resolution, watch metrics, synopsis, metadata hashes, and versioned synopsis vector embeddings (generated for free via Gemini or locally via Ollama). Implement SQLite FTS5 for exact matching, cosine similarity in Python for zero-latency semantic search, a dry-run-safe intelligence backfill command, a taste-vector recommendation engine based on Tautulli logs, metadata-backed collection gap auditing with interactive sequel-search buttons in Discord (`/library`, `/recommend`, `/audit`), and conservative quality-upgrade checks.
* **Phase 3: Conversational RAG & Agentic Orchestration (Option B Integration)**: Layer conversational intelligence over the Phase 2 database using LLM integrations (Gemini, OpenAI, or local Ollama). Generate deep expert film profiles (craft, themes, director influences) and enable conversational chat/QA with a 2-stage retrieval pipeline (fast cosine-similarity matching of top candidates, followed by LLM-based conversational ranking/explaining).
  * *Constraint Mitigations*:
    * **Ollama Queue Guard**: Sequential or throttled concurrency execution to prevent freezing local LLM hosts.
    * **In-Memory Vector Cache**: Cache deserialized vectors in-memory to prevent SQLite bottlenecking on large libraries.
    * **Backoff & Progressive Saving**: Commit to DB after each movie enrichment and use exponential backoff retries for rate-limiting.
    * **JSON Schema Enforcement**: Use LLM structured output schemas and regex parsing fallbacks for clean JSON.
    * **Spoiler Isolation**: Segment plot summaries from thematic tags to ensure `--no-spoilers` queries stay leak-free.
* **Phase 4: Multi-Library Skeleton**: Realign the project roadmap around movies, anime, TV, and TV Classic. Add domain concepts, separate database routing, and Plex section-to-domain mapping while keeping movie behavior unchanged.
  * **MVP**: Movies still work; `anime`, `tv`, and `tv_classic` exist as configured domains with separate SQLite DB paths; Plex sections can map to domains; tool docs and block docs reflect the roadmap.
* **Phase 5: Anime Library Intelligence**: Implement anime first as the proving ground for reusable series/episode architecture. Build anime show/season-or-arc/episode/special state, Plex facts, typed enrichment, query routing, regression tests, composite embeddings, and RAG.
  * **MVP**: Anime syncs from Plex into its own DB and can answer show/episode questions with citations.
* **Phase 6: Anime Episode and Season Downloads**: Generalize Prowlarr search beyond movie category `2000`, starting with anime categories and anime-specific episode/season-pack handling.
  * **MVP**: Users can search/download anime episodes, specials, absolute episodes, or season packs with dry-run, confirmation, obfuscated magnet refs, structured errors, and JSON envelopes intact.
* **Phase 7: TV Reuse Pass**: Reuse the anime-proven series/episode architecture for the TV database. Add TV sync, factual metadata, typed enrichment, RAG, and episode/season download support.
  * **MVP**: TV is searchable, RAG-queryable, and downloadable by episode/season without becoming a second one-off architecture.
* **Phase 8: TV Classic Deep Episode Discovery**: Apply selective deep enrichment to classic shows where episode-level discovery is valuable, initially targeting shows such as `Cheers`, `Friends`, and `Modern Family`.
  * **MVP**: Selected classics can answer interesting episode-level questions about guest stars, holidays, bottle episodes, character focus, arcs, and notable moments with exact local episode citations.
* **Phase 9: Unified Media Assistant**: Add a route-aware `/ask` or `/media ask` that searches across movies, anime, TV, and TV Classic while citing the domain and item type.
  * **MVP**: One assistant can answer across all libraries while users can still force a domain when needed.
* **Phase 10: Domain-Specific Autonomous Monitors**: Add opt-in monitoring models tailored to each active media type instead of a generic Sonarr/Radarr clone.
  * **Movie Release-Window Monitor**: Weekly release-window sweeps for wanted movies, physical media, major VOD availability, and meaningful quality upgrades.
  * **Anime Cour Watchlist**: Seasonal anime tracking by cour, expected episode, absolute numbering, release-group/quality preference, and batch checks after cour completion. The adjacent `anime-pipe` project is treated as an early prototype source for cadence and release heuristics, not the final architecture.
  * **TV Continuing Show Watchlist**: Watch only active/incomplete TV shows for new or missing episodes, with ended-show pause behavior.
  * **TV Classic Exception**: Classic TV shows are generally complete, so they prioritize deep episode discovery instead of ongoing release monitoring, with only optional quality-upgrade monitoring if later needed.
  * **MVP**: Monitor-only dry-run sweeps can produce reviewable candidates with structured events, quotas, and admin controls; the Phase 10 MVP does not auto-download. Approval-required enqueue and trusted auto-enqueue are later hardening steps after strict confidence gates are proven.

### Lessons From Movie Intelligence Blocks

The movie implementation established reusable rules for every new domain:

* Use enrichment ladders, not giant enrichment blocks.
* Build durable schema before asking the LLM to reason over the domain.
* Mirror Plex facts before external facts.
* Use typed metadata early.
* Require authority-backed facts for hard claims such as guest stars, studios, source material, episode numbers, air dates, franchises, and awards.
* Route structured queries before semantic search.
* Add deterministic regression tests before trusting RAG.
* Build composite embeddings only after useful metadata exists.
* Keep every write/admin path dry-run-first, bounded, resumable, and event-logged.
* Keep existing movie tools as backward-compatible wrappers around future domain-aware tools.
* Treat autonomous behavior as a graduated ladder: manual search first, monitor-only review second, approval-required enqueue third, and trusted auto-enqueue only after regression-tested matching is reliable.



---

## 📂 Document Map

* `docs/architecture.md`: Detail of layer topologies, database schema structures, and routing loops.
* `docs/tool-contracts.md`: Standardized JSON envelopes, error handling guidelines, and input/output parameters.
* `docs/reuse-map-anime-pipe.md`: Analysis of regex and debrid parameters reused from the anime-pipe system.
* `docs/setup-guide.md`: Configuration steps for Dockerized Prowlarr indexing and local API connectivity.
* `docs/blocks/`: Individual markdown files detailing scoped, AI-buildable tickets.



