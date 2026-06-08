# Block 10-0: Domain-Specific Autonomous Monitors

> Status: Future.
> Result: Not implemented.
> Notes: Preserves the future autonomous-monitor roadmap without making it part of the Phase 4-9 MVP path.

## Goal

Define the future autonomous-monitor model for each media domain after manual search/download, domain databases, and matching regression tests are reliable. The design should avoid becoming an unrestricted Sonarr/Radarr clone by requiring opt-in monitor entries, reviewable dry-run sweeps, quotas, structured events, and confidence-gated enqueue behavior.

The Phase 10 MVP is monitor-only: scheduled or manual dry-run sweeps can surface reviewable candidates for movie release windows, anime cour watchlists, and continuing TV shows, but they do not auto-download.

## Scope

- Define a shared monitor safety model with graduated modes:
  - `manual`: user-triggered search only.
  - `monitor_only`: scheduled sweeps produce candidates for review.
  - `approval_required`: candidates can be enqueued after explicit approval.
  - `trusted_auto_enqueue`: strict matches can enqueue automatically only after confidence gates are proven.
- Define a movie release-window monitor for wanted movies, physical media releases, major VOD availability, and meaningful quality upgrades, with a weekly sweep as the default cadence.
- Define an anime cour watchlist model for quarterly seasons, currently airing shows, expected episodes, absolute numbering, release-group or quality preferences, and batch checks near cour completion.
- Treat the adjacent `anime-pipe` project as an early prototype source for anime cadence and release heuristics, not as final architecture to copy directly.
- Define a TV continuing-show watchlist for active or incomplete shows, missing/new episode detection, and ended-show pause behavior.
- Define TV Classic as the exception: classic shows are usually complete, so deep episode discovery remains primary; only optional quality-upgrade monitoring is considered later.
- Require per-domain quotas, admin-visible state, structured event logs, pause/resume/delete controls, and dry-run-first sweep commands.
- Define the block sequence for Phase 10:
  - Block 10-1: Monitor State Schema & Admin Tools.
  - Block 10-2: Monitor Sweep Engine.
  - Block 10-3: Movie Release-Window Monitor.
  - Block 10-4: Anime Cour Watchlist Monitor.
  - Block 10-5: TV Continuing Show Monitor.
  - Block 10-6: Discord Review & Approval Flow.
  - Block 10-7: Trusted Auto-Enqueue Rules.

## Out Of Scope

- Do not implement monitor runtime loops in this block.
- Do not add automatic enqueue behavior before manual episode/season search and domain matching regression tests are complete.
- Do not create a general-purpose replacement for Sonarr/Radarr.
- Do not change existing movie, anime, TV, or TV Classic download flows.
- Do not make trusted auto-enqueue part of the Phase 10 MVP.

## Likely Files Or Areas

- `docs/project-charter.md`
- `docs/blocks/README.md`
- Future monitor design docs under `docs/architecture/` or `docs/production/`
- Future tool docs in `docs/tool-surface.md` and `docs/tool-manifest.yaml`

## Acceptance Criteria

- The charter records autonomous monitoring as a future opt-in capability, not a Phase 4-9 MVP requirement.
- The roadmap distinguishes movie release-window monitoring, anime cour watchlists, TV continuing-show watchlists, and the TV Classic exception.
- The safety ladder is explicit: manual, monitor-only, approval-required, then trusted auto-enqueue.
- The roadmap requires dry-run sweeps, quotas, structured events, and admin controls before any autonomous enqueue behavior.
- `anime-pipe` is documented as prototype input for anime monitor heuristics rather than final architecture.
- The Phase 10 MVP is explicitly monitor-only and does not auto-download.
- The block index lists Blocks 10-1 through 10-7 as future implementation slices.

## Verification

- `git diff -- docs/project-charter.md docs/blocks/README.md docs/blocks/block-10-0-domain-specific-autonomous-monitors.md`
- Manual check that this block does not make autonomous monitoring a dependency of Phases 4-9.
