# Block 6-7: Anime Download MVP Integration

> Status: Planned.
> Result: Not implemented.
> Notes: Completes the Phase 6 MVP with confirmed anime episode, special, absolute episode, whole-season, and season-pack downloads.

## Goal

Integrate the Phase 6 anime download pieces into one verified manual workflow: users can search, review, confirm, and enqueue anime episodes, specials, absolute episodes, whole seasons, or season packs while preserving dry-run safety, obfuscated references, structured errors, and JSON envelopes.

## Scope

- Wire anime request parsing, source search, result matching, deduplication, file selection, confirmation, AllDebrid unlock, and IDM handoff into a single manual flow.
- Add end-to-end CLI/MCP verification for dry-run and confirmed paths using mocked external adapters where possible.
- Add Discord end-to-end coverage for candidate review, confirmation, file selection, cancellation, and error states.
- Record structured domain events for successful confirmed enqueue attempts and structured errors for failures.
- Confirm the media-bot lifecycle still ends at IDM handoff and does not move, organize, or rename files.

## Out Of Scope

- Do not add autonomous anime monitoring or trusted auto-enqueue.
- Do not implement TV or TV Classic downloads.
- Do not modify `media-watcher` responsibilities.
- Do not expose raw magnets, direct links, API keys, tokens, private paths, or raw provider payloads.

## Likely Files Or Areas

- `src/moviebot/tools/`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/cli/mcp_server.py`
- `src/moviebot/discord_app.py`
- `src/moviebot/db/repositories.py`
- `tests/test_anime_download_mvp.py`
- `tests/test_discord_app.py`

## Acceptance Criteria

- A dry-run anime episode/special/absolute episode/whole-season/season-pack request returns safe candidates and proposed actions without writes.
- A confirmed anime request can enqueue the selected safe candidate through mocked AllDebrid/IDM boundaries.
- Ambiguous, duplicate, unsafe, and upstream-failure cases return structured errors or selection states.
- Movie download behavior remains backward compatible.
- The Phase 6 MVP can be demonstrated through CLI/MCP and Discord-facing tests.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_download_mvp.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_discord_app.py tests/test_anime_download_mvp.py -q --basetemp data\\pytesttmp-anime-mvp`
