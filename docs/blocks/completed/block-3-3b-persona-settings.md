# Block 3-3b: Persona Settings & Conversational History Integration

> Status: Implemented on 2026-06-06.
> Result: Implemented.
> Verification: `pytest tests/test_persona_settings.py` and `pytest tests/test_mcp_server.py` - passed.
> Notes: Implemented persistent bot persona overrides, Discord `/persona` command suite, FastMCP persona tools, sliding history context window (10 turns), and expanded interaction database retention (1,000 entries).

## Goal

Enable system administrators to customize and persist the bot's conversational persona/system instructions via Discord, CLI, and MCP. Additionally, scale the RAG pipeline's memory capability to support deep conversational context tracking by injecting multi-turn chat history into queries and retaining a larger historical record.

## Scope

- **Database & Persistence Layer:**
  - Create `BotSettingsRepository` backed by the `kv_store` table to store and retrieve the custom `rag_persona` setting.
  - Expand SQLite user interaction logging retention capacity from 30 entries to **1,000 entries** per user with a robust automated pruning mechanism.
- **Conversational RAG Engine:**
  - Update `conversational_rag.py` to retrieve the custom persona override from `BotSettingsRepository`, dynamically applying it to Gemini generation system instructions.
  - Implement structured conversation history injection: reconstruct the last **10 turns** (20 messages total) of user queries and bot responses from `UserInteractionMemoryRepository` and inject them as `chat_history` when invoking Gemini Flash.
- **Discord Presentation & CLI Layers:**
  - Implement `/persona show`, `/persona set <persona_text>`, and `/persona reset` slash commands in `discord_app.py`, restricted to users with `is_bot_manager_check` permissions.
  - Integrate new persona commands into `/help` slash command documentation.
  - Expose CLI options for managing the persona override.
- **MCP Server:**
  - Implement and register `get_bot_persona` and `set_bot_persona` tools in FastMCP (`mcp_server.py`).
  - Document the tools in `tool-manifest.yaml`.
- **Testing & Verification:**
  - Write test suite `tests/test_persona_settings.py` verifying Settings Repository CRUD, RAG prompt overrides, context history injection, Discord command rendering, and database pruning logic.
  - Verify MCP tools invocation in `tests/test_mcp_server.py`.

## Out Of Scope

- Personal user-specific persona instructions (the persona is global for the bot).
- Real-time LLM persona generation or dynamic self-refinement of the persona.

## Likely Files Or Areas

- `src/moviebot/db/repositories.py`
- `src/moviebot/core/conversational_rag.py`
- `src/moviebot/tools/ask_library_tool.py`
- `src/moviebot/bot/discord_app.py`
- `src/moviebot/cli/mcp_server.py`
- `src/moviebot/cli/tool_cli.py`
- `tests/test_persona_settings.py` [NEW]

## Acceptance Criteria

- Running `/persona show` displays the active system instruction/persona.
- Running `/persona set <text>` overrides the default system instruction for all future conversational RAG queries.
- Running `/persona reset` reverts the bot back to the default config-level system instruction.
- Only users with `is_bot_manager` permissions can run persona modification commands.
- `/ask` queries successfully remember and adapt to the context of the last 10 turns.
- Interaction history logs are pruned correctly once they exceed 1,000 entries per user.
- All new tests pass.

## Verification

- `pytest tests/test_persona_settings.py` passes.
- `pytest tests/test_mcp_server.py` passes.
