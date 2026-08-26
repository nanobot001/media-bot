# Block 5-7: Browser-Readiness Scoreboard Semantics

> Status: Planned.
> Result: Not implemented.
> Notes: Final block in the Phase 5 stream-readiness hardening sequence; depends on the stable evidence states from Block 5-5 and cycle attribution from Block 5-6.

## Goal

Make prewarming tiers and progress report the capability the user actually cares about. Tracking or cache-checking a title must not advance a browser-readiness milestone; milestone progress and `frontier_to_go` must count only exact media records with fresh, authoritative browser-ready evidence.

## Dependencies

- Block 5-5 authoritative verified-browser evidence.
- Block 5-6 preserved vector origins and adaptive-cycle metrics.

## Scope

- Preserve the existing milestone values:
  - movies: 40, 100, 250, 500, 1000;
  - TV: 30, 75, 150, 300, 600;
  - TV Classic: 100, 250, 500, 1000, 2000;
  - all domains: 170, 425, 900, 1800, 3600.
- Calculate tier advancement, `frontier_to_go`, and `progress_percent` from fresh `browser_stream_ready` records, not `total_tracked`.
- Continue reporting separate capability counts:
  - `total_tracked` / evaluated;
  - `cloud_cached` / instant-download-ready;
  - `instant_cached` / verified-browser-ready;
  - `external_cached` / cached but not browser-verified;
  - `p2p_only`;
  - `dropped_count`.
- Keep `vector_breakdown` and add or preserve enough lane attribution to explain how many verified browser records came from recent, all-time, TV progression, Discovery-hot, manual, and Search-promotion origins.
- Update scoreboard labels so `Tier`, progress percentage, and `Frontier (To Go)` explicitly mean verified browser-stream coverage.
- Show evaluated and cached-download totals alongside the browser milestone so increased scanning is visible without overstating streaming readiness.
- Keep existing API field names where compatibility requires them; add explicit aliases/labels instead of silently changing a published structured field's meaning when downstream consumers could be affected.
- Document the finalized distinction among Discovery presentation tiers (`major`/`indie`), prewarm source vectors, and browser-readiness milestone tiers.

## Out Of Scope

- Changing the milestone numbers.
- Changing frontier selection, adaptive budgets, cursor advancement, or provider calls.
- Reclassifying major versus indie media.
- Treating likely/probeable candidates as verified browser-ready.
- Rewriting historical records without applying the Block 5-5 evidence rules.

## Likely Files Or Areas

- `src/moviebot/db/cache_prewarm_repo.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/web/app.js`
- `src/moviebot/web/index.html`
- `docs/tool-adapter-memory.md`
- `tests/test_background_prewarmer.py`
- `tests/test_web_ui_endpoints.py`

## Acceptance Criteria

- With 40 tracked movie rows but only 10 verified browser-ready rows, the Tier 1 movie scoreboard reports 25% progress and 30 browser-ready titles to go.
- Cached-download-only and probeable records remain visible in their own counts but do not advance a browser milestone.
- Tier advancement occurs exactly at the existing verified-browser-ready thresholds.
- Dropped AD cache state removes affected browser-ready evidence from milestone progress.
- The dashboard clearly distinguishes evaluated, AD-cached/download-ready, and verified browser-ready totals.
- Major/indie Discovery tiers and source-vector counts remain separate concepts and retain existing behavior.
- Structured API compatibility is preserved or changed only through explicit additive fields covered by tests and documentation.
- No provider, AllDebrid, prewarm scheduling, transfer, or notification behavior changes in this block.

## Verification

- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_background_prewarmer.py tests\test_web_ui_endpoints.py -q --basetemp scratch\pytesttmp-block-5-7`
- Add deterministic scoreboard boundary tests immediately below, at, and above every milestone transition.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-7-full`
- `node --check src/moviebot/web/app.js`
- `git diff --check`
- Restart only `media-bot` through PM2 and compare the scoreboard API with the rendered Pre-warm UI using seeded or existing read-only data.
