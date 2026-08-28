# Block 5-5b: MediaFlow Browser Transcoding Capability Pilot

> Status: Implemented with limitations on 2026-08-27.
> Result: Implemented with limitations; pilot decision: `adopt_with_bounded_adapter`.
> Verification: `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_mediaflow_client.py tests\test_mediaflow_streaming.py tests\test_mediaflow_pilot_page.py -q` - 24 passed; the page is served at `/mediaflow-pilot.html`; Compose configuration passes; the deterministic fixture matrix covered direct-play, remux, audio-only, full-transcode, text-subtitle, and HDR reject/tone-map decisions; software remux/transcode/HLS outputs decoded cleanly. The pinned Linux/amd64 source manifest was verified as `sha256:3b8e30f246ced9c61b4f9e4cd4aeb99b860b23b15f85a3c6d5c711dccbf1ce97`; the assembled local image is `sha256:3b7056ca827cc4eb89bd94c0b622e74bf10ae876298f35eddb419b2b18461dd5`, and the container is healthy on `127.0.0.1:8888`. The operator confirmed the pilot playback, seek, source-switch, and subtitle checks; the supplied run showed direct `200`, HEVC-to-H.264 NVENC, EAC3-to-AAC, and completed subtitle-fixture output, with no timeout or SIGKILL in that excerpt. Full regression had 345 passed and 1 pre-existing failure.
> Notes: The client preflights HLS and falls back to encrypted direct transcode when the v2.4.9 playlist leaks source/password query parameters or cannot be validated. The bounded adapter is pilot-only and preserves localhost binding, authentication, URL secrecy, and the existing VLC fallback; it does not authorize production route replacement. A real bitmap-subtitle fixture and independently recorded reconnect, resource-cleanup, HDR visual-quality, range, and browser decoded-sample evidence remain limitations for a later bounded hardening follow-up.

## Goal

Determine whether a pinned, locally hosted MediaFlow Proxy container can securely and reliably turn an authorized AllDebrid VOD source into a Chrome-playable stream while preserving direct-play efficiency, explicit track selection, robust seeking, network recovery, and process cleanup. Finish with an evidence-backed `adopt`, `adopt_with_bounded_adapter`, or `reject` decision before changing prewarming or scoreboard semantics.

Block completion means the capability matrix was exercised and the decision was recorded. It does not require adopting MediaFlow when a mandatory gate fails.

## Dependencies

- Merged Block 5-5 authoritative file verification, durable browser/download candidate identity, and local VLC fallback.
- Docker Desktop with the NVIDIA container runtime available on the local host.
- Host `ffprobe`/`ffmpeg` for independent metadata and output checks.
- Explicit authorization before unlocking or streaming any live AllDebrid source.
- Current MediaFlow documentation for [browser transcoding and seeking](https://github.com/mhdzumair/mediaflow-proxy/blob/main/docs/usage/url-params-and-encoding.md) and [Docker installation](https://github.com/mhdzumair/mediaflow-proxy/blob/main/docs/installation.md).

## Success Definition

- The pilot is successful as an evaluation when every required row is tested, evidence is recorded without secrets, and one adoption decision is made.
- MediaFlow may be marked `adopt` only when all mandatory capability, security, lifecycle, and operator-playback gates pass.
- Use `adopt_with_bounded_adapter` only when the missing behavior is explicitly scoped for a later Block 5-5c and does not weaken URL secrecy, cleanup, source identity, or fallback safety.
- Use `reject` when a mandatory capability cannot be proven reliably or would require building a substantial custom transcoding server.

## Scope

### Isolated Docker Pilot

- Add a pinned MediaFlow Proxy service without changing the existing Prowlarr or FlareSolverr services.
- Bind the pilot to `127.0.0.1` only, require an API password from environment configuration, and use short-lived encrypted/signed playback URLs.
- Record the exact image version or digest used. Do not use an unrecorded floating `latest` image for acceptance evidence.
- Enable NVIDIA GPU access for the local GTX 1060 and retain a controlled CPU fallback for diagnostic comparison.
- Add health, readiness, inactivity-timeout, concurrency, temporary-segment, and resource-limit configuration appropriate for a single-user pilot.

### Deep Stream Inventory

- Run one bounded metadata probe per selected source and return a structured, non-sensitive inventory containing:
  - container and format names;
  - duration and seekability;
  - every video stream's index, codec, profile, level, width, height, frame rate, pixel format, bit depth, color primaries, transfer characteristics, color space, and HDR/Dolby Vision indicators when detectable;
  - every audio stream's index, codec, language, title, channel count/layout, sample rate, bitrate, and default/forced disposition;
  - every subtitle stream's index, codec, language, title, text/bitmap classification, and default/forced disposition.
- Never persist or return the raw AllDebrid URL, authorization headers, API password, or FFmpeg command containing those values.
- Use stable stream indexes from the probe as the selection contract for audio and subtitle tracks.

### Smart Delivery Decision Matrix

For each request, produce one structured decision and a human-readable reason:

| Decision | Required behavior |
| --- | --- |
| `direct_play` | Use the existing direct browser path for an already compatible MP4/fMP4 H.264 8-bit + AAC/MP3 source. |
| `remux_copy` | Repackage compatible elementary streams without video or audio re-encoding when only the container/delivery shape is incompatible. |
| `audio_transcode` | Copy compatible H.264 video and transcode only incompatible audio such as AC3/EAC3/DTS/TrueHD to AAC. |
| `full_transcode` | Transcode incompatible video such as HEVC/H.265, HEVC 10-bit, VC-1, AV1, unsupported H.264 pixel formats, or unsupported HDR output to browser-safe H.264 8-bit, with AAC audio. |
| `subtitle_burn` | Burn the explicitly selected bitmap subtitle into video, which necessarily forces video transcoding. |
| `external_fallback` | Explain the unsupported or failed capability and preserve `Open in local VLC`; never label the source browser-ready. |

- Prove the selected path from MediaFlow/FFmpeg process evidence or structured metrics; do not infer stream copy or GPU use merely from successful playback.
- Do not transcode a compatible source unnecessarily.
- Detect HDR10/Dolby Vision and either preserve a browser-supported HDR path, produce a verified SDR tone-map, or reject/fallback explicitly. Washed-out or silently clipped HDR output fails the gate.

### Remote HTTP Resilience

- Reuse upstream HTTP connections where supported and apply bounded reconnect behavior equivalent to FFmpeg's `reconnect`, `reconnect_streamed`, network-error/selected-HTTP-error recovery, read timeout, retry-count, maximum-delay, and total-delay controls.
- Do not enable `reconnect_at_eof` for finite AllDebrid VOD by default; reserve EOF reconnection for a separately identified live/endless source.
- Test one controlled mid-stream upstream disconnect and prove recovery or a bounded, structured failure without a broken pipe, leaked secret, or orphan process.

### Seeking And Delivery

- Use HLS VOD with fMP4 `init.mp4`/`.m4s` segments as the preferred browser-transcode path unless evidence supports a better delivery mode.
- Evaluate direct fragmented MP4 for the explicit start-time path and fallback scenarios.
- For direct transcode start requests, seek at the input before full demux/decode where the vendor supports it; record that indexed MKV/MP4 seeking is nearest-keyframe plus any accurate-seek decode, not guaranteed frame-exact stream-copy seeking.
- Test initial playback, forward seek, backward seek, and source replacement without downloading the full file first.
- Verify HLS manifest/segment MIME types, cache headers, bounded segment retention, and browser playback.
- Verify `206 Partial Content`, `Content-Range`, and correct byte boundaries on routes where byte-range delivery applies. Do not require arbitrary range semantics from normal HLS segment fetches.

### Audio And Subtitle Tracks

- Provide a minimal pilot selector or test harness that chooses an audio stream by stable index and exposes language, codec, and channel layout before playback.
- Copy compatible AAC when safe; otherwise transcode the selected track to AAC.
- Support an explicit stereo or 5.1 AAC target and test downmixing from 5.1/7.1 TrueHD, DTS/DTS-HD MA, or another available surround fixture without silent channels or clipping.
- Extract a selected text subtitle (SRT/ASS/SSA or equivalent) and convert it to WebVTT for native HTML5 `<track>` playback, preserving timestamps and language metadata.
- Detect PGS/VobSub and other bitmap subtitles. When selected, burn the track through an FFmpeg video filter and make the forced full-transcode decision transparent.
- Do not silently choose or burn a subtitle track. No-subtitle playback must remain available.

### Browser Playback And Transparency

- Use a minimal local pilot page or test harness; do not build the final production UI in this block.
- Display the authoritative source inventory, selected audio/subtitle streams, decision (`direct_play`, `remux_copy`, `audio_transcode`, `full_transcode`, `subtitle_burn`, or `external_fallback`), output codecs, accelerator, and fallback reason.
- Verify Chrome reaches metadata and `playing`, displays moving video, and produces decoded unmuted audio. Record operator-heard audio separately from browser decoded-sample telemetry.
- Keep `Open in local VLC` available for every source for which a direct provider URL is safely available.

### Process And Resource Lifecycle

- Associate each playback request with a server-side session identifier that does not expose the upstream URL.
- On browser disconnect, seek, source replacement, timeout, or container shutdown, terminate obsolete FFmpeg/PyAV/pipe workers and their descendants.
- Prove that repeated seek/source-change operations do not accumulate workers, open upstream connections, GPU sessions, or temporary segments.
- Enforce a small pilot concurrency limit, inactivity timeout, bounded temporary storage, and deterministic segment/session cleanup.
- Record first-frame latency, seek-resume latency, input/output codecs, chosen decision, accelerator, CPU/GPU utilization, reconnect count, exit reason, and cleanup result without recording secrets.

## Capability Canaries

- **Direct-play control:** Use the already verified `Scary Movie` MP4/H.264/AAC browser copy, or an equivalent deterministic fixture, and prove no unnecessary encoder is started.
- **Full-transcode canary:** Probe `Obsession` as a candidate only if its authoritative selected file actually proves an incompatible video/audio format. Otherwise select another explicitly authorized cached HEVC 10-bit plus EAC3/DTS source. Prove Chrome video, decoded audio, and GPU encoder use.
- **Audio-only canary:** Use H.264 video with an incompatible surround audio track and prove video copy plus AAC audio conversion/downmix.
- **Text-subtitle canary:** Select an SRT/ASS track and prove WebVTT rendering after a seek.
- **Bitmap-subtitle canary:** Select a PGS/VobSub track and prove transparent forced video transcoding with visible subtitles.
- **Failure canary:** Force one unsupported or interrupted path and prove structured failure, worker cleanup, and local VLC fallback.
- Prefer deterministic local fixtures for automated tests. Any live AllDebrid canary remains separately authorized, bounded, and non-destructive.

## Out Of Scope

- Replacing Media Bot's production stream routes or removing the Block 5-5 direct browser path.
- Building a polished production audio/subtitle selector; the pilot needs only a verifiable harness.
- Writing a custom general-purpose FFmpeg streaming server when MediaFlow lacks a mandatory capability.
- Changing Block 5-6 prewarming budgets, Block 5-7 scoreboard semantics, Discovery tiers, or milestone values.
- Automatically caching uncached media, creating Cloud Transfer cards, or mutating AllDebrid state beyond an explicitly authorized existing stream.
- Exposing MediaFlow outside localhost/LAN, configuring public ingress, or weakening authentication.
- Claiming support for every corrupt, encrypted, DRM-protected, or unusual media file.

## Likely Files Or Areas

- `docker-compose.yml`
- `.env.example`
- `src/moviebot/adapters/mediaflow_client.py`
- `src/moviebot/core/browser_stream_verifier.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/web/app.js`
- `src/moviebot/web/index.html`
- `tests/test_mediaflow_client.py`
- `tests/test_mediaflow_streaming.py`
- `docs/blocks/block-5-5b-mediaflow-browser-transcoding-capability-pilot.md`

## Acceptance Criteria

- A pinned, authenticated, localhost-only MediaFlow container starts without changing the existing Prowlarr/FlareSolverr services and exposes a passing health check.
- The probe contract reports container, duration, seekability, video bit depth/HDR fields, and every audio/subtitle track while excluding URLs, headers, tokens, passwords, and private command arguments.
- Every canary receives exactly one structured decision with evidence proving whether video/audio were copied or transcoded and which accelerator was used.
- The compatible direct-play control starts without a video encoder and remains playable through the existing browser path.
- The incompatible full-transcode canary produces Chrome-playable H.264 8-bit + AAC through HLS/fMP4, reaches `playing`, shows moving video, and produces decoded unmuted audio.
- On the local GTX 1060, NVENC use is positively observed for the full-transcode canary or the pilot records a structured adoption-blocking reason; CPU fallback is not misreported as GPU success.
- The audio-only canary copies H.264 video, converts only the selected surround audio stream to the requested AAC layout, and produces intelligible non-silent output.
- A selected text subtitle is rendered through WebVTT after initial playback and after seeking; a selected bitmap subtitle is visibly burned and reported as a forced video transcode.
- Forward and backward seeks resume without reading the entire source first; the recorded evidence distinguishes nearest-keyframe/segment behavior from frame-exact seeking.
- Applicable direct/fMP4 proxy routes return correct `206 Partial Content` and `Content-Range`; HLS manifests and segments use correct MIME types and remain independently fetchable.
- One controlled upstream interruption either recovers within the configured retry budget or fails structurally; normal finite VOD EOF terminates rather than reconnecting indefinitely.
- Disconnect, seek, source replacement, timeout, and shutdown tests leave no obsolete worker, GPU session, upstream connection, or temporary segment beyond the documented cleanup deadline.
- HDR content is preserved, acceptably tone-mapped, or explicitly rejected; silent color degradation is not accepted.
- Browser responses, persisted state, structured events, logs, and test artifacts contain no raw AllDebrid URL or MediaFlow credential.
- The block completion note records the image version/digest, complete capability matrix, measured startup/seek/resource results, known limitations, and one decision: `adopt`, `adopt_with_bounded_adapter`, or `reject`.
- Blocks 5-6 and 5-7 remain unchanged until that decision is recorded.

## Verification

- `docker compose --env-file .env.example config`
- `docker compose --env-file .env.example --profile mediaflow-pilot config`
- `docker compose --env-file .env --profile mediaflow-pilot up -d mediaflow-proxy`
- `docker compose ps mediaflow-proxy`
- Verify the MediaFlow health endpoint from localhost without printing credentials.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_mediaflow_client.py tests\test_mediaflow_streaming.py -q --basetemp scratch\pytesttmp-block-5-5b`
- Run deterministic fixture-backed direct, remux, audio-only, full-transcode, text-subtitle, bitmap-subtitle, range, reconnect, seek, and cleanup tests.
- Run one separately authorized live browser canary only after fixture-backed gates pass.
- Inspect MediaFlow/FFmpeg worker counts, temporary segment state, `nvidia-smi`, Docker CPU/memory, and structured session events before playback, during playback, after seek/source replacement, and after disconnect.
- `node --check src/moviebot/web/app.js`
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5b-full`
- `git diff --check`
- Restart only `media-bot` if application source changes. Do not restart Prowlarr or FlareSolverr and do not run a broad provider/prewarm cycle.
