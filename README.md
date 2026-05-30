# Movie Media Bot 🎬

A modular, stateful, tool-friendly Discord bot ecosystem that automates movie searching, local media library cross-referencing, and multi-stage download handoffs.

---

## 🚀 System Architecture & Setup

This system is designed to run in a hybrid container-to-host layout on **Windows**:
1.  **Discord Bot / APIs (`movie-media-bot`):** Runs inside a Docker container (or directly on Windows). Launches the Discord bot client and the FastAPI webhook listener concurrently on port `8000`.
2.  **Prowlarr (Docker):** Runs inside Docker on `http://host.docker.internal:9696`.
3.  **Tautulli (Plex Activity):** Pushes stream playback activity notifications (start, stop, watched) directly to the FastAPI webhook endpoint.
4.  **Internet Download Manager (IDM):** Runs natively on the Windows host.
5.  **IDM Bridge:** A lightweight PowerShell REST server runs on the host to bridge requests from the Docker container to native IDM.

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
*   `/resolve [dry_run]`: Manually trigger a resolution sweep on pending magnet links.
*   `/errors [limit]` *(Bot Managers Only)*: List recent runtime command exception log reports.
*   `/health` *(Bot Managers Only)*: Expose stack connectivity, process metrics, and disk spaces.
*   `/events [limit]` *(Bot Managers Only)*: Retrieve recent SQLite event log entries.
*   `/logs <source> [lines]` *(Bot Managers Only)*: Tail logs for a named source (`watcher`, `bot-out`, `bot-err`).

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
