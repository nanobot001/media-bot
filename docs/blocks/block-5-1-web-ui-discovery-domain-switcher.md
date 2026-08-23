# Block 5.1: Web UI Discovery Feeds & 3-Domain Switcher

## Objective
Implement the top-level Discovery experience in the React Web UI with an instant 3-domain switcher (`[🎬 Movies] [📺 TV Series] [📻 Classic TV]`) and TMDb-powered trending/popular poster feeds.

## Requirements
- Domain Switcher:
  - Toggle between `Movies`, `TV Series`, and `Classic TV`.
  - Dynamically load domain-specific discovery feeds.
- Discovery Poster Feeds:
  - Connect to `/api/discover/movies` and `/api/discover/tv`.
  - Filter pills: `🔥 Trending`, `🌐 Popular English`, `🎥 4K HDR`, `💿 New Digital Releases`.
  - High-res poster grid with TMDb rating badges (e.g. ★ 8.8), year tags, and owned badges from the local library.
- Click Action:
  - Clicking any poster opens the Torrent Selection & Lightning Cache modal for that item.

## Acceptance Criteria
- [ ] Domain switcher cleanly toggles active media context.
- [ ] Poster grid loads trending/popular English releases on initial page load.
- [ ] Filter pills dynamically re-query discovery feeds.
- [ ] Responsive across mobile, tablet, and desktop viewports.
