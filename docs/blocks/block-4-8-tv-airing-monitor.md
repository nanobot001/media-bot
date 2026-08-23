# Block 4.8: TV Airing Monitor & Auto-Archiving

## Objective
Implement a scheduled autopilot sweep engine (matching the `anime-pipe` model) that monitors tracked shows on their scheduled broadcast day, automatically queries and downloads newly aired episodes without requiring manual confirmation, and transitions completed series to `archived` state upon finale ingest.

## Requirements
- Day-of-Week Autopilot Sweep:
  - Background scheduler runs daily checks for shows in `tv_watchlist` where `status == 'watching'` and `is_monitored == 1`.
  - Matches shows scheduled to air today based on `release_day` and TMDb next air dates.
  - Queries Prowlarr (Block 4-4) and AllDebrid `⚡ Lightning` cache for the newly dropped episode.
- Auto-Ingest:
  - Invokes `resolve_missing_episodes` (from Block 4-7) to automatically unlock and enqueue the episode to IDM with destination `F:\_temp\tv`.
  - Triggers just-in-time show-level enrichment (Block 4-5) if the series is newly tracked or missing TMDb/network metadata.
  - Increments `last_downloaded_episode` upon successful handoff.
  - Generates structured event logs for telemetry.

- Finale & Archival:
  - When `last_downloaded_episode == total_episodes_expected` (season/series finale has been ingested), automatically updates status to `completed` and `archived` to stop redundant polling.
- Safety & Controls:
  - Domain quota limits to prevent runaway downloads.
  - Manual on-demand sweep command: `python -m moviebot.cli.tool_cli sweep-airing [--dry-run]`.

## Dependencies
- Block 4-3 (TMDb TV air dates and episode counts)
- Block 4-5 (TV download pipeline)
- Block 4-6 (TV watchlist state and `release_day` schedules)
- Block 4-7 (`resolve_missing_episodes` core function)

## Acceptance Criteria
- [ ] Airing sweep identifies monitored shows scheduled to air on the current day.
- [ ] Newly dropped episodes are automatically searched, verified for cache, and queued to IDM without manual intervention.
- [ ] Finale detection automatically transitions show status to `completed` and `archived`.
- [ ] Unit tests verify daily schedule matching, auto-ingest execution, and state transitions.
