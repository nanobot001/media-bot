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
2. **Verification & Integration (Current)**: Validating API connectivity, DB sync routines, and dry-run execution pipelines.
3. **Webhook Notifications (Planned)**: Hooking Tautulli stream watch events to trigger automatic library syncs.
4. **Cleanup & Disk Guard (Planned)**: Automatic tracking of space on `F:\_temp\movies` to warn or prune old media files.

* **Leverage Adjacent Tools**: Developers and agent systems are explicitly encouraged to inspect, reference, and reuse operational patterns and helper scripts from the neighboring `anime-pipe` directory to accelerate the AllDebrid/IDM integration.

### How the Blocks Deliver the MVP
The MVP is a containerized movie orchestration pipeline. The block progression ensures this is delivered systematically:
* **Block 00 & 01** establish the core database state mirror, Prowlarr indexing logic, and the IDM download delegation pathway.
* **Block 02** adds event-driven syncing to keep the database mirror accurate without manual runs.
* **Block 03** ensures the destination disk (`F:\_temp\movies`) does not overflow, adding host-safe cleanup policies.
* **Block 04** secures and wraps the system in Discord commands (`/search`, `/check`, `/sync`) with select menus.

---

## 🔮 Future Phases

* **Phase 2: Agentic Orchestration (Model Context Protocol)**: Package the tools as an MCP Server. This allows local AI agents (like Codex or Antigravity) to query active streams, check libraries, and manage storage directories autonomously.
* **Phase 3: Multi-User Curation & Quotas**: Add user request quotas, prioritized queue schedules, and administrator approval panels in Discord.
* **Phase 4: Advanced Media-Watcher Orchestrator Integration**: Enable bidirectional status polling. The bot can check `media-watcher` logs or progress cues to notify Discord users when their enqueued movie has finished migrating into Plex.
* **Phase 5: Unified Media Intelligence Layer (Plex-RAG Evolution)**: Evolve the Plex database mirror from a simple deduplication cache to a centralized authoritative metadata store. Layer SQLite FTS5 search, vector embeddings (Qdrant), and conversational agents/tools (e.g., `plex.recommend_owned`, `plex.search_owned`) to reason over the user's complete library, watch history, and download queue for unified discovery and acquisition.


---

## 📂 Document Map

* `docs/architecture.md`: Detail of layer topologies, database schema structures, and routing loops.
* `docs/tool-contracts.md`: Standardized JSON envelopes, error handling guidelines, and input/output parameters.
* `docs/reuse-map-anime-pipe.md`: Analysis of regex and debrid parameters reused from the anime-pipe system.
* `docs/setup-guide.md`: Configuration steps for Dockerized Prowlarr indexing and local API connectivity.
* `docs/blocks/`: Individual markdown files detailing scoped, AI-buildable tickets.



