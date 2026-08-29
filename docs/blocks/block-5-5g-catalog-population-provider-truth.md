# Block 5-5g: Catalog Population and Provider-Check Truth

> Status: Implemented on 2026-08-29.
> Result: Implemented.
> Verification: `28 passed` focused; `384 passed, 5 warnings` full non-MCP suite; `node --check src\moviebot\web\app.js` and `git diff --check` passed.
> Notes: Search and passive pre-warming now share structured provider outcomes, retain every bounded exact variant with cycle/source evidence, and expose reconciled per-cycle catalog counts without acquiring media or creating transfer ownership. No live provider smoke or PM2 restart was performed.

## Goal

Populate the release-variant catalog from bounded Prowlarr searches and AllDebrid checks while retaining every relevant exact variant, explicit check coverage, source attribution, and cycle linkage. Provider errors and incomplete checks must remain unknown, and passive work must remain silent and non-acquiring.

## Dependencies

- Block 5-5e durable pre-warm run ledger.
- Block 5-5f release-variant catalog and canonical aggregate-state service.
- Existing movie quality gate, release parser, ranking, and exact identity safeguards.

## Scope

- Replace boolean-only AD cache-check results with structured per-candidate outcomes that distinguish `cached`, `not_cached`, `unknown`, provider error, and unresolvable reference.
- Preserve all eligible exact candidates returned inside the bounded search window instead of persisting only the selected winner.
- Record search coverage, candidate count, checked count, provider result, source/vector origin, and the active `cycle_id` for pre-warm work.
- Keep ranking as a selection aid and recommended-variant projection; it must not delete or overwrite lower-ranked variants.
- Update passive pre-warming to populate/reverify variant evidence while retaining existing recent, all-time, TV, TV Classic, and watch-priority vectors.
- Recalculate title/scope aggregates through the shared availability service after a complete bounded check.
- Extend pre-warm cycle status with visible discovered, retained, checked, cached, uncached, unknown, and provider-error variant counts sourced from the catalog writes for that cycle.
- Preserve exact direct-play evidence only for the matching release identity; a newly selected download candidate must not inherit another variant's browser proof.
- Keep passive checks silent: no automatic download of uncached media, no manual transfer intent, no Cloud Transfer card, and no completion notification.
- Return sanitized structured provider errors and counts without exposing raw magnets, provider URLs, credentials, or private paths.

## Out Of Scope

- Changing the number of titles or releases processed per cycle.
- Adding MediaFlow playback/preflight or the release-picker UI.
- Switching every presentation surface to the catalog; that belongs to Block 5-5h.
- Changing the movie quality gate, release-ranking weights, or manual acquisition paths.

## Likely Files Or Areas

- `src/moviebot/adapters/alldebrid_client.py`
- `src/moviebot/adapters/prowlarr_client.py`
- `src/moviebot/tools/search_sources_tool.py`
- `src/moviebot/core/background_prewarmer.py`
- `src/moviebot/core/availability_service.py`
- `src/moviebot/db/release_variant_repo.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/web/app.js`
- `tests/test_web_search.py`
- `tests/test_background_prewarmer.py`
- `tests/test_web_ui_endpoints.py`

## Acceptance Criteria

- A successful AD response marks each checked exact candidate cached or not cached; a timeout, HTTP failure, malformed response, or missing result remains unknown.
- A title with three discovered variants retains all three after ranking and repeated pre-warm cycles.
- Any cached variant derives at least B, and any exact fresh direct-play variant derives C, regardless of which variant is recommended for download.
- A complete successful check with zero cached variants derives A and records how many candidates were checked.
- Partial provider responses cannot derive A for the title/scope.
- Pre-warm writes include the durable cycle ID and preserve first-seen history.
- After a fixture-backed cycle, the pre-warm status surface visibly reports discovered, retained, checked, cached, uncached, unknown, and provider-error variant counts that reconcile to that cycle's catalog records.
- Search and pre-warm use the same provider-outcome mapping and exact identity rules.
- Passive work creates no cloud-transfer ownership, download, notification, or unsafe provider-wide cleanup side effect.

## Verification

- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_web_search.py tests\test_background_prewarmer.py tests\test_release_variant_catalog.py -q --basetemp scratch\pytesttmp-block-5-5g`
- Add deterministic fake-provider tests for complete cached/uncached responses, partial responses, timeout, HTTP error, malformed payload, duplicate release identity, and cross-cycle re-verification.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5g-full`
- `git diff --check`
- Verify with fake-backed data that no test creates provider transfer intents or notifications. Any live read-only AD smoke remains separately authorized.
