# Block 05: MCP Server Integration

**Status: COMPLETED**

## Goal
Implement a Model Context Protocol (MCP) server wrapper around our standardized JSON tool boundaries, allowing AI agents (like Codex or Antigravity) to search library mirrors, check deduplication, and request downloads directly.

## Scope
* Create `src/moviebot/cli/mcp_server.py` using the Python MCP SDK.
* Expose all 8 core and advanced tools as official MCP tools:
  1. `search_library`
  2. `dedupe_check`
  3. `search_sources`
  4. `enqueue_download`
  5. `get_download_jobs`
  6. `get_error_logs`
  7. `query_watch_history`
  8. `resolve_pending_jobs`
* Provide local configuration snippets for Codex and Antigravity.

## Acceptance Criteria
* The MCP server starts and successfully lists all 8 tools.
* Tools invoked through MCP return output matching the standardized JSON envelope.

