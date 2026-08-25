# Block 5.2: Web UI Search & ⚡ Lightning Cache Badging

> Status: Implemented on 2026-08-24.
> Result: Implemented.
> Verification: `pytest tests/test_web_search.py` - passed (4/4 tests), full suite passed (299/299 tests).
> Notes: Added `/api/search` FastAPI endpoint with multi-domain Prowlarr category routing and AllDebrid instant cache checks, release title metadata parser, and interactive Search Modal with ⚡ Lightning badges and pinned ranking.

## Objective
Implement instant title search and Prowlarr release listings with real-time AllDebrid `⚡ Lightning (Instant Cache)` badging.

## Requirements
- Instant Search Bar:
  - Query Prowlarr for the active domain (Category 2000 for Movies, 5000 for TV/Classic TV).
- ⚡ Lightning Cache Badging:
  - Backend runs batch `/v4/magnet/instant` checks against AllDebrid.
  - Display glowing green/cyan `⚡ Lightning (Instant Cache)` badge for pre-cached torrents.
  - Display amber `⏳ Uncached (P2P)` badge for uncached releases.
  - Pinned ranking: Automatically sort ⚡ Lightning cached releases to the top.
- Detailed Release Columns:
  - Resolution (2160p Remux, 1080p Web-DL), File Size, Seeders, Audio channels (Dolby Atmos, 5.1), and Source Tracker.

## Acceptance Criteria
- [x] Searching returns ranked torrent releases from Prowlarr.
- [x] AllDebrid instant cache status accurately badges releases as `⚡ Lightning` vs `⏳ Uncached`.
- [x] Cached releases are sorted/highlighted for immediate 1-click download.
