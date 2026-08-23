# Block 5-7: Anime RAG & Ask Support

> Status: Planned.
> Result: Not implemented.
> Notes: Completes the Phase 5 MVP by answering anime show and episode questions with citations.

## Goal

Add anime-aware conversational asking over the local anime database so users can ask show and episode questions and receive grounded answers with citations to local anime records.

## Scope

- Add anime domain support to the conversational ask pipeline, including CLI and MCP exposure.
- Route exact anime questions through structured query routing before semantic retrieval.
- Use anime semantic retrieval and compact metadata context for descriptive questions.
- Return citations that identify the anime domain, show title, episode title when applicable, season/episode or absolute episode number when available, and local Plex/source identifiers.
- Add Discord exposure through the existing `/ask` flow or a clearly domain-aware anime ask command if the current command structure requires it.
- Preserve movie ask behavior and multi-user privacy guards.

## Out Of Scope

- Do not add anime download search or enqueue behavior.
- Do not add `tv` or `tv_classic` RAG yet.
- Do not make unsupported hard claims without source-backed evidence.
- Do not expose private file paths, raw vectors, API keys, tokens, or raw provider payloads.

## Likely Files Or Areas

- `src/moviebot/core/conversational_rag.py`
- `src/moviebot/tools/`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/cli/mcp_server.py`
- `src/moviebot/discord_app.py`
- `tests/test_anime_rag.py`
- `tests/test_discord_app.py`

## Acceptance Criteria

- Users can ask anime show and episode questions and receive grounded answers with citations.
- Exact episode questions use structured routes before semantic retrieval.
- Descriptive anime questions can use semantic retrieval when embeddings are available.
- Movie `/ask`, CLI, and MCP behavior remains backward compatible.
- Public-read outputs preserve privacy and structured JSON envelopes.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_rag.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_discord_app.py tests/test_anime_rag.py -q --basetemp data\\pytesttmp-anime-rag`
