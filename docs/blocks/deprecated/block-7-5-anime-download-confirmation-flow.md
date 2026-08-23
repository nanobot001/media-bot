# Block 6-5: Anime Download Confirmation Flow

> Status: Planned.
> Result: Not implemented.
> Notes: Exposes manual, confirmation-first anime downloads through tool and user-facing surfaces.

## Goal

Add an anime download flow that lets users search and confirm episode, special, absolute episode, or season-pack downloads through structured tools and Discord/CLI surfaces before any write action reaches AllDebrid or IDM.

## Scope

- Add CLI and MCP tool exposure for anime search/download intents with dry-run defaults where appropriate.
- Add Discord interaction support for reviewing anime candidates, confirming a selected result, choosing files when required, and cancelling safely.
- Preserve obfuscated result references through the confirmation flow.
- Record structured events for confirmed write actions and structured errors for failed searches, ambiguous matches, and enqueue failures.
- Keep movie `/search`, `/download`, and existing tool behavior backward compatible.

## Out Of Scope

- Do not add trusted auto-download or monitor behavior.
- Do not bypass confirmation for anime downloads.
- Do not implement TV or TV Classic download flows.
- Do not expose raw magnets, direct links, API keys, tokens, or private local paths.

## Likely Files Or Areas

- `src/moviebot/tools/`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/cli/mcp_server.py`
- `src/moviebot/discord_app.py`
- `tests/test_anime_download_flow.py`
- `tests/test_discord_app.py`

## Acceptance Criteria

- Anime download commands can run dry-run searches and return structured candidates.
- Confirmed write actions require explicit user selection or confirmation.
- Discord and tool outputs preserve JSON/privacy boundaries and magnet obfuscation.
- Confirmed attempts create structured events and errors without breaking movie flows.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_download_flow.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_discord_app.py tests/test_anime_download_flow.py -q --basetemp data\\pytesttmp-anime-download-flow`
