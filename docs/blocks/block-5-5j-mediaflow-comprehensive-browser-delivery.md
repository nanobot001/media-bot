# Block 5-5j: MediaFlow Comprehensive Browser Delivery

> Status: In progress; child 5-5j-1 implemented on 2026-08-30.
> Result: Not implemented.
> Notes: Successor program to Blocks 5-5c and 5-5i. Diagnostics and admission evidence are implemented; segmented production, seek ownership, release-class/HDR coverage, and alternate-version fallback remain.

## Goal

Provide one compatibility-first browser-delivery strategy for every known movie release shape. Each exact cached variant must be classified into direct play, remux, audio-only transcode, segmented video transcode, subtitle conversion/burn, verified HDR handling, alternate cached variant, or external-player fallback. The system must either play reliably or explain precisely why it cannot; it must not fail as an opaque stall.

## Authority And Compatibility

- Explicit user requirements define the outcome.
- `docs/project-charter.md`, tool/privacy contracts, exact-variant identity, direct-play C truth, and movie eligibility remain locked constraints.
- Blocks 5-5c and 5-5i remain historical; this program supersedes only their documented limitations.
- Production MediaFlow remains localhost-only, authenticated, version-pinned, and configuration-rollback capable.

## Scope

- Cover MP4/M4V/MKV and other probed containers; H.264/AVC, HEVC/H.265, 8/10-bit, AV1/VP9 and other unsupported source codecs; stereo and multichannel AAC/MP3/AC3/EAC3/DDP/DTS/TrueHD-class audio; text and bitmap subtitles; SDR, HDR10/HLG, and Dolby Vision evidence; multiple selectable tracks; and exact-file selection for multi-file releases.
- Route each variant to the cheapest proven browser-safe path. Preserve direct/remux and audio-only paths while using segmented fMP4/HLS or an equivalent incremental path for heavy video work.
- Add startup, idle-output, session, seek, cancellation, and cleanup supervision. Healthy output must survive beyond a fixed request timeout; stalled or superseded work must stop deterministically.
- Use measured, versioned admission evidence and active reservations. File size alone must not decide capability, and stale decisions must be distinguishable from current decisions.
- Make diagnostics first-class and configurable as `off`, `summary`, or `detailed`. Even `off` retains a minimal sanitized code and stage so playback truth never becomes opaque.
- Show a user-readable reason, retryability, and safe next action. When the selected release cannot play, prefer another exact cached variant with a proven route before offering the external player.
- Preserve structured events and expose bounded localhost diagnostics without raw provider URLs, magnets, passwords, tokens, headers, private paths, or command lines.

## Child Sequence

1. **5-5j-1: Diagnostics And Admission Evidence** — versioned structured errors, configurable visibility, persisted sanitized evidence, and dashboard/API explanations.
2. **Segmented Producer And Supervision** — incremental fragments, startup/idle deadlines, backpressure, and sustained-output verification.
3. **Seek, Cancellation, And Cleanup** — producer ownership, supersession, random access, and deterministic release of workers/reservations.
4. **Release-Class Matrix And HDR Policy** — fixture-backed routing for codec/container/audio/subtitle/HDR combinations.
5. **Automatic Alternate-Variant Fallback** — bounded safe failover with explicit user-visible release identity and reason.

Only the selected child may be implemented at one time. Later child files should be created when their predecessor has verified evidence.

## Out Of Scope

- TV or TV Classic rollout before the movie path is verified.
- Replacing MediaFlow or migrating to an unrelated major vendor version.
- Changing canonical availability A/B/C, movie quality eligibility, passive caching ownership, or download behavior.
- Claiming every release must play in-browser; unsupported or over-capacity variants must fail clearly and offer a safe alternative.
- Live provider playback without separate operator authorization.

## Likely Files Or Areas

- `docker/mediaflow-audio-stereo/`
- `docker-compose.yml`
- `src/moviebot/core/mediaflow_*.py`
- `src/moviebot/adapters/mediaflow_client.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/web/app.js`
- `src/moviebot/web/index.html`
- `src/moviebot/config.py`
- `tests/test_mediaflow_*.py`
- `tests/test_web_ui_endpoints.py`

## Program Acceptance Criteria

- Every known movie release class has deterministic fixture coverage and one truthful route or fallback.
- Heavy playback emits continuing fragments beyond 120 seconds, exposes full duration, and supports early/middle/late random seeking without leaving an obsolete producer.
- Admission reports the exact sanitized measurements, profile/version, budget, and reasons used; stale results cannot masquerade as current capability.
- Startup timeout, idle stall, capacity busy, policy rejection, browser failure, seek failure, disconnect, and cleanup are distinct structured outcomes.
- The local dashboard and trusted-read diagnostics route explain recent failures and safe next actions according to the configured visibility mode.
- Direct-play preference, exact-variant identity, A/B/C truth, feature-flag rollback, and secret isolation remain unchanged.

## Verification Strategy

- Deterministic fake-backed tests for every child before any live provider canary.
- Full non-MCP regression suite after each completed child.
- Docker Compose validation and custom-image tests for vendor-side children.
- Local browser fixture checks for sustained playback, seeking, cancellation, source switching, and truthful fallback messages.
- A real-release canary only after separate authorization and after fixture gates pass.
