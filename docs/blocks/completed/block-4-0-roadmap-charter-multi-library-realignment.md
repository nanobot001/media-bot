# Block 4-0: Roadmap & Charter Multi-Library Realignment

> Status: Implemented on 2026-06-08.
> Result: Implemented.
> Verification: `git diff -- docs/project-charter.md docs/blocks/README.md` - passed.
> Notes: Documented the multi-library alignment in the charter and registered Phase 4 and 5 blocks in the block index.

## Goal

Make the project authority docs reflect the new direction: `media-bot` remains movie-stable, but the roadmap now expands toward separately indexed anime, TV, and TV Classic domains. This block is documentation-only and prepares the repo for later implementation blocks.

## Scope

- Update the project charter to make `movies`, `anime`, `tv`, and `tv_classic` first-class media domains.
- Revise the old TV non-goal so user-triggered episode/season search and download are in scope, while autonomous monitoring is deferred to a later opt-in phase.
- Record phase-level MVPs for Phase 4 through Phase 10.
- Record the rollout order: Anime first, TV second, TV Classic third, unified assistant fourth, domain-specific monitors later.
- Add the movie-derived implementation lessons that later domains must reuse.
- Update the block index so the new roadmap is visible to future implementers.

## Out Of Scope

- Do not change runtime code, schemas, tools, Discord commands, MCP tools, or migrations.
- Do not implement domain routing, Plex sync, anime schemas, or download behavior.
- Do not create detailed tickets for every future TV, TV Classic, or autonomous-monitor block yet.

## Likely Files Or Areas

- `docs/project-charter.md`
- `docs/blocks/README.md`
- `docs/continue-here.md` if a handoff update is requested after the block

## Acceptance Criteria

- The charter states that anime, TV, and TV Classic are first-class future domains.
- The charter states that autonomous monitoring is deferred to a future opt-in phase while user-triggered episode/season search and download are in scope.
- The roadmap documents phase MVPs for multi-library skeleton, anime intelligence, anime downloads, TV reuse, TV Classic deep discovery, unified media assistant, and future domain-specific monitors.
- The block index includes Phase 4 and the first Anime Phase 5 planned blocks.
- No code behavior changes are introduced by this block.

## Verification

- `git diff -- docs/project-charter.md docs/blocks/README.md`
- Manual check that no non-documentation files changed for this block.
