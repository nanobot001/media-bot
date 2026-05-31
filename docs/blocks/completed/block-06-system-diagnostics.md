# Block 06: System Diagnostics and Observability Suite

**Status: COMPLETED**

## Execution Notes
This block was implemented and verified successfully:
- **Core Diagnostic Tools**: Developed `check_movie_state_tool`, `get_system_health_tool`, `get_tool_manifest_tool`, `get_recent_events_tool`, and `tail_logs_tool`.
- **FastAPI Endpoints**: Exposed the diagnostic tools over HTTP routes (`/health`, `/status`, `/manifest`, `/events`, `/logs`) in `webhook.py`, resolving a namespace shadowing bug where the route function shadowed the `fastapi.status` module.
- **FastMCP Integration**: Registered all 5 tools on the MCP server in `mcp_server.py`.
- **CLI Subcommands**: Added clean command-line subcommands to `tool_cli.py`.
- **Discord Slash Commands**: Implemented `/status` and `/health` commands in `discord_app.py` returning interactive, beautifully formatted embeds, restricted by channel and role checks.
- **Verification**: Built a robust, isolated unit testing suite in `tests/test_check_state_and_health.py` mocking file system checks, dynamic HTTP responses, PM2 subprocess output, and database repositories. All tests pass successfully.

## Goal
Implement a comprehensive, standardized system diagnostics and observability suite to support health checks, movie pipeline tracking, manifest introspection, events querying, and tail logging. These tools must be exposed over Discord, HTTP endpoints, CLI, and MCP.

## Scope
*   **Core Tools**:
    *   `check_movie_state`: Cross-reference Plex database (`library_items`), active/recent download jobs (`download_jobs`), intake storage (`F:\_temp\movies`), destination directories, and FileBot logs (`media-watcher.log`) for a given movie title.
    *   `get_system_health`: Monitor stack connectivity (Plex, Prowlarr, AllDebrid, Tautulli), local disk/mount read-write status (`F:`, `C:`), PM2 process states (via `pm2 jlist`), and local IDM bridge health.
    *   `get_tool_manifest`: Parse and expose the schemas of the tool manifest (`docs/tool-manifest.yaml`).
    *   `get_recent_events`: Fetch recent logs from the `events` table.
    *   `tail_logs`: Retrieve the last N lines from specific logs (`watcher`, `bot-out`, `bot-err`).
*   **Adapters & API**:
    *   Add GET `/health` to `idm_bridge_api.py`.
    *   Expose GET `/health`, GET `/status`, GET `/manifest`, GET `/events`, and GET `/logs` on the FastAPI server (`webhook.py`).
*   **Presentation & CLI**:
    *   Add `check-state`, `health`, `manifest`, `events`, and `logs` subcommands to `tool_cli.py`.
    *   Register all 5 tools as MCP tools in `mcp_server.py`.
    *   Add `/status` and `/health` slash commands in `discord_app.py` with rich interactive embeds.

## Acceptance Criteria
*   The FastMCP server correctly lists and executes the 5 new diagnostic tools.
*   FastAPI endpoints respond with correct status envelopes.
*   CLI and Discord subcommands run cleanly and present data accessibly.
*   A suite of unit tests validates the behavior of all diagnostic components.
