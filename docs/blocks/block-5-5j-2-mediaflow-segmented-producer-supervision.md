# Block 5-5j-2: MediaFlow Segmented Producer And Supervision

> Status: Implemented and verified locally on `codex/block-5-5j-2-segmented-producer`.
> Result: Heavy movie transcodes use an opaque on-demand HLS segment gateway with byte-evidence startup/idle supervision, bounded metadata, and Chromium playback through vendored HLS.js 1.7.1.
> Notes: Second child of Block 5-5j. Implementation commit `640d6ed` passed the deterministic 135-second fixture and repository verification gates. The active custom MediaFlow container was subsequently recreated, PM2 `media-bot` alone was restarted, and the sanitized status/dashboard smoke passed. No live provider canary is claimed.

## Goal

Deliver heavy MediaFlow movie transcodes as continuously advancing browser-safe segments under explicit startup and idle-output supervision. Healthy work must continue beyond the old 120-second worker boundary, while a producer that never starts or stops emitting output must fail with a precise diagnostic and release its reserved capacity.

## Scope

- Add one supervised segmented-producer lifecycle for video-reencode delivery decisions such as `full_transcode` and `subtitle_burn`.
- Preserve the exact eligible release variant and private unlocked source while exposing only opaque localhost session, manifest, and segment references to the browser.
- Track producer state, startup deadline, last-output time, bounded segment inventory, terminal reason, and sanitized progress metrics.
- Distinguish configuration, producer startup, upstream source, idle-output stall, capacity, and terminal encoder failures in structured diagnostics.
- Keep the producer alive while output advances instead of allowing a fixed web-worker timeout to terminate healthy long playback.
- Apply bounded backpressure and cleanup to terminal or disconnected producers without claiming random-seek ownership reserved for the next child.
- Preserve direct play, remux, audio-only transcode, external-player fallback, exact-variant identity, eligibility, A/B/C truth, and feature-flag rollback.

## Out Of Scope

- Arbitrary early/middle/late seeking, producer supersession, and complete disconnect cleanup; those belong to Block 5-5j-3.
- Broad codec/container/audio/subtitle/HDR classification changes; those belong to Block 5-5j-4.
- Automatic alternate cached-variant fallback; that belongs to Block 5-5j-5.
- TV or TV Classic rollout, database migrations, dependency replacement, or a MediaFlow major-version migration.
- Live provider playback without separate operator authorization.

## Likely Files Or Areas

- `docker/mediaflow-audio-stereo/`
- `docker-compose.yml`
- `src/moviebot/adapters/mediaflow_client.py`
- `src/moviebot/core/mediaflow_adapter.py`
- `src/moviebot/core/mediaflow_diagnostics.py`
- `src/moviebot/api/web_routes.py`
- `tests/test_mediaflow_*.py`

## Acceptance Criteria

- A deterministic local movie fixture longer than 130 seconds emits an initial playable manifest and media segment within the configured startup deadline, then continues adding playable segments beyond 120 seconds without a worker restart.
- Output progress is measured from produced media evidence, not merely an open HTTP request or running process.
- A producer that emits no initial media fails as `MEDIAFLOW_PRODUCER_STARTUP_TIMEOUT`; one that starts and then stops advancing fails as `MEDIAFLOW_PRODUCER_IDLE_TIMEOUT`.
- Startup and idle failures include sanitized current diagnostics, terminate the affected producer, and release its capacity reservation without making unrelated MediaFlow sessions unavailable.
- Segment retention and in-memory producer metadata remain bounded by explicit configuration and tests.
- Existing direct/remux/audio-only routes and current dashboard diagnostics remain regression-covered and unchanged.
- Provider URLs, magnets, passwords, tokens, headers, private paths, command lines, and raw encoder output are absent from public API and event projections.

## Verification

- `.venv\Scripts\python.exe -m pytest tests\test_mediaflow_segmented_producer.py tests\test_mediaflow_production_adapter.py tests\test_mediaflow_client.py -q`
- `.venv\Scripts\python.exe -m pytest -q`
- `docker compose --env-file .env.example --profile mediaflow-pilot config --quiet`
- Run the deterministic local long-duration fixture and assert playable output before the startup deadline, increasing segment evidence beyond 120 seconds, bounded retention, and clean terminal state.
- `.venv\Scripts\python.exe -m py_compile <changed Python modules>`
- `node --check src\moviebot\web\app.js` when the browser contract changes.
- `git diff --check`

## Implemented Evidence

- The pinned MediaFlow 2.4.9 image now advertises segmented HLS and carries forced AAC-stereo intent through playlist, segment, handler, and universal-pipeline boundaries. The exact image patch built successfully from its digest-pinned base.
- Media-bot fetches the private MediaFlow VOD playlist server-side, retains private targets only in the short-lived registry, and exposes an opaque localhost manifest plus opaque init/media segment routes. Manifest and segment reads are incrementally byte-bounded.
- Chromium receives vendored HLS.js 1.7.1 from the existing local static application. Native-HLS capability remains separate, so segmented support changes only heavy `full_transcode` and `subtitle_burn` routing; direct, remux, and audio-only decisions retain their prior behavior.
- Initialization metadata does not count as producer progress. The first actual media segment proves startup; later media requests use the idle-output deadline. A terminal segment failure records its sanitized code/stage, closes only that session, and releases only its reservation.
- The deterministic local fixture was 135.021 seconds with 27 media segments. Segment `s000000` produced 188,686 bytes in 0.093 seconds; segment `s000024`, beginning at 120.0 seconds, produced 187,734 bytes in 0.110 seconds. The public manifest remained opaque and the MediaFlow worker PID remained `21314` before and after the proof.
- Focused MediaFlow/browser/image-patch verification passed 54 tests; the final repository-wide suite passed 443 tests.
