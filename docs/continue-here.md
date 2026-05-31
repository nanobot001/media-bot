# Continue Here

## 2026-05-29

Current state:
- All 6 blocks have been successfully implemented, verified, and merged:
  - **Block 01 (Verification & Integration)**: Plex library syncing (mirrored database), Prowlarr client, and host-side IDM HTTP bridge delegation.
  - **Block 02 (Discord Gateway)**: Slash commands (`/search`, `/download`, `/check`, `/sync`, `/history`), channel checks (`@in_allowed_channel()`), interactive button/select views, and SQLite error logging (`errors` table) with admin notifications.
  - **Block 03 (Tautulli Webhooks)**: FastAPI receiver (`/webhook/tautulli`) on port 8000 to ingest Plex events, secured with token/bearer auth, logging events to `events` table and triggering selective database syncs.
  - **Block 04-1 (Active Jobs & Diagnostics)**: Active job tracking in DB, automated background resolver polling AllDebrid every 60s, and diagnostic slash commands (`/jobs`, `/resolve`, `/errors`).
  - **Block 05 (MCP Server Wrapper)**: Exposed all 8 system tools via Model Context Protocol (`FastMCP` server at `src/moviebot/cli/mcp_server.py`) for AI agent discovery and automation.
  - **Block 06 (System Diagnostics & Observability)**: Diagnostic suite tools (`check_movie_state_tool`, `get_system_health_tool`, etc.) fully exposed over Discord `/status` & `/health` slash commands, FastAPI, CLI, and FastMCP, verified with an isolated unit test suite.
- AllDebrid API has been fully migrated from deprecated `/v4` to `/v4.1` with recursive file flattening to support status checking (`/magnet/status`) and file selection.
- Both `media-bot` and `anime-pipe` have been configured to run via PM2 on Windows with hidden console windows (`windowsHide: true`), ensuring resurrection on reboot.
- All 32 pytest unit tests are passing successfully in the Docker container (`docker compose run`).

Next step:
- **Phase 2: Centralized Media Intelligence Layer (Plex-RAG Evolution)**:
  - Transition the Plex mirror database into a fully-realized media intelligence metadata engine with SQLite FTS5 for smart search.
  - Keep Phase 2 SQLite-first with in-memory cosine similarity over versioned synopsis embeddings; defer dedicated vector databases until the conversational RAG phase or proven scale pressure.

Do-not-forget checks:
- Keep the Docker-to-host bridge routing via `host.docker.internal` active.
- Verify PM2 log outputs (`pm2 logs`) to trace the background job resolver and Discord gateway status.
