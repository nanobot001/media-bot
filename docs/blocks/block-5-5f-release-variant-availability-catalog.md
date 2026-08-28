# Block 5-5f: Release-Variant Availability Catalog

> Status: Planned.
> Result: Not implemented.
> Notes: Corrective Phase 5 state-foundation block; replaces the one-selected-release snapshot as the long-term source of truth while preserving compatibility for existing callers.

## Goal

Represent every relevant release version discovered for an exact movie or TV scope, retain its independent AllDebrid and delivery evidence, and derive one coherent title-level availability class. The catalog must preserve direct-play state C as authoritative direct-play evidence only; MediaFlow capability remains a separate per-variant delivery property and never promotes A/B/C.

## Dependencies

- Block 5-5 authoritative direct-play verification and exact media identity.
- Block 5-5d movie release-window quality gate.
- Block 5-5e durable `cycle_id` and pre-warm run evidence.

## Canonical State Contract

- Internal aggregate state `unknown`: evidence is absent, incomplete, stale, or the provider check failed.
- State A / `not_cached`: a successful bounded AD check found zero cached variants among the recorded candidate set.
- State B / `ad_cached`: at least one exact eligible variant is cached, but no cached variant has fresh authoritative direct-play proof.
- State C / `direct_play_ready`: at least one exact eligible cached variant has fresh authoritative direct-play proof.
- MediaFlow fields describe how a cached non-direct variant may be delivered (`untested`, `candidate`, `verified`, or `failed`) but do not alter A/B/C.

## Scope

- Add a durable release-variant repository keyed by canonical media identity plus a stable release identity/hash rather than one row per title.
- Preserve movie title/year/TMDb identity and TV show/season/episode/pack scope so remakes, seasons, episodes, season packs, and complete-series packs cannot inherit unrelated evidence.
- Store sanitized release facts needed for selection: title, resolution, source type, container, video/audio codecs, HDR, channels, subtitle summary, size, seeders, and source/vector attribution.
- Store independent evidence dimensions for AD cache state, direct-play verification, and MediaFlow qualification, each with checked/verified timestamps and structured status/error fields.
- Preserve `first_seen_at`, `last_seen_at`, `last_cache_checked_at`, and `last_observed_cycle_id` without rewriting first-seen history during re-verification.
- Add a shared availability service that derives the title/scope aggregate and coverage counts from current variant evidence instead of accepting route-authored booleans.
- Expose checked-candidate coverage so state A means "none of the recorded candidates successfully checked were cached," never an unbounded provider-wide claim.
- Provide an additive compatibility projection for existing `cached`, `cloud_cached`, `instant_cached`, and `browser_stream_ready` readers while making the canonical aggregate state explicit.
- Add a bounded read-only catalog inspector for an exact media identity that returns the aggregate state, coverage, sanitized variant summaries, evidence status/freshness, and first/last-observed timestamps without switching normal Discovery or Search consumers.
- Migrate existing `prewarmed_cache` records conservatively: fresh direct evidence becomes C evidence; fresh cached-only evidence becomes B evidence; existing false/absent cache bits become `unknown` unless a successful check proves A.
- Keep the existing table readable during migration and provide a rollback-safe path; do not destructively delete historical rows in this block.

## Out Of Scope

- Performing new provider searches, AD checks, direct verification, or MediaFlow preflights.
- Switching Discovery, Search, CLI/MCP, or UI consumers to the new projection.
- Changing pre-warm budgets, scheduling, ranking, or automatic acquisition behavior.
- Building the version-picker UI or production MediaFlow adapter.

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/release_variant_repo.py`
- `src/moviebot/core/availability_service.py`
- `src/moviebot/db/cache_prewarm_repo.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/cli/tool_cli.py`
- `tests/test_release_variant_catalog.py`
- `tests/test_browser_stream_verification.py`
- `tests/test_web_ui_endpoints.py`
- `docs/tool-adapter-memory.md`

## Acceptance Criteria

- Two or more variants for one movie/year or TV scope remain independently queryable after repeated writes and re-verification.
- A successful check with zero cached variants derives A; one cached non-direct variant derives B; one fresh verified direct variant derives C.
- Adding or removing MediaFlow qualification does not change the derived A/B/C result.
- Provider error, unchecked, partial, and stale evidence derive `unknown`, never A.
- A title may derive C while retaining additional B-class cached variants for later MediaFlow selection.
- First-seen timestamps remain stable while last-seen/check timestamps advance independently.
- Existing fresh browser evidence and cached-only records migrate without losing exact reference identity; legacy false rows do not become false claims of A.
- Movie remake identity and TV season/episode/pack identity are covered by deterministic tests.
- Given an exact movie or TV scope, the read-only inspector visibly lists every retained variant and its independent AD, direct-play, and MediaFlow evidence while exposing no raw provider reference or secret.
- Legacy structured fields remain available as documented additive projections during migration.

## Verification

- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_release_variant_catalog.py tests\test_browser_stream_verification.py tests\test_background_prewarmer.py -q --basetemp scratch\pytesttmp-block-5-5f`
- Add migration fixtures for browser-verified, cached-only, false/unknown, duplicate-title/different-year, episode, season-pack, and complete-series records.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5f-full`
- `git diff --check`
- Run a read-only migration preview against a copied local database and compare legacy versus projected counts before any normal-runtime restart.
