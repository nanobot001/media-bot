# Movie Media Bot 🎬

A modular, stateful, tool-friendly Discord bot ecosystem that automates movie searching, local media library cross-referencing, and multi-stage download handoffs.

---

## 🚀 System Architecture & Setup

This system runs natively on **Windows** with support services containerized:
1.  **Discord Bot / APIs (`movie-media-bot`):** Runs natively on the Windows host using Python 3.12, managed by PM2. Launches the Discord bot client and the FastAPI webhook listener concurrently on port `8000`.
2.  **Prowlarr (Docker):** Runs inside Docker on `http://127.0.0.1:9696`.
3.  **FlareSolverr (Docker):** Solves Cloudflare challenges automatically for Prowlarr indexers on `http://127.0.0.1:8191`.
4.  **Tautulli (Plex Activity):** Pushes stream playback activity notifications (start, stop, watched) directly to the FastAPI webhook endpoint.
5.  **Internet Download Manager (IDM):** Runs natively on the Windows host.
6.  **IDM Bridge:** A lightweight PowerShell REST server running natively on the host on port `8765`.

### 1. Host Configuration
Copy `.env.example` to `.env` and fill in the required API keys and secrets (Discord, AllDebrid, Prowlarr, Plex, and Tautulli Webhook Secret).

### 2. Launching the Support Services (Docker)
Ensure Docker is running, then boot the Prowlarr and FlareSolverr services:
```powershell
docker-compose up -d
```

### 3. Launching the Discord Bot & Webhook Server (PM2)
The bot runs natively on the Windows host under PM2:
```powershell
pm2 start scripts/launcher.js --name "media-bot"
```
This boots both the Discord Bot Gateway and the FastAPI Webhook Receiver listening on port `8000`.

### 4. Launching the IDM Host Bridge
On the Windows host, execute the IDM listener script:
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run_idm_bridge.ps1
```

---

## 💬 Discord Slash Commands

The following commands are available inside permitted Discord channels:
*   `/help`: Show a list of available commands, pipeline guide, and role-based command reference.
*   `/search [query]`: Search Prowlarr indexers for torrents/magnets.
*   `/check [title] [year]`: Dry-run deduplication engine evaluation against the library database.
*   `/sync`: Manually sync the local database mirror with the Plex server. Filters ignored sections and prunes deleted records.
*   `/library [query] [genre] [director] [resolution] [rating_above] [watch_status] [limit]`: Search or browse the movie library. Supports standard filters, semantic query search (e.g., "space travel"), and visualizes inferred routing filters, canonical TMDb franchise/brand tags, and tagline/synopsis previews.
*   `/movie [title] [year]`: Show a detailed database card for one movie, including TMDb poster image, synopsis, core metadata, library quality details, cast/crew, brand/franchise/universe tags in the enrichment section, hard facts, and provenance fields.
*   `/ask [question]`: Ask natural language questions about your library (e.g., *"What sad dramas from the 90s do I have?"* or *"What should I add next?"*). Returns a conversational RAG answer citing matching library items. When asking for additions, the bot suggests external movies not yet in your library with `🔍 Search & Add` buttons for one-click download (with a confirmation step).
*   `/profile show`: Show and manage your profile settings (Plex username mapping, manual taste overrides, atomic memories, and visibility settings) interactively.
*   `/recommend`: Request personalized movie recommendations based on Tautulli watch history profiles and vector similarity.
*   `/audit`: Audit movie collections to identify missing sequel or prequel gaps. Displays interactive buttons to instantly search Prowlarr/download.
*   `/history [user] [title] [limit]`: Query user watch history from Tautulli logs.
*   `/download [url]`: Send a direct magnet link or torrent URL to debrid and IDM.
*   `/jobs [active_only] [limit]`: View active or recent download queue status.
*   `/status [title]`: View the live pipeline status card for a download job (debrid, download, filebot, plex).
*   `/resolve [dry_run]`: Manually trigger a resolution sweep on pending magnet links.
*   `/errors [limit]` *(Bot Managers Only)*: List recent runtime command exception log reports.
*   `/health` *(Bot Managers Only)*: Expose stack connectivity, process metrics, and disk spaces.
*   `/events [limit]` *(Bot Managers Only)*: Retrieve recent SQLite event log entries.
*   `/logs <source> [lines]` *(Bot Managers Only)*: Tail logs for a named source (`watcher`, `bot-out`, `bot-err`).
*   `/debug <rating_key>` *(Bot Managers Only)*: Manually run Mismatch Guard audit/fix on a Plex rating key.
*   `/persona [show|set|reset]` *(Bot Managers Only)*: View, set, or reset the custom system-instruction database override persona for conversational queries.


---

## 🔄 Ingestion Pipeline & Status Cards

Whenever a movie download is initiated via `/search` selection or `/download <url>`, the bot creates a dynamic, interactive status card in Discord and starts tracking its progression across 5 distinct pipeline stages:

```text
Ingestion Pipeline: Predator Badlands (2025)
Debrid Cache       | 🟢 Completed
Downloading (IDM)  | 🟡 Active (45.3% [████░░░░░░])
Intake & Stabilize | ⚪ Waiting
FileBot Import     | ⚪ Waiting
Plex Library       | ⚪ Waiting
Elapsed Time       | ⏱️ 4m 12s (▰▰▰▰)
```

### The 5 Pipeline Stages
1. **Debrid Cache (`debrid`)**: 
   * **Purpose:** Downloads torrent metadata and resolves download URLs.
   * **Action:** Checks if the torrent is cached on AllDebrid. If not cached, the bot waits for AllDebrid to finish downloading the torrent.
2. **Downloading (IDM) (`downloading`)**: 
   * **Purpose:** Downloads the high-speed file from AllDebrid to local storage.
   * **Action:** Communicates via the IDM Host Bridge to queue and download the file onto the Windows server using Internet Download Manager.
3. **Intake & Stabilize (`in_folder`)**: 
   * **Purpose:** Ensures the file is fully written before processing.
   * **Action:** `media-watcher` detects the file in the completed folder and monitors its size. Once the file size remains identical between polls, it is marked as stable.
4. **FileBot Import (`filebot`)**: 
   * **Purpose:** Handles naming hygiene and Plex file placement.
   * **Action:** Runs FileBot automatically to match, rename, and copy/move the completed movie file into the appropriate Plex library folder.
5. **Plex Library (`plex`)**: 
   * **Purpose:** Updates your streaming library and completes the lifecycle.
   * **Action:** Triggers a Plex section refresh and verifies that Plex successfully matched and indexed the media metadata.

### Interactive Features & Lifecycle
* **🔄 Manual Refresh Button:** Under each card, users can press the `🔄 Refresh` button to force an immediate, real-time query of the pipeline status.
* **⏱️ Activity Ticks (`▰`):** The card displays elapsed time. As the job runs, a progress character (`▰`) is appended for each minute of active run time to visually indicate that the process is moving.
* **🤖 Automatic Updates:** A background worker loop in the bot sweeps active jobs every 60 seconds (configurable) and automatically edits the Discord cards with progress bars and stage updates.
* **🧹 Terminal Transition:** Once a status card reaches `Plex Library` (success) or `Error` (failure), the background updater stops sweeping it and flags it as complete to conserve API limits.

### 🧠 Intelligent Ingestion
When media-bot downloads reach Plex, or when Tautulli reports a Plex library event, the bot triggers an immediate intelligent sync:
* **Rich Metadata Enrichment:** The bot queries Plex to retrieve the movie's full metadata (genres, directors, runtime, rating, and synopsis).
* **On-the-Fly Semantic Embeddings:** The bot automatically calls the Gemini API (gemini-embedding-001) to generate a semantic vector embedding of a **metadata-enriched composite search document** (combining Title, Year, Genres, Tones, Themes, and Synopsis). This is stored in the SQLite database along with a deterministic composite hash to prevent unnecessary API calls and support automatic cache invalidation when metadata updates.
* **Auto-Audits:** Runs a similarity check via MismatchGuard to ensure Plex correctly matched the movie's title and alerts administrators in Discord of any mismatches.
* **Pipeline Enrichment Card:** For movies downloaded through media-bot, reaching `Plex Library` is enough to post the rich **New Movie Added** card. Tautulli is still useful for movies added outside media-bot, but is not required for downloaded-movie enrichment cards.

This ensures the SQLite database is always a complete, authoritative, semantically-indexed mirror of your library.

### 🏆 Authority-Backed Hard-Fact Enrichment
To maintain data integrity and prevent LLM hallucinations, the library enrichment pipeline implements a **Hybrid Smart-Merge Strategy**:
* **Wikidata Integration First:** When enriching, the system queries the Wikidata REST API for authoritative factual data: awards, nominations, source materials, box office earnings, and collection franchises.
* **Plex Curation Overrides:** Curated Plex collections and custom labels (e.g. Classic, Cult Classic) take priority over machine-inferred labels.
* **LLM Gap Filling:** The Gemini API (gemini-1.5-flash) is used as a fallback to infer missing soft tags (themes, tones, premises, and settings) and popular/cultural footprint details only when Wikidata/rules return empty datasets.
* **Per-Field Provenance Tracking:** Every record documents its source origin (rules, gemini_fallback, or rules+gemini) inside hard_fact_sources_json for complete auditability.

#### Auto-Enrichment & Notifications
When a media-bot download reaches Plex, the pipeline worker initiates an async auto-enrichment worker (provider=gemini). Tautulli library-add webhooks can still trigger the same path for movies added outside media-bot. Once complete, the bot publishes a rich **New Movie Added** summary card in Discord showing:
* Core metadata (rated, runtime, rating, genres, studios).
* Curated tags: Themes, Tone, Premise, Setting, Awards, Source Material, Popularity, and Content Warnings.
* A footer indicating exactly which engines were used to resolve the facts and tags (e.g. Enrichment: gemini | Facts: wikidata).
Duplicate-post guards prevent the pipeline and webhook triggers from posting the same movie card twice.

---

### 🧠 Conversational Library RAG (v1.4.0)

Media Bot features an advanced two-stage Retrieval-Augmented Generation (RAG) system for conversational library search:
* **Stage 1 (Retrieval):** Performs a local semantic search over your library's composite vector embedding database, filtering candidate movies down to the top 15-20 most relevant matches.
* **Stage 2 (LLM Explanation & Reranking):** Passes the pruned metadata of the candidates to Google Gemini (using token-efficient minification), which selects the best 3-5 matches and writes a concise explanation answering the user's question.
* **TTL Caching:** Conversational queries are cached in a thread-safe TTL cache (`RAGQueryCache`) for 5 minutes, preventing redundant Gemini API calls.

---

### 🎬 External Recommendations (v1.5.2)

When you ask *"what should I add next?"* or *"recommend something I don't have"*, the bot shifts into external suggestion mode:

* **LLM-Powered Suggestions:** Gemini generates external movie recommendations outside your library using parametric knowledge.
* **Ownership Gate (Zero Token Cost):** Before any suggestion surfaces, the bot runs the existing multi-tier deduplication engine (`evaluate_deduplication`) against your library — exact title+year match, plus fuzzy Levenshtein scoring — to silently discard anything you already own. No library manifest is injected into the prompt.
* **Content Safety Gate:** Each suggestion is verified against TMDb for content rating. Titles exceeding your profile's `max_content_rating` are filtered out automatically.
* **Genre Exclusion Gate:** Suggestions matching your `excluded_genres` profile list are dropped.
* **Search & Add Flow:** Approved suggestions appear with a `🔍 Search & Add: [Title]` button. Clicking it prompts a Yes/No confirmation before triggering a Prowlarr search, preventing accidental downloads.

---

### 👤 User Profiles & Memory (v1.5.0)

The bot maintains user profiles mapping Discord accounts to Plex watch histories:
* **Account Mapping:** Set your Plex/Tautulli username in your profile to link your playback history.
* **Organic Memory Extraction:** As you ask questions and interact with the bot, it uses Gemini to detect and extract atomic facts about your tastes (e.g., *"Likes Canadian indie movies"*, *"Hates gore"*).
* **Taste Customization:** Manually configure taste overrides and profile visibility settings using the interactive `/profile show` menu.
* **Personalized RAG:** The conversational RAG engine automatically retrieves and compiles your active taste preferences to personalize recommended outcomes.

---

## 🔌 Model Context Protocol (MCP) Integration

The bot runs a Model Context Protocol (MCP) server that allows LLM agents (like Claude Desktop or other client systems) to query and interact with the library. 

To start the MCP server:
```powershell
python -m moviebot.cli.mcp_server
```

### Available Tools Exposed via MCP:
* `query_library`: Exact filter, FTS5 match, and semantic similarity search over library items.
* `ask_library`: Converse with the movie library using natural language questions (Conversational RAG).
* `recommend_movies`: Personalised movie recommendations using watch history taste vectors.
* `audit_collections`: Detect missing sequel/prequel gaps in movie franchises.
* `check_movie_state`: Audit system state for a movie (Plex, downloads, IDM, folders, and logs).
* `get_download_jobs`: Retrieve active or historical download jobs.
* `enqueue_download`: Download torrent/magnet links via Prowlarr, AllDebrid, and IDM.
* `resolve_pending_jobs`: Sweeps and resolves pending downloads.
* `get_system_health`: PM2 process status, disk spaces, and API connectivity.
* `get_recent_events` / `tail_logs`: View diagnostic event entries and log outputs.

---

## 🛠️ Developer Interface (CLI Tool)

For administrative operations, debugging, or running as a tool directly from terminal:
```powershell
# Run configuration and path check tests
python -m moviebot.cli.tool_cli configtest

# Trigger database synchronization sweeps
python -m moviebot.cli.tool_cli sync-library

# Backfill metadata details and embeddings from Plex and Gemini
python -m moviebot.cli.tool_cli sync-intelligence --no-dry-run

# Run the database-wide composite embedding backfill (creates auto backup)
.\scripts\run-embeddings-backfill.ps1

# Query/search the library using FTS or semantic search via CLI
python -m moviebot.cli.tool_cli query-library --query "space travel" --genre "Sci-Fi" --limit 5

# Ask natural language questions about your library using conversational RAG
python -m moviebot.cli.tool_cli ask --question "What space movie do I have similar to Interstellar?"

# Get recommendations via taste profiler on the CLI
python -m moviebot.cli.tool_cli recommend

# Audit collections for gaps via CLI
python -m moviebot.cli.tool_cli audit-collections

# Manually test the deduplication engine
python -m moviebot.cli.tool_cli dedupe --title "The Matrix: Resurrections (2021)!!" --year 2021

# List active or recent download jobs
python -m moviebot.cli.tool_cli jobs --all --limit 10

# Manually trigger pending torrent resolution sweep
python -m moviebot.cli.tool_cli resolve-pending --dry-run

# Inspect recent diagnostic error logs
python -m moviebot.cli.tool_cli errors --limit 10

# Query recent system events from SQLite table
python -m moviebot.cli.tool_cli events --limit 10

# Tail system log streams
python -m moviebot.cli.tool_cli logs --source watcher --lines 20
```

---

## 🧪 Running Tests
We provide full test coverage for deduplication, file heuristic parsing, and configuration verification:
```powershell
pytest
```
