# Movie Media Bot 🎬

A modular, stateful, tool-friendly Discord bot ecosystem that automates movie searching, local media library cross-referencing, and multi-stage download handoffs.

---

## 🚀 System Architecture & Setup

This system is designed to run in a hybrid container-to-host layout on **Windows**:
1.  **Discord Bot / APIs (`movie-media-bot`):** Runs inside a Docker container (or directly on Windows). Launches the Discord bot client and the FastAPI webhook listener concurrently on port `8000`.
2.  **Prowlarr (Docker):** Runs inside Docker on `http://host.docker.internal:9696`.
3.  **FlareSolverr (Docker):** Solves Cloudflare challenges automatically for Prowlarr indexers on `http://host.docker.internal:8191`.
4.  **Tautulli (Plex Activity):** Pushes stream playback activity notifications (start, stop, watched) directly to the FastAPI webhook endpoint.
5.  **Internet Download Manager (IDM):** Runs natively on the Windows host.
6.  **IDM Bridge:** A lightweight PowerShell REST server runs on the host to bridge requests from the Docker container to native IDM.

### 1. Host Configuration
Copy `.env.example` to `.env` and fill in the required API keys and secrets (Discord, AllDebrid, Prowlarr, Plex, and Tautulli Webhook Secret).

### 2. Launching the Discord Bot & Webhook Server (Docker)
```powershell
docker-compose up -d --build
```
This boots both the Discord Bot Gateway and the FastAPI Webhook Receiver listening on port `8000` (mapped to `http://localhost:8000/webhook/tautulli` for incoming stream notifications).

### 3. Launching the IDM Host Bridge
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
*   `/sync`: Manually sync the local database mirror with the movie library on the Plex server.
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

---

## 🛠️ Developer Interface (CLI Tool)

For administrative operations, debugging, or running as a tool directly from terminal:
```powershell
# Run configuration and path check tests
python -m moviebot.cli.tool_cli configtest

# Trigger database synchronization sweeps
python -m moviebot.cli.tool_cli sync-library

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
