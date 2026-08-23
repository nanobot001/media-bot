# Block 5.2: Web UI Search & ⚡ Lightning Cache Badging

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
- [ ] Searching returns ranked torrent releases from Prowlarr.
- [ ] AllDebrid instant cache status accurately badges releases as `⚡ Lightning` vs `⏳ Uncached`.
- [ ] Cached releases are sorted/highlighted for immediate 1-click download.
