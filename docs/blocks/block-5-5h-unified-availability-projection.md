# Block 5-5h: Unified Availability Projection

> Status: Planned.
> Result: Not implemented.
> Notes: Corrective Phase 5 consumer block; makes Discovery, Search, pre-warm status, CLI, MCP, and the web UI project the same catalog-derived state before MediaFlow production integration.

## Goal

Make every read surface describe the same title/scope availability and variant evidence. Discovery and tools must distinguish unknown from state A, preserve direct-play-only state C, expose cached alternatives without overstating browser readiness, and use canonical domain and TV-scope identity.

## Dependencies

- Block 5-5f release-variant catalog and shared availability service.
- Block 5-5g truthful catalog population from Search and pre-warming.

## Scope

- Make web Discovery, web Search, pre-warm status/scoreboard inputs, `discover_media_tool`, CLI Discovery, and MCP Discovery consume the shared catalog projection rather than route-specific boolean reconstruction.
- Add one authoritative structured field such as `availability_state` plus coverage and freshness metadata; retain existing aliases additively during compatibility migration.
- Preserve state C as verified direct play only: `browser_stream_ready` and legacy `instant_cached` remain true only for fresh exact direct-play evidence.
- Expose cached variant counts and sanitized variant summaries sufficient for a later MediaFlow selector without exposing magnets, raw provider URLs, credentials, or private paths.
- Represent missing, stale, failed, and incomplete provider evidence as `unknown` / `not_checked`; do not label it uncached or claim active searching when no work is running.
- Fix `classic_tv` input aliasing so all durable lookups use canonical `tv_classic` identity.
- Define TV projections explicitly by requested episode, season, season pack, or complete-series scope; a show-level card must not imply whole-show readiness from one season or episode.
- Keep major/indie Discovery presentation tiers, pre-warm source vectors, A/B/C availability, and later scoreboard milestones as separate concepts.
- Document compatibility fields and update tool-facing contracts where additive output fields become durable.

## Out Of Scope

- MediaFlow playback, preflight, transcode state, or production feature flags.
- Building the final release-version picker.
- Changing pre-warm scheduling, candidate budgets, ranking, quality gates, or provider mutation behavior.
- Removing legacy fields before all in-repo consumers and tests have migrated.

## Likely Files Or Areas

- `src/moviebot/core/availability_service.py`
- `src/moviebot/tools/discover_media_tool.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/cli/mcp_server.py`
- `src/moviebot/web/app.js`
- `docs/tool-adapter-memory.md`
- `docs/tool-surface.md`
- `docs/tool-manifest.yaml`
- `tests/test_web_ui_endpoints.py`
- `tests/test_web_search.py`
- `tests/test_discover_media.py`
- `tests/test_mcp_server.py`

## Acceptance Criteria

- The same seeded catalog evidence produces the same `availability_state`, counts, and direct-play flag in Discovery, Search, CLI, MCP, and pre-warm read APIs.
- No evidence, stale evidence, AD timeout, and partial checks render as unknown/not checked; only a complete successful zero-cached check renders A.
- A title with cached non-direct variants renders B; adding one verified direct variant renders C while all other cached variants remain visible.
- `browser_stream_ready` and `instant_cached` remain exact aliases for direct-play C and are never set by MediaFlow capability.
- `classic_tv` requests retrieve `tv_classic` catalog evidence in deterministic route/tool tests.
- TV cards identify the scope supporting their status and cannot promote a whole show from an unrelated episode or season.
- Public structured outputs contain no raw magnets, provider URLs, credentials, private paths, or unsanitized provider errors.
- Existing clients retain additive compatibility fields, and all changed tool contracts have matching tests and documentation.

## Verification

- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_web_ui_endpoints.py tests\test_web_search.py tests\test_discover_media.py tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5h`
- Add one shared fixture matrix for unknown, A, B, C, stale, provider-error, movie-remake, TV episode, season-pack, and Classic TV alias projections across every surface.
- `node --check src/moviebot/web/app.js`
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5h-full`
- `git diff --check`
- Restart only `media-bot` through PM2 and compare the web/API projection against seeded or existing read-only catalog evidence. Do not trigger live provider work without separate authorization.
