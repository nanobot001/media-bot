# Block 5-5c: MediaFlow Production Browser-Stream Adapter

> Status: Planned.
> Result: Not implemented.
> Notes: Historical identifier retained for continuity. Implementation is dependency-gated after Blocks 5-5e through 5-5h so MediaFlow consumes exact catalog variants and never owns A/B/C or direct-play truth.

## Goal

Allow the normal Media Bot UI at `http://localhost:8000` to deliver a user-selected cached release variant through the pinned, authenticated local MediaFlow service when direct play is unavailable or the user deliberately chooses another cached version. Preserve direct-play state C, safe HLS fallback, explicit failure behavior, local VLC fallback, and a fast operator rollback switch. The integration must remain server-side and feature-flagged until fixture-backed and separately authorized live canaries pass.

## Dependencies

- Block 5-5 authoritative browser-stream verification and its ownership-safe source identity.
- Block 5-5b MediaFlow pilot, including the v2.4.9 pinned container, safe HLS preflight, encrypted direct-transcode fallback, and fixture-backed decision contracts.
- Block 5-5d universal movie quality gate.
- Block 5-5f exact release-variant catalog and canonical A/B/C derivation.
- Block 5-5g truthful AD cache evidence for catalog variants.
- Block 5-5h unified availability projection and sanitized cached-variant summaries.
- Docker Desktop with the localhost-only MediaFlow profile healthy and authenticated.

## Scope

- Add a production adapter configuration flag that defaults to disabled and fails closed when MediaFlow health, authentication, or pinning requirements are not satisfied.
- Accept an exact catalog `release_variant_id`; do not search, rank, or infer a replacement release inside the MediaFlow adapter.
- Route a selected cached non-direct variant through the existing MediaFlow client while retaining the existing verified direct-play path as the default and the existing local VLC fallback.
- Add a minimal cached-version selector to the existing stream/detail experience: recommend the verified direct candidate when one exists, list other cached variants as MediaFlow candidates, and keep failed/external-only variants visible without claiming browser playback.
- Preserve A/B/C semantics: MediaFlow success or failure updates only that variant's MediaFlow delivery evidence and never sets `browser_stream_ready`, `instant_cached`, or title state C.
- Keep provider source URLs, MediaFlow passwords, authorization headers, and private command arguments server-side; expose only an opaque local playback/session reference to the browser.
- Reuse the existing structured delivery decisions and safe HLS preflight. If a vendor HLS manifest is unsafe or unverifiable, use encrypted direct transcode or return a bounded structured failure; never pass the unsafe manifest to the browser.
- Associate each production playback request with an opaque server-side session and terminate obsolete MediaFlow/FFmpeg/PyAV work on disconnect, seek, source replacement, timeout, and shutdown.
- Emit sanitized structured playback events containing decision, input/output codecs, accelerator, fallback reason, latency, reconnect count, exit reason, and cleanup result without secrets or raw provider URLs.
- Persist the MediaFlow result against the exact selected variant as `verified` or `failed`, including a sanitized decision (`direct`, `remux`, `audio_transcode`, `full_transcode`, or structured failure) and evidence timestamp.
- Make rollout and rollback operator-visible through configuration and health/status reporting without changing prewarming, readiness-scoreboard, or AllDebrid caching semantics.

## Out Of Scope

- Building a replacement transcoding service or changing MediaFlow itself.
- Removing or replacing the existing direct browser-stream route, local VLC fallback, or authoritative Block 5-5 verification.
- Public, LAN-wide, or remote exposure of MediaFlow; the initial production adapter remains localhost-only and authenticated.
- Automatically caching uncached media, creating Cloud Transfer intents, changing provider behavior, or starting an unauthorized live AllDebrid canary.
- Changing Block 5-6 prewarming budgets or Block 5-7 scoreboard semantics.
- Rebuilding the catalog, A/B/C projection, Search, or Discovery state derivation inside the adapter.
- Building polished audio/subtitle/quality preference management beyond the minimal exact-variant selector and existing player contract.

## Likely Files Or Areas

- `src/moviebot/adapters/mediaflow_client.py`
- `src/moviebot/core/browser_stream_verifier.py`
- `src/moviebot/core/mediaflow_pilot.py`
- `src/moviebot/core/availability_service.py`
- `src/moviebot/db/release_variant_repo.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/config.py`
- `src/moviebot/web/app.js`
- `src/moviebot/web/index.html`
- `docker-compose.yml`
- `tests/test_mediaflow_client.py`
- `tests/test_mediaflow_streaming.py`
- `tests/test_browser_stream_verification.py`
- `tests/test_web_search.py`

## Acceptance Criteria

- With the production flag disabled, existing normal-project playback behavior and tests remain unchanged.
- With the flag enabled and MediaFlow healthy, a normal local browser-stream request can select one exact cached catalog variant and receive a browser-playable result through MediaFlow.
- When a title has a verified direct candidate plus other cached variants, the direct candidate remains recommended and state C remains based only on that direct proof; choosing another variant routes only that exact variant through MediaFlow.
- When a title is state B, a successful MediaFlow playback does not promote it to C; the selected variant records MediaFlow verification separately.
- Compatible H.264/AAC MP4/fMP4 playback does not start an unnecessary video encoder; incompatible HEVC/audio fixtures use the expected MediaFlow transcode decision and positively recorded accelerator evidence.
- The browser receives neither the raw provider URL nor the MediaFlow API password in response bodies, URLs, headers, persisted state, browser-visible errors, or logs.
- Unsafe or unverifiable vendor HLS manifests are rejected before browser delivery and use the existing encrypted direct-transcode fallback or a structured failure with local VLC fallback.
- A failed or unhealthy MediaFlow dependency fails closed to the existing safe path; it does not silently label a source browser-ready or expose a provider URL.
- A missing, stale, mismatched, uncached, or quality-gate-rejected `release_variant_id` fails with a structured error before MediaFlow receives a source.
- Disconnect, seek, source replacement, timeout, and shutdown leave no obsolete MediaFlow/FFmpeg/PyAV worker, GPU session, upstream connection, or temporary segment beyond the documented cleanup deadline.
- The normal project player reports the selected delivery decision, output codecs, accelerator, and fallback reason using sanitized data; it does not expose provider internals.
- A configuration-only rollback disables the adapter and restores the previous normal-project playback route without code changes or data migration.
- Fixture-backed integration tests cover disabled mode, healthy MediaFlow, exact variant selection, direct-preference preservation, B remaining B after MediaFlow success, health failure, full transcode, unsafe HLS fallback, secret exclusion, source replacement, and cleanup.
- One separately authorized live browser canary passes only after fixture-backed tests pass; its evidence is recorded without raw URLs, credentials, or private command arguments.
- Blocks 5-6 and 5-7 remain unchanged by this block.

## Verification

- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_mediaflow_client.py tests\test_mediaflow_streaming.py tests\test_browser_stream_verification.py -q --basetemp scratch\pytesttmp-block-5-5c`
- Add deterministic fake-backed tests for feature-flag off/on, MediaFlow health failure, safe HLS fallback, opaque browser responses, and lifecycle cleanup.
- `docker compose --env-file .env.example --profile mediaflow-pilot config`
- Verify the pinned MediaFlow health endpoint from localhost without printing credentials.
- Exercise the normal player with local fixtures for direct play, HEVC/audio transcode, seeking, source replacement, and subtitle playback.
- Scan fresh MediaFlow and application logs for credential/source-URL patterns by count only; do not print raw logs.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5c-full`
- `node --check src\moviebot\web\app.js`
- `git diff --check`
- Restart only `media-bot` through PM2 after source changes and verify the status/health endpoint reports the adapter state. Do not trigger a broad live provider or prewarm cycle.
