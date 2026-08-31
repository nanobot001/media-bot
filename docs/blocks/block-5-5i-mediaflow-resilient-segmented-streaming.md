# Block 5-5i: MediaFlow Resilient Segmented Streaming

> Status: Implemented with limitations on 2026-08-30.
> Result: Implemented with limitations.
> Verification: `53 focused MediaFlow/web tests`, `py_compile`, and `git diff --check` passed.
> Notes: Added calibrated-profile admission and atomic runtime reservations, plus a dashboard heavy-slot indicator and capacity-specific playback error. The vendor-side segmented producer, idle-output supervision, and sustained-fragment verification remain unimplemented and require a separate bounded follow-up.

## Goal

Allow eligible large or expensive cached releases to play through MediaFlow as a sustained browser stream. The system must generate and serve media fragments incrementally, supervise transcoding by startup and idle-output deadlines rather than a fixed total request timeout, preserve accurate duration and seeking, and fail clearly to an external-player or alternate-release path when the current runtime cannot safely carry the workload.

## Dependencies

- Block 5-5b MediaFlow capability pilot and its pinned v2.4.9 image.
- Block 5-5c production browser adapter, opaque sessions, stereo audio contract, duration propagation, seeking, and current capacity guard.
- Docker GPU runtime with the localhost-only MediaFlow profile.
- Local fixture server and fake-backed test conventions; no provider canary is required to implement this block.

## Scope

- Replace the active-stream reliance on one long-lived synchronous transcode response with a session-owned segmented/fMP4 delivery path or an equivalent streaming-safe MediaFlow route.
- Emit the initialization segment and subsequent media fragments incrementally, with bounded buffering/backpressure and no unbounded source or output accumulation in memory or temporary storage.
- Replace the current total worker-timeout failure mode with explicit startup and idle-output supervision. Keep ordinary control/API requests bounded separately.
- Add a capacity admission decision for heavy work based on source metadata and current runtime reservations: codec/bit depth, resolution, duration, source size, audio conversion, subtitle burn, GPU/CPU availability, and active heavy sessions. Preserve configurable guardrails as a fallback, but do not use file size alone as the capability decision.
- Permit at most the documented safe number of heavy transcode sessions; return a retryable structured capacity response when the runtime is busy rather than starting a stream that will compete and stall.
- Preserve opaque local session references, provider-secret isolation, exact variant identity, stereo downmix behavior, absolute duration metadata, and seek behavior. Seeking must cancel or supersede the old segment producer and start from the requested timestamp without re-unlocking the provider source.
- Record sanitized lifecycle evidence for time-to-first-fragment, fragment cadence/output progress, stall reason, capacity decision, seek, disconnect, cancellation, and cleanup. Mark MediaFlow delivery verified only after the browser receives sustained output, not merely after URL preparation or one `playing` event.
- Keep the existing direct/remux path, external-player/VLC fallback, configuration rollback, and A/B/C semantics unchanged.

## Out Of Scope

- Replacing MediaFlow with a new general-purpose transcoding service.
- Removing the pinned-image requirement or migrating the MediaFlow vendor to an unrelated major version.
- Automatic AllDebrid caching, release ranking, catalog rebuilding, or changes to title-level A/B/C semantics.
- A broad queueing platform for every media job; this block may reject excess heavy sessions with a bounded retryable response.
- Broad UI redesign. Only the status, fallback, and playback messages required to make capacity and stall outcomes truthful are included.
- A live provider playback canary before fixture-backed tests and explicit operator authorization.

## Likely Files Or Areas

- `docker/mediaflow-audio-stereo/Dockerfile`
- `docker/mediaflow-audio-stereo/patch_mediaflow_audio.py`
- `docker-compose.yml`
- `src/moviebot/core/mediaflow_adapter.py`
- `src/moviebot/adapters/mediaflow_client.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/web/app.js`
- `src/moviebot/config.py`
- `tests/test_mediaflow_streaming.py`
- `tests/test_mediaflow_production_adapter.py`
- `tests/test_mediaflow_audio_stereo_patch.py`
- `tests/test_web_ui_endpoints.py`

## Acceptance Criteria

- A direct-play or remux-compatible fixture behaves exactly as before and does not reserve a heavy-transcode slot or start a video encoder.
- A long-duration HEVC/10-bit plus multichannel-audio fixture produces an initialization segment and continuing media fragments incrementally; the browser does not depend on the entire movie being transcoded before playback can continue.
- An active stream remains viable past 120 seconds when fragments continue to be produced; the old fixed Gunicorn request timeout cannot terminate a healthy active stream. A stalled producer is stopped by the documented idle-output deadline and reports a structured failure.
- Startup, idle, and session deadlines are independently configurable and covered by deterministic tests. A session that cannot produce its first fragment within the startup deadline fails fast with a sanitized alternate-release/external-player outcome.
- Heavy-transcode admission accounts for source size, duration, video re-encode, bit depth/resolution, audio conversion, subtitle burn, and current reservations. A large file is not rejected solely because of size when its measured delivery path is safe; a smaller but more expensive workload can still be rejected.
- When the heavy-transcode capacity is occupied, a second heavy request does not start a competing MediaFlow job. It returns a retryable structured capacity result without exposing provider details or signed URLs.
- Seeking to early, middle, and late positions cancels or supersedes the previous producer, starts the new segment sequence at the requested position, preserves the absolute timeline and full duration, and leaves no obsolete worker or session producer after cleanup.
- Browser disconnect, modal close, source replacement, timeout, and shutdown terminate the owned producer and release the capacity reservation within the documented cleanup deadline.
- MediaFlow delivery is not marked `verified` from URL preparation or a single browser `playing` event. Verification requires sustained fragment/output progress over the configured observation window; stalls and cleanup are recorded with sanitized reasons.
- Browser responses, logs, events, and errors contain no provider URL, magnet, MediaFlow password, authorization header, private command line, or local secret.
- Existing direct-play preference, external-player/VLC fallback, feature-flag rollback, exact-variant evidence, and title A/B/C state remain unchanged.

## Verification

- `.\.venv\Scripts\python.exe -m pytest tests\test_mediaflow_streaming.py tests\test_mediaflow_production_adapter.py tests\test_mediaflow_audio_stereo_patch.py tests\test_web_ui_endpoints.py -q --basetemp scratch\pytesttmp-block-5-5i`
- Add a deterministic fake producer test for first-fragment timeout, continuous fragments beyond 120 seconds, idle timeout, backpressure, capacity busy, disconnect cancellation, and cleanup.
- Exercise a local long-duration HEVC/10-bit plus multichannel-audio fixture through the active custom image; record first-fragment latency, fragment cadence, duration, seek positions, and cleanup counts without raw URLs or credentials.
- `docker compose --env-file .env.example --profile mediaflow-pilot config`
- `docker compose --env-file .env --profile mediaflow-pilot build mediaflow-proxy`
- `node --check src\moviebot\web\app.js`
- `.\.venv\Scripts\python.exe -m py_compile src\moviebot\core\mediaflow_adapter.py src\moviebot\adapters\mediaflow_client.py`
- `.\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5i-full`
- `git diff --check`
- Restart only `media-bot` after source changes, verify the sanitized adapter health state, and run any live provider canary only after separate authorization.
