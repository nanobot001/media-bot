# Block 3-0: RAG Infrastructure & Caching

> Status: Planned.
> Result: In progress.
> Notes: Establishes backend support utilities for conversational library RAG, including in-memory TTL caching, token-efficient metadata serialization, and a central Gemini text generation client.

## Goal

Lay down the foundational code infrastructure to support high-efficiency conversational RAG (Block 3-1). By building a robust text-generation client wrapper, token minification mechanics, and query caching, we ensure Block 3-1 has a fast, stable, and cost-controlled foundation.

## Scope

- **Gemini Completion Client (`src/moviebot/core/gemini_client.py`):**
  - Implement a central async function `generate_gemini_content` to call Gemini for text/JSON generation.
  - Automatically read model names and credentials from existing configuration wrappers.
  - Capture generation errors and log them to the local `ErrorLogRepository`.
- **RAG Infrastructure Helpers (`src/moviebot/core/conversational_rag.py`):**
  - Implement `minimize_movie_metadata(movie: Dict[str, Any]) -> Dict[str, Any]` to extract only essential matching facts and truncate synopses to under 150 characters, reducing token usage per candidate by 80%.
  - Implement `RAGQueryCache` as a thread-safe, async-capable, in-memory cache with configurable TTL (default 300 seconds) to avoid duplicate API requests.
- **Unit Testing (`tests/test_conversational_rag.py`):**
  - Test metadata minification logic.
  - Test `RAGQueryCache` TTL expiration, hits, misses, and cleanup.
  - Mock and test the Gemini text client interface.

## Out Of Scope

- User-facing interfaces (Discord `/ask` slash command, CLI `ask` command, MCP server tools).
- Schema changes or database modifications.

## Likely Files Or Areas

- `src/moviebot/core/gemini_client.py` [NEW]
- `src/moviebot/core/conversational_rag.py` [NEW]
- `tests/test_conversational_rag.py` [NEW]

## Acceptance Criteria

- `pytest tests/test_conversational_rag.py` executes and passes all tests.
- `minimize_movie_metadata` successfully serializes movie objects into compact dictionaries with truncated synopses.
- `RAGQueryCache` correctly caches and returns values within the TTL, and evicts them after the TTL expires.
- Central Gemini client executes completions and records errors using the DB logger.

## Verification

- `pytest tests/test_conversational_rag.py`
