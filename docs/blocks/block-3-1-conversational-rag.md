# Block 3-1: Conversational Library RAG & Ask Command

> Status: Planned.
> Result: In progress.
> Notes: Implements a 2-stage retrieval pipeline (semantic candidates + LLM reranking and conversational explanation) to allow natural language questions about the user's local library.

## Goal

Add conversational QA search capabilities to the `media-bot` via Discord, CLI, and MCP. Users will be able to query their library using rich, natural language questions (e.g., *"I want to watch a movie with great cinematography set in space, similar to Interstellar. What do I have?"* or *"What's a good sad drama from the 90s in my library?"*), and receive an engaging explanation of matching owned movies.

## Scope

- **Conversational RAG Core Engine (`src/moviebot/core/conversational_rag.py`):**
  - Implement a 2-stage retrieval pipeline:
    - **Stage 1 (Retrieval):** Perform local vector/semantic search using the composite embedding space to fetch the top $N$ (e.g., 15-20) candidate movies.
    - **Stage 2 (LLM Conversational Reranking & Explanation):** Format a rich prompt for the Gemini API containing the user's natural language question and the metadata of the candidate movies (including Title, Year, Genres, Tones, Themes, Synopsis, Tagline, Awards). Ask the model to select the best 3-5 matches and generate a concise, conversational markdown response explaining why they match the request.
- **Discord slash command (`/ask`):**
  - Register `/ask question:[string]` in `src/moviebot/bot/discord_app.py`.
  - Execute the 2-stage RAG pipeline and respond with a beautifully formatted Discord embed containing the conversational answer.
- **CLI Subcommand (`ask`):**
  - Add `ask` subcommand to `src/moviebot/cli/tool_cli.py`:
    - `python -m moviebot.cli.tool_cli ask --question "..."`
- **MCP Tool Registration (`plex.ask_library`):**
  - Expose the conversational search function via MCP to allow agentic workflows to converse with the library mirror.
- **Unit and Integration Testing:**
  - Write test cases verifying correct query construction, candidate selection logic, LLM prompt assembly, and error boundaries (e.g., empty library, Gemini API errors, rate limit handling).

## Out Of Scope

- Introducing conversational memory or chat history (each command execution is single-turn QA).
- Vector indexing of transcripts or full subtitle files (restricted to the existing composite `library_items` metadata schema).
- Modifying the underlying database schema.

## Likely Files Or Areas

- `src/moviebot/core/conversational_rag.py` [NEW]
- `src/moviebot/bot/discord_app.py`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/mcp/server.py`
- `tests/test_conversational_rag.py` [NEW]

## Acceptance Criteria

- Running `python -m moviebot.cli.tool_cli ask --question "What space movie do I have?"` returns a conversational response citing matches (e.g. *Interstellar*, *Ad Astra*) with an explanation.
- The `/ask` command is registered and executes correctly in Discord, responding with a rich embed.
- The `plex.ask_library` tool is available via the MCP server interface and returns valid JSON response envelopes.
- Unit tests verify the pipeline behavior under normal, mock-LLM, and failure states.

## Verification

- `pytest tests/test_conversational_rag.py` passes.
- Manual execution of the CLI and Discord commands with sample natural language queries.
