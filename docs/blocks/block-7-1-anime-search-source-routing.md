# Block 6-1: Anime Search Source Routing

> Status: Planned.
> Result: Not implemented.
> Notes: Starts Phase 6 by generalizing source search beyond movie category `2000` for anime requests.

## Goal

Add domain-aware anime source search so the bot can query configured anime Prowlarr categories while preserving movie search behavior, magnet obfuscation, structured JSON envelopes, and dry-run-safe tool contracts.

## Scope

- Add settings for anime Prowlarr categories, indexer preferences, and optional quality/release filters without changing the movie category default.
- Add a domain-aware source search path for `anime` that returns obfuscated result references instead of raw magnet URLs.
- Preserve existing `search_sources` movie behavior as the backward-compatible default.
- Include dry-run/preview behavior that shows query parameters, selected categories, and result counts without enqueueing downloads.
- Record structured errors for misconfigured categories, unavailable Prowlarr, malformed responses, and empty results.

## Out Of Scope

- Do not parse episode requests beyond accepting normalized search text.
- Do not deduplicate against anime episodes yet.
- Do not enqueue or unlock downloads.
- Do not add TV or TV Classic search categories.

## Likely Files Or Areas

- `src/moviebot/config.py`
- `src/moviebot/adapters/prowlarr_client.py`
- `src/moviebot/tools/`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/cli/mcp_server.py`
- `tests/test_anime_search_sources.py`

## Acceptance Criteria

- Anime source search uses anime-specific configured categories and leaves movie category `2000` behavior unchanged.
- Tool output uses structured JSON envelopes and obfuscated result references.
- Public-read results do not expose raw magnet URLs, API keys, private local paths, or raw sensitive payloads.
- Misconfiguration and upstream failures return structured errors.

## Verification

- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_anime_search_sources.py -q`
- `$env:PYTHONPATH="src"; py -3.12 -m pytest tests/test_tool_cli.py tests/test_mcp_server.py -q --basetemp data\\pytesttmp-anime-search`
