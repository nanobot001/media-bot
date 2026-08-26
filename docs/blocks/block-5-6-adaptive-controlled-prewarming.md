# Block 5-6: Adaptive Controlled Prewarming

> Status: Planned.
> Result: Not implemented.
> Notes: Depends on Block 5-5 so increased throughput uses authoritative browser verification rather than multiplying the current title-only false negatives.

## Goal

Increase popular-movie coverage substantially while preserving the existing Discovery tiers, resumable frontier progression, TV priorities, provider politeness, and silent passive-prewarm boundary. The worker should process a full useful catalog slice when providers are healthy and reduce work automatically when indexers degrade.

## Dependencies

- Block 5-5 authoritative browser verification, durable evidence reuse, and ownership-aware probe cleanup.
- Existing recent movie cursor (current year down through 1980) and independent TMDb all-time-popularity cursor.
- Existing progressive TV vectors and six-hour background loop.

## Scope

- Preserve the existing cycle phases and ordering:
  1. batch-reverify tracked AllDebrid cache state;
  2. process eight progressive/classic-TV candidates;
  3. process six trending-TV candidates;
  4. process the recent movie frontier;
  5. process the all-time-popular movie frontier.
- Preserve these vector origins and cursor semantics: `plex_watch_priority`, `season_progression`, `frontier_boxset`, `frontier_s1`, `infinite_tmdb_classic`, `tv_trending`, `movie_recent`, and `movie_all_time_popular`.
- Make each movie lane adaptive and bounded:
  - normal target: 20 candidates per lane per six-hour cycle;
  - healthy target: up to 30 candidates per lane;
  - degraded target: no fewer than 10 candidates per lane unless the global time cap is reached;
  - hard cycle wall-clock cap: 30 minutes.
- Derive the next cycle's lane target from persisted structured health statistics:
  - use 30 when median movie search latency is at most 5 seconds and the error rate is at most 5%;
  - use 10 when median latency is at least 15 seconds, the error rate reaches 20%, or a provider reports rate limiting;
  - otherwise use 20.
- Deduplicate exact media identities across hot, recent, and all-time lanes before network work while still advancing each resumable cursor past the consumed frontier positions.
- Prioritize deep browser verification in this order:
  1. manual browser-copy requests, which remain immediate and outside background budgets;
  2. already-successful Search/player verifications awaiting persistence, which should normally require no new provider call;
  3. titles present in the current Discovery cache/feed;
  4. recent-frontier titles;
  5. all-time-popular titles.
- Per cycle, enforce global deep-verification limits:
  - at most 15 media titles;
  - at most 20 AllDebrid file-tree inspections;
  - at most two `ffprobe` fallbacks;
  - one `ffprobe` process at a time;
  - stop probing a title after the first verified browser candidate.
- Preserve current-year-to-1980 descending traversal. Pre-1980 movies remain reachable through all-time popularity rather than an oldest-first crawl.
- Persist cycle duration, selected adaptive target, median search latency, error/rate-limit counts, lane counts, deduplicated count, deep-verification counts, and stop reason in structured cycle state/events.
- Keep passive prewarming silent: it may inspect already cached releases but must not cache an uncached release, create a manual intent, produce a Cloud Transfer card, or generate a completion notification.

## Out Of Scope

- Altering major/indie Discovery classification or the user's active Discovery filters.
- Changing movie, TV, TV Classic, or all-domain milestone values.
- Replacing the existing SQLite cursor scheme or six-hour schedule with a new scheduler.
- Increasing the existing eight progressive/classic-TV or six trending-TV candidate budgets.
- Autonomous AllDebrid downloads of uncached media.

## Likely Files Or Areas

- `src/moviebot/core/background_prewarmer.py`
- `src/moviebot/db/cache_prewarm_repo.py`
- `src/moviebot/db/connection.py`
- `src/moviebot/core/discovery_cache.py`
- `src/moviebot/api/web_routes.py`
- `tests/test_background_prewarmer.py`
- `tests/test_browser_stream_prepare.py`

## Acceptance Criteria

- A healthy normal cycle selects 20 recent and 20 all-time-popular movie frontier positions before deduplication.
- Health thresholds deterministically select 30, 20, or 10 candidates per lane for the next cycle.
- The cycle stops safely at 30 minutes without corrupting or skipping unresolved cursor state.
- Duplicate exact title/year identities receive at most one network evaluation per cycle while both source vectors remain attributable.
- Manual requests are never delayed by the background deep-verification budget.
- Deep verification cannot exceed 15 titles, 20 AD inspections, or two serialized `ffprobe` calls per cycle.
- The recent cursor continues from the current year toward 1980; the all-time cursor remains independent and resumable.
- Existing TV watch priority, season progression, classic catalog, boxset, and trending behavior remains unchanged.
- Passive work does not create AllDebrid downloads, Cloud Transfer cards, or user notifications.
- Cycle output and event data explain the selected budget and any degradation decision without exposing secrets or raw magnet URLs.

## Verification

- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_background_prewarmer.py tests\test_browser_stream_prepare.py -q --basetemp scratch\pytesttmp-block-5-6`
- Add deterministic fake-provider tests for healthy, normal, degraded, rate-limited, deduplicated, and 30-minute-cap cycles.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-6-full`
- `git diff --check`
- Restart only `media-bot` through PM2 and verify the prewarm status API reports the selected adaptive budget and preserved vector counts. Do not trigger a broad live provider cycle unless separately authorized.
