# Block 4.9: Weekly Release Discord Notifier & In-Line Ingest

## Objective
Implement a weekly automated Discord notification digest and on-demand `/digest` command that surfaces top new movie and TV releases the user does not already own, with interactive in-line buttons for one-click download.

## Requirements

### Digest Generation (reuses Block 4-3 discovery engine)
- Call `discover_media_tool(domain, feed="weekly", exclude_owned=True)` — do NOT reimplement TMDb queries, filtering, or library deduplication.
- Apply user-configurable preference overlays stored in `kv_store`:
  - `language` (default `en`), `included_genres` / `excluded_genres`, `preferred_studios` / `networks`, `min_rating`.

### Discord Presentation (`bot/commands_digest.py`)
- Rich multi-item embed displaying poster thumbnails, release dates, studio/network tags, TMDb ratings, and concise synopses.
- Interactive Button Rows on each item:
  - `⚡ Ingest: [Title]` — triggers existing Prowlarr search → AllDebrid cache check → IDM enqueue pipeline.
  - `ℹ️ Details` — expands full metadata and trailer link.
  - `🚫 Ignore` — persists dismissal in `kv_store` so the title is suppressed in future digests.
- Slash commands:
  - `/digest [domain: movies|tv|all] [genre] [studio]` — on-demand digest.
  - `/digest settings` — configure channel, genre/studio preferences, and delivery schedule.

### Scheduling
- Automated weekly background cron posting to the configured Discord alerts channel (via PM2/Task Scheduler).
- Configurable day-of-week and time.

## Dependencies
- Block 4-3 (`discover_media_tool` for trending/popular queries and library dedup)
- Existing search → download pipeline for `⚡ Ingest` button action

## Acceptance Criteria
- [ ] Digest generation accurately retrieves unowned top weekly releases for movies and TV by calling `discover_media_tool`.
- [ ] Genre, studio, language, and rating preference overlays function properly.
- [ ] Discord embeds display clean release summaries with in-line action buttons.
- [ ] `⚡ Ingest` button initiates the Prowlarr search → debrid cache check → IDM enqueue pipeline.
- [ ] `🚫 Ignore` persists and suppresses titles from future digests.
- [ ] Unit tests cover digest generation, preference filtering, and Discord view interactions.
