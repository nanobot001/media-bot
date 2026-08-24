# Block 5.1: Web UI Discovery Feeds, 3-Domain Switcher & Live Ingest Sidebar

> Status: Implemented on 2026-08-23.
> Result: Implemented.
> Verification: `pytest` - 293 passed in 58.58s; FastAPI test client endpoint verification and static web cockpit served at `/`.
> Notes: Instant 3-domain switcher (`[🎬 Movies] [📺 TV Series] [📻 Classic TV]`), TMDb discovery feeds, Plex ownership badges (`[IN PLEX]` / `[MISSING]`), Centered Media Detail Modal, Live Recent Ingest Activity Sidebar with synthesized `media-watcher` status chips, and dedicated Full Download History Table are fully operational.

## Objective
Implement the top-level Discovery experience in the Web UI Cockpit with an instant 3-domain switcher (`[🎬 Movies] [📺 TV Series] [📻 Classic TV]`), TMDb-powered trending/popular poster feeds, a live recent ingest activity sidebar, and a full download history view.

## Requirements
- Domain Switcher:
  - Toggle between `Movies`, `TV Series`, and `Classic TV`.
  - Dynamically load domain-specific discovery feeds.
- Discovery Poster Feeds:
  - Connect to `/api/discover` for `movies`, `tv`, and `tv_classic`.
  - Filter pills: `🔥 Trending`, `🌐 Popular English`, `★ Top Rated`, `💿 New Releases`, plus genre dropdown.
  - High-res poster grid with TMDb rating badges (e.g. ★ 8.8), year tags, and owned badges (`[IN PLEX]` vs `[MISSING]`) from the local library mirrors.
- Centered Media Detail Modal:
  - Clicking any poster opens the modal with backdrop artwork, poster, synopsis, ratings, genres, network, and `[🔍 Search Torrents & Download]` action.
- Live Recent Ingest Sidebar Widget:
  - Collapsible right sidebar displaying real-time download jobs with synthesized `media-watcher` status chips (`[⚡ IDM Downloading]`, `[⚙️ Media-Watcher Processing]`, `[✅ Added to Plex]`).
- Dedicated Full History View:
  - Searchable, filterable table view across all media domains.

## Acceptance Criteria
- [x] Domain switcher cleanly toggles active media context.
- [x] Poster grid loads trending/popular English releases on initial page load.
- [x] Filter pills and genre dropdown dynamically re-query discovery feeds.
- [x] Centered Media Detail Modal displays rich backdrop, metadata, and search trigger.
- [x] Live Recent Ingest Sidebar displays real-time jobs and media-watcher state.
- [x] Dedicated Full History View provides searchable multi-domain audit table.
- [x] Responsive across mobile, tablet, and desktop viewports.
