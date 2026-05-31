# Block 2-4: Unified Discord, CLI & MCP Interface

> Status: Proposed
> Result: Pending
> Verification: Start MCP server to check schemas; run Discord app in verification mode to test UI embeds and sequel search buttons.

## Goal
Expose the new media intelligence features through the Discord slash command surface, MCP wrapper tools, and the CLI execution suite.

## Scope
* **JSON Tool Integration**:
  * Create `moviebot/tools/query_library_tool.py`:
    * Accepts parameters: `query`, `semantic_query`, `genre`, `director`, `resolution`, `watch_status`, `max_runtime`, `min_rating`.
    * Invokes SQLite FTS5 and cosine similarity ranking.
  * Create `moviebot/tools/recommend_movies_tool.py`:
    * Runs the taste recommender algorithm.
  * Create `moviebot/tools/audit_collections_tool.py`:
    * Runs the collection gap auditing logic.
  * Register all three tools on the FastMCP interface in `moviebot/cli/mcp_server.py`.
  * Register all three tools in `docs/tool-manifest.yaml` before exposing them through Discord.
  * Preserve the standard `{ ok, tool, timestamp, data }` / `{ ok, tool, timestamp, error }` JSON envelope from `docs/tool-surface.md`.
* **CLI Additions**:
  * In `moviebot/cli/tool_cli.py`, implement `query-library`, `recommend`, and `audit-collections` CLI subcommands forwarding parameters to the respective tools.
  * Human CLI output may be table-formatted, but `--json` must return the unmodified structured envelope for tool callers.
* **Discord Slash Commands & UI Components**:
  * In `moviebot/bot/discord_app.py`, implement:
    * `/library`: Calls `query_library_tool` and returns a rich embed list (displaying percentage match for semantic results).
    * `/recommend`: Calls `recommend_movies_tool` and displays taste profiling recommendations in an embed.
    * `/audit`: Calls `audit_collections_tool`, returns an embed of gaps, and dynamically builds a `CollectionAuditView` with buttons (e.g. `[🔍 Search John Wick 3]`). Clicking a button starts an indexer search for the missing sequel.

## Out Of Scope
* Modifying background debrid resolver loop logic.

## Implementation Instructions
1. Implement the tool scripts under `src/moviebot/tools/`.
2. Register them using `@mcp.tool()` inside `src/moviebot/cli/mcp_server.py`.
3. Add the subcommands to `src/moviebot/cli/tool_cli.py`.
4. In `src/moviebot/bot/discord_app.py`, write the slash commands and subclass `discord.ui.View` to implement the `CollectionAuditView` buttons which internally invoke the indexer search callback.

## Acceptance Criteria
* The MCP server starts successfully and exposes `query_library_tool`, `recommend_movies_tool`, and `audit_collections_tool` with correct parameter schemas.
* `docs/tool-manifest.yaml` and `docs/tool-surface.md` describe the tool names, risk levels, inputs, and output shapes.
* Running CLI command `python -m moviebot.cli.tool_cli query-library --genre "Sci-Fi"` prints correct matching entries.
* Running `/audit` in Discord returns a list of missing collection sequences with working search buttons.
* Clicking a gap search button correctly triggers a search query against Prowlarr and displays the interactive debrid download option view.

## Verification Commands
```powershell
$env:PYTHONPATH="src"
# Verify tests
pytest tests/test_mcp_server.py
pytest tests/test_intelligence.py

# Verify CLI subcommands
python -m moviebot.cli.tool_cli query-library --help
python -m moviebot.cli.tool_cli recommend --help
python -m moviebot.cli.tool_cli audit-collections --help
```
