# Block 5-5: Authoritative Browser-Stream Verification

> Status: In progress (implementation and automated/runtime gates complete; live Chrome canary pending).
> Result: Implementation complete; live canary pending.
> Verification: 327 tests passed (excluding `tests/test_mcp_server.py`), `ffprobe` available, `node --check` passed, diff check passed, and only `media-bot` was restarted and smoke-tested through PM2/API. The non-MCP full run has one shared-default-database lifecycle failure (`total_cached` observed as 3 instead of the test's clean-state 0); MCP collection remains blocked by the installed MCP 2.x/legacy FastMCP mismatch. Chrome playback/audio evidence is pending because the Codex Chrome extension/native host is unavailable on this host.
> Notes: First block in the Phase 5 stream-readiness hardening sequence; complete this before changing pre-warm throughput or scoreboard semantics.

> Update 2026-08-26: Discovery now reconciles exact verified browser copies stored under release-label rows and exposes the selected browser-stream copy separately from the download copy, including parsed container, codec, audio, size, and verification-source details.

## Goal

Eliminate browser-readiness false negatives caused by incomplete indexer titles while preserving conservative identity and codec safety. Cached releases may be considered probeable from indexer metadata, but only authoritative AllDebrid file evidence may earn the browser-ready state and lightning action.

The motivating regression is `Scary Movie` (2026): the indexer title `Scary Movie (2026) [1080p] [WEBRip] [5.1]` lacks codec and container tags, while the actual AllDebrid file is an MP4 with x264 video and AAC audio. The current prefilter rejects the release before inspecting that authoritative filename.

## Dependencies

- The current worktree's separate cached-download and browser-stream readiness fields.
- The manual `cloud_transfer_intents` ownership boundary and `POST /api/stream/prepare` route.
- `ffprobe` available on the host PATH; do not add a Python or JavaScript media-probing dependency.

## Scope

- Replace the single strict indexer-title gate with three internal classifications:
  - `explicitly_incompatible`: reject listings that positively advertise an unsupported container, HEVC/x265/H.265, AV1, 10-bit video, or unsupported audio.
  - `probeable`: retain exact-identity cached listings whose codec/container/audio metadata is incomplete but not explicitly incompatible.
  - `verified_browser_ready`: grant only after authoritative file verification.
- Preserve exact movie title and year matching and exact TV season/episode matching before probing. A compatible file for the wrong sequel, remake, special, or making-of feature must not be promoted.
- For an on-demand request, rank exact cached candidates and inspect at most the best three, stopping after the first verified candidate.
- Inspect the actual AllDebrid file tree and selected filename before applying the strict MP4/M4V + H.264/AVC + AAC/MP3 rule.
- When the actual filename remains ambiguous, run one bounded `ffprobe` process at a time against the unlocked URL:
  - timeout after 20 seconds;
  - inspect metadata only, never intentionally download the full media file;
  - require an MP4-family container, H.264/AVC video, and AAC/MP3 audio;
  - record a structured timeout/probe error and leave the item unverified on uncertainty.
- For the explicitly authorized live canary, open the first authoritative verified unlocked URL in the Chrome/player path and run a bounded 5-10 second playback check:
  - require media metadata to load and unmuted playback to reach `playing`;
  - require an allowed audio track to be present and produce non-zero decoded audio samples through a browser-side Web Audio check;
  - record browser playback and audio evidence without claiming that physical speakers or OS volume were tested.
- Persist successful Search/player verification into the exact Discovery media record using upsert semantics when no `prewarmed_cache` row exists. A successful verified playback must not be lost merely because the title was never pre-warmed.
- Store enough durable verification identity to reuse the result safely: exact media identity, selected reference/infohash, selected file ID when available, actual filename, evidence source, and verification timestamp.
- Treat verified readiness as seven-day evidence while continuing the existing cheap AllDebrid cache-availability recheck. Cache loss clears browser readiness immediately.
- Implement ownership-aware temporary probe cleanup:
  - inspect existing provider state before submitting the cached magnet;
  - delete only an AD entry proven to have been created by this probe;
  - never delete a pre-existing entry, a `cloud_transfer_intents` entry, a manual request, or an active stream entry;
  - cleanup failure is structured and retryable, not a reason to delete another candidate.
- Preserve structured JSON route responses, dry-run behavior, obfuscated magnet boundaries, event/error recording, and Python 3.12/PM2 runtime behavior.

## Out Of Scope

- Increasing frontier batch sizes or changing the six-hour cycle; Block 5-6 owns scheduling and throughput.
- Changing milestone values, tier advancement, or scoreboard presentation; Block 5-7 owns those semantics.
- Caching an uncached release during passive prewarming.
- Treating successful URL resolution, `player_type="web"`, or a filename alone as proof when required codec fields remain ambiguous.
- Loosening exact title/year or TV episode identity safeguards.
- Streaming every candidate or every library file, or treating physical speaker output as a required codec proof.

## Likely Files Or Areas

- `src/moviebot/core/release_parser.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/adapters/alldebrid_client.py`
- `src/moviebot/db/cache_prewarm_repo.py`
- `src/moviebot/db/connection.py`
- `tests/test_browser_stream_prepare.py`
- `tests/test_stream_unlock.py`
- `tests/test_web_search.py`

## Acceptance Criteria

- The incomplete `Scary Movie (2026) [1080p] [WEBRip] [5.1]` listing remains probeable rather than being rejected before AD inspection.
- Its actual `Scary.Movie.2026.1080p.WEBRip.x264.AAC5.1-....mp4` file is verified and persisted as browser-ready for `Scary Movie` (2026).
- A cached HEVC/x265/MKV/DDP candidate remains download-ready or external-player-ready and never receives browser-ready status.
- A compatible file for a wrong-year sequel or adjacent title is never promoted.
- An ambiguous actual MP4 filename is probed with the bounded `ffprobe` fallback; timeout, missing audio, or unsupported codecs remain unverified.
- The explicitly authorized `Scary Movie` (2026) canary opens the identified stream in Chrome/player, reaches metadata and `playing`, and confirms that its allowed audio track produces decoded samples; muted autoplay, missing audio, or absent decoded audio fails the canary.
- A verified stream opened from Search creates or updates the exact Discovery readiness record even when no prewarm row existed.
- Repeated verification reuses fresh durable evidence instead of repeating AD file inspection or `ffprobe`.
- Temporary AD cleanup occurs only with positive probe ownership evidence; tests prove that pre-existing and manual entries cannot be deleted.
- Passive verification creates no Cloud Transfer card or completion notification.
- Existing unrestricted Search/IDM behavior remains unchanged.

## Verification

- `Get-Command ffprobe`
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_browser_stream_prepare.py tests\test_stream_unlock.py tests\test_web_search.py -q --basetemp scratch\pytesttmp-block-5-5`
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5-full`
- `node --check src/moviebot/web/app.js`
- `git diff --check`
- Restart only `media-bot` through PM2 and verify `http://localhost:8000/` plus the relevant read APIs.
- Run one explicitly authorized, ownership-guarded live canary for `Scary Movie` (2026). Record the selected listing, authoritative filename or probe result, exact persisted media identity, Chrome/player metadata and playback result, decoded-audio result, and evidence that no pre-existing/manual AD entry was deleted.
