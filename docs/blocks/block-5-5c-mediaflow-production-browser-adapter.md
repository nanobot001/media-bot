# Block 5-5c: MediaFlow Production Browser-Stream Adapter

> Status: Implemented with a live-canary limitation on 2026-08-29.
> Result: Implemented with bounded runtime proof; exact provider/title browser playback remains separately unverified.
> Verification: 46 focused tests, 402 full non-MCP tests, and 19 MCP tests passed. JavaScript syntax, Python compilation, Docker Compose configuration, the pinned custom MediaFlow image build and activation, and `git diff --check` passed. A real local HEVC plus AAC 5.1 fixture requested at 6 seconds produced H.264 plus AAC stereo fMP4 with video start 6.000s and total duration about 12.01s from the active custom image; the sanitized app status reported the adapter enabled, healthy, pinned, and stereo-capable.
> Notes: The production adapter is disabled by default and fails closed. It accepts only an exact eligible cached catalog variant, returns an opaque local playback session, persists MediaFlow delivery evidence separately from A/B/C, and cleans up bounded sessions on lifecycle events and shutdown. The bounded MediaFlow adaptation forces multichannel AAC downmix when stereo is required and advertises that capability through health. For forward-only `transcode_stream`, browser timeline clicks/drags now debounce and reprepare the same opaque session at the requested time; the pinned image skips pre-target packets, preserves the absolute fMP4 timeline, and reports remaining duration so the browser timeline stays truthful. No live AllDebrid/provider canary was run; exact Toy Story playback, subtitle behavior, and broad worker/GPU cleanup remain separately authorized operator work.
> UI visibility follow-up (2026-08-29): Added an always-visible `MediaFlow On` / `MediaFlow Off` / `MediaFlow Error` indicator to the fixed runtime status bar after live debugging showed that the exact-version action sat below the first viewport inside movie details. JavaScript syntax, 19 focused web/adapter tests, `git diff --check`, PM2 restart, and a 382x920 live viewport check passed.
> Timeline-seeking follow-up (2026-08-29): Native video timeline clicks/drags and arrow-key seeks now use a 250ms debounce, abort the forward-only response, call the localhost-only seek route, and rotate the signed URL without re-unlocking the provider source. A local non-indexed HEVC plus AAC 5.1 fixture confirmed the 6-second suffix/timeline behavior and stereo output. Exact provider-backed browser confirmation remains pending.
> Duration-propagation follow-up (2026-08-29): The pinned universal pipeline now accepts the authoritative source duration from the handler’s MKV/ffprobe metadata for initial fMP4 `mvhd`/track metadata; seek requests retain the remaining-duration override. This addresses long HEVC/DTS files whose PyAV stream-level duration is absent or unreliable. Focused tests, active-image initial-duration and 6-second-seek fixture checks, PM2 restart, and sanitized healthy status passed; the exact provider-backed browser canary remains pending.
> Frontend cache-invalidation follow-up (2026-08-29): The cockpit now revalidates `/`, `/index.html`, and `/app.js`, and the script cache key advanced to `v=37`, preventing an existing stale asset key from hiding the timeline-seeking handler on the next page load. The focused web UI suite (11 tests), JavaScript syntax check, and diff check passed; an existing open tab still requires reload.
> Capacity-admission follow-up (2026-08-30): High-cost video transcodes (`full_transcode` and `subtitle_burn`) now fail closed before MediaFlow URL generation when the observed source exceeds configurable size or duration guardrails, returning a sanitized external-player/alternate-release message instead of starting a stream likely to stall. Defaults are 6 GiB and 7200 seconds; 48 focused MediaFlow/web tests, Python compilation, and diff checks passed. The pinned vendor worker timeout and full segmented-streaming redesign remain follow-up work.

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

- Building a replacement transcoding service or maintaining a general MediaFlow fork; this block permits only the bounded pinned-image adaptation required to honor the existing stereo contract.
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
- `docker/mediaflow-audio-stereo/Dockerfile`
- `docker/mediaflow-audio-stereo/patch_mediaflow_audio.py`
- `tests/test_mediaflow_client.py`
- `tests/test_mediaflow_streaming.py`
- `tests/test_browser_stream_verification.py`
- `tests/test_mediaflow_production_adapter.py`
- `tests/test_mediaflow_audio_stereo_patch.py`
- `tests/test_web_search.py`

## Acceptance Criteria

- With the production flag disabled, existing normal-project playback behavior and tests remain unchanged.
- With the flag enabled and MediaFlow healthy, a normal local browser-stream request can select one exact cached catalog variant and receive a browser-playable result through MediaFlow.
- When a title has a verified direct candidate plus other cached variants, the direct candidate remains recommended and state C remains based only on that direct proof; choosing another variant routes only that exact variant through MediaFlow.
- When a title is state B, a successful MediaFlow playback does not promote it to C; the selected variant records MediaFlow verification separately.
- Compatible H.264/AAC MP4/fMP4 playback does not start an unnecessary video encoder; incompatible HEVC/audio fixtures use the expected MediaFlow transcode decision and positively recorded accelerator evidence.
- When the app requires stereo and the selected audio stream has more than two channels, the adapter sends an explicit stereo-downmix request only when the pinned MediaFlow health contract advertises `force_audio_stereo`; a missing capability fails closed before MediaFlow receives the source.
- The pinned custom MediaFlow adaptation applies that request to the universal transcode path, including AAC multichannel input, and a real local HEVC plus AAC 5.1 fixture produces H.264 video with AAC stereo output.
- For forward-only `transcode_stream`, clicking or dragging the browser timeline calls a bounded localhost-only seek route that reuses the existing private source, rotates the signed playback URL, and does not re-unlock the provider.
- The seeked fMP4 preserves the requested absolute timeline position and exposes the remaining duration; packet data before the target is skipped even when the source has no usable later cue index.
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
- `docker compose --env-file .env --profile mediaflow-pilot build mediaflow-proxy`
- Verify the pinned MediaFlow health endpoint from localhost without printing credentials.
- Exercise the normal player with local fixtures for direct play, HEVC/audio transcode, seeking, source replacement, and subtitle playback. The local HEVC plus AAC 5.1 fixture requested at 6 seconds produced H.264 plus AAC stereo with a 6.000-second video start and about 12.01 seconds total duration through the active custom image; no provider-backed title canary was rerun.
- Scan fresh MediaFlow and application logs for credential/source-URL patterns by count only; do not print raw logs.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5c-full`
- `node --check src\moviebot\web\app.js`
- `git diff --check`
- Restart only `media-bot` through PM2 after source changes and verify the status/health endpoint reports the adapter state. Do not trigger a broad live provider or prewarm cycle.
