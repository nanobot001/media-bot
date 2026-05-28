# Block 05: MCP Server Integration

**Status: PLANNED**

## Goal
Implement a Model Context Protocol (MCP) server wrapper around our standardized JSON tool boundaries, allowing AI agents (like Codex or Antigravity) to search library mirrors, check deduplication, and request downloads directly.

## Scope
* Create `src/moviebot/cli/mcp_server.py` using the Python MCP SDK.
* Expose `search_library_tool`, `dedupe_check_tool`, `search_sources_tool`, and `enqueue_download_tool` as official MCP tools.
* Mount the MCP server configuration inside the local Gemini/Claude app configurations.

## Acceptance Criteria
* The MCP server starts and successfully list all 4 tools.
* Tools invoked through MCP return output matching the standardized JSON envelope.
