# Project Charter: Media Bot

This is the top-level authority and index for the `media-bot` project. All design, logic, architecture, database schemas, and block implementations flow from this document.

---

## 🎯 Purpose

`media-bot` is a modular, stateful, "tool-first" automation assistant for searching movie databases, cross-referencing local libraries (Plex), deduplicating search listings, and orchestrating multi-stage high-speed downloads from AllDebrid to a native Windows Internet Download Manager (IDM) client.

---

## 👥 Audience / Users

* **Home Server Administrators**: Users running Plex Media Server on local or LAN networks who want an automated, Discord-triggered mechanism to request, verify, and download media files without manually handling torrent files, magnet links, or browser-based downloaders.
* **Co-located Agents**: Agentic bots (like Codex or Antigravity) that need programmatic, deterministic JSON interfaces to search, check, and enqueue downloads.

---

## 🚀 Goals

1. **Tool-First Design**: Decouple business logic (searching, debrid interaction, file heuristics, Plex querying) from the Discord bot presentation layer. Every core operation is exposed as a functional, parameter-driven tool returning standardized JSON envelopes.
2. **Deterministic Deduplication**: Classify requested movies against the active Plex library using Levenshtein distance matching and IMDb ID validation to prevent duplicate downloads.
3. **Smart File Selection**: Implement regex-based heuristic pruning to discard sample clips and trailer videos from multi-file torrent sets, automatically resolving the main film file or prompting the user on size ambiguity.
4. **Container-to-Host Download Delegation**: Support routing direct downloads from a Dockerized bot container to a native Windows IDM client using a lightweight local HTTP-bridge api.

---

## 🚫 Non-Goals

* We do not support TV show batch downloading, folder syncing, or automated series tracking (which are handled better by Sonarr/Radarr).
* We do not implement native bittorrent client connections within the bot; all bittorrent activity is delegated to the AllDebrid caching service.
* **No File Migration**: We do not handle final file movement, organization, or renaming into the Plex directory tree. This is handled entirely by the separate, continuously running `media-watcher` script.

---

## 📦 MVP Definition

The Minimal Viable Product consists of:
1. **Deduplication Engine**: Normalizing user search requests and comparing them to a Plex library mirror database.
2. **Search Tool**: Interfacing with Prowlarr to find category 2000 (Movies) torrent listings, obfuscating sensitive magnet URLs with temporary hash tokens.
3. **Enqueue Tool**: Uploading magnet URLs to AllDebrid, scanning the file manifest to find the main video file, unlocking the direct stream link, and sending it to IDM.
4. **Discord Gateway**: Initiating slash commands (`/search`, `/download`, `/check`, `/sync`, `/history`) with rich interactive Button & Dropdown views to handle file choices.
5. **IDM HTTP Bridge**: Running on the Windows host to accept queue requests from the container.

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
* **Phase 4: Multi-User Curation & Quotas**: Add user request quotas, prioritized queue schedules, and administrator approval panels in Discord.
* **Phase 5: Advanced Media-Watcher Orchestrator Integration**: Enable bidirectional status polling. The bot can check `media-watcher` logs or progress cues to notify Discord users when their enqueued movie has finished migrating into Plex.



---

## 📂 Document Map

* `docs/architecture.md`: Detail of layer topologies, database schema structures, and routing loops.
* `docs/tool-contracts.md`: Standardized JSON envelopes, error handling guidelines, and input/output parameters.
* `docs/reuse-map-anime-pipe.md`: Analysis of regex and debrid parameters reused from the anime-pipe system.
* `docs/setup-guide.md`: Configuration steps for Dockerized Prowlarr indexing and local API connectivity.
* `docs/blocks/`: Individual markdown files detailing scoped, AI-buildable tickets.



