# Block 5-5d: Universal Movie Release-Window Quality Gate

> Status: Implemented.
> Result: Implemented on `codex/block-5-5d-universal-movie-quality-gate`.
> Notes: Corrective Phase 5 hardening block completed before the MediaFlow production adapter; no MediaFlow, provider, ranking-weight, or migration changes were made.

## Completion Note (2026-08-27)

- Added a shared fail-closed movie decision with the inclusive 65-day boundary, authoritative TMDb theatrical-date resolution, structured reasons, and secondary CAM/HDTS/TS/telesync/screener-style rejection.
- Applied the decision before candidate ranking, cache preference, pre-warming persistence, title/direct-reference ingest, dry-run ranking, cloud pre-cache, and browser/playback selection. Discovery retains rejected titles only as non-actionable informational results and refreshes cached discovery quality decisions.
- Preserved the existing `score_and_rank_releases` weights and MediaFlow/downstream browser semantics. Rejected diagnostics are sanitized and all action routes recheck the hard gate.
- Added deterministic gate/provider/prewarm coverage and isolated legacy SQLite prewarmer tests from local runtime cache files. No live provider or AllDebrid smoke was run.
- Verification passed: 34 focused block tests, 77 expanded movie/playback tests, and 359 full non-MCP tests; `compileall` and `git diff --check` also passed. Existing FastAPI/Discord deprecation warnings remain.

## Goal

Make the conservative movie release-window policy universal across title discovery, release search, ranking, pre-warming, cache persistence, ingest, and playback-candidate selection. Use the authoritative movie release date versus today as the primary eligibility rule, then preserve the existing point-based ranking system for candidates that pass the gate.

## Policy

- For movies, retain the existing conservative default: a title is not automatically release-eligible until at least 65 days have elapsed since its authoritative theatrical release date.
- The date gate must not depend on the torrent title saying `CAM`, `HDTS`, `TS`, or another recognizable marker.
- Source-name markers remain a secondary rejection layer for poor releases that appear after the release window or use misleading metadata.
- A cached release, high score, browser compatibility, MediaFlow transcode, or explicit reference ID must never override a failed movie quality gate.
- Discovery may show an upcoming or unavailable title as informational evidence, but it must not present it as available, pre-warm it, cache it as an accepted candidate, queue it, or select it for playback.

## Scope

- Create one shared, structured movie eligibility decision containing the gate result and a safe reason such as `RELEASE_WINDOW_NOT_ELIGIBLE`, `LOW_QUALITY_SOURCE`, or `ELIGIBLE`.
- Carry authoritative TMDb movie release-date context into every automatic movie selection path that currently has only a title or year.
- Apply the gate before cached-status preference and candidate winner selection in background pre-warming.
- Apply the gate to normal search presentation, dry-run ranking, title-based ingest, direct-reference ingest, cloud pre-cache, and browser/playback candidate selection.
- Keep raw search evidence available for diagnostics only when it is clearly marked rejected and cannot be recommended or actioned.
- Preserve the existing `score_and_rank_releases` point weights and use them only after hard eligibility filtering.
- Add deterministic tests for titles inside and outside the 65-day window, misleading/absent CAM markers, cached low-quality candidates, direct-reference bypasses, and no-eligible-release outcomes.

## Out Of Scope

- Implementing the TV quality gate in this block; the TV sub-plan below is planning guidance for a separate block.
- Changing the existing point values, cache bonus, browser-readiness semantics, MediaFlow behavior, or AllDebrid APIs.
- Automatically deleting or invalidating existing AllDebrid/provider cache entries or historical database rows.
- Adding an early-digital-release exception to the conservative 65-day rule.
- Broad discovery-frontier, pre-warming-budget, or scoreboard changes from Blocks 5-6 and 5-7.

## TV Follow-Up Sub-Plan

TV must use a separate policy rather than inheriting the movie 65-day rule:

- Use authoritative series/season/episode air-date context; pre-air episodes must not be eligible.
- Define a bounded post-air release grace rule for continuing shows before implementing automatic TV pre-warming or ingest gating.
- Preserve a distinct Classic TV policy for complete libraries and quality upgrades rather than treating classic episodes like newly released movies.
- Reuse the same structured decision shape and hard-before-ranking contract, but use TV-specific season/episode identity, air-date, pack, and episode-file validation.
- Apply the eventual TV gate across TV search, season/episode selection, pre-warming, complete-series fallback, ingest, and playback candidates.
- Add TV-specific tests for pre-air releases, exact aired episodes, season packs, complete-series packs, and quality-upgrade candidates.

## Likely Files Or Areas

- `src/moviebot/core/release_parser.py`
- `src/moviebot/tools/discover_media_tool.py`
- `src/moviebot/tools/search_sources_tool.py`
- `src/moviebot/core/background_prewarmer.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/tools/enqueue_download_tool.py`
- `src/moviebot/db/cache_prewarm_repo.py`
- `tests/test_movie_quality_gate.py`
- `tests/test_web_search.py`
- `tests/test_background_prewarmer.py`
- `tests/test_web_ingest_telemetry.py`

## Acceptance Criteria

- Every automatic movie path uses the same hard eligibility decision before ranking, cache preference, enqueueing, or playback selection.
- A movie inside the 65-day release window cannot become an accepted search winner, pre-warmed record, cloud-cached candidate, ingest target, or playback candidate even when its release title omits all low-quality markers and AllDebrid reports it cached.
- A movie outside the window can proceed to the existing point-based ranking, but CAM/HDTS/TS/telesync/screener-style markers are still rejected as defense in depth.
- Normal search exposes only eligible actionable releases; rejected evidence, if retained, includes a structured rejection reason and cannot be selected by the UI or API.
- Title-based and reference-based ingest both fail closed with a structured quality-gate error when the movie is ineligible.
- If all candidates fail, the system returns an explicit no-acceptable-release result and does not write a new accepted prewarm/cache record.
- Existing accepted browser-readiness records are not silently rewritten or deleted; any remediation of already-persisted ineligible records is separately audited and authorized.
- MediaFlow remains downstream of selection and cannot make an ineligible movie eligible.
- Movie ranking behavior for eligible candidates remains covered by the existing tests and continues to prefer the configured quality/cache policy.

## Verification

- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_movie_quality_gate.py tests\test_web_search.py tests\test_background_prewarmer.py tests\test_web_ingest_telemetry.py tests\test_mismatch_guard.py -q --basetemp scratch\pytesttmp-quality-gate`
- Exercise a deterministic movie inside the 65-day window through discovery, search, pre-warm, title ingest, direct-reference ingest, and playback-candidate selection; verify rejection without provider mutation.
- Exercise an eligible movie with both a good Web-DL candidate and a cached CAM/HDTS candidate; verify the bad candidate cannot win.
- Verify rejected candidates cannot advance browser-readiness or cache/prewarm counts.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-quality-gate-full`
- `git diff --check`
