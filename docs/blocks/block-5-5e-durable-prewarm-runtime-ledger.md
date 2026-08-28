# Block 5-5e: Durable Prewarm Runtime Ledger

> Status: Planned.
> Result: Not implemented.
> Notes: Corrective Phase 5 runtime block; must land before release-catalog population or adaptive throughput so every background cycle has durable, inspectable evidence.

## Goal

Make the passive pre-warm worker operationally trustworthy across PM2 restarts, Plex-sync failures, manual triggers, and normal six-hour scheduling. A user or tool must be able to determine whether a cycle was scheduled, started, completed, failed, or was interrupted without relying on process-local memory or clustered cache-row timestamps.

## Dependencies

- Existing PM2-supervised native runtime and FastAPI startup lifecycle.
- Existing pre-warm interval and enable settings.
- Existing recent, all-time-popular, TV, and TV Classic cursor state.

## Scope

- Add a durable pre-warm run ledger with a stable `cycle_id` and structured lifecycle states such as `scheduled`, `running`, `completed`, `failed`, `interrupted`, and `skipped`.
- Persist at minimum: scheduled/start/finish timestamps, next-due timestamp, trigger source, process/runtime identity, selected interval, phase counts, provider-error counts, stop reason, and a sanitized structured error code/message when applicable.
- Start the pre-warm scheduler independently of Plex startup synchronization success while preserving Plex synchronization as a separate startup task.
- Add a durable singleton/lease guard so startup, restart recovery, and manual triggers cannot run overlapping cycles.
- On startup, reconcile stale `running` rows as interrupted and compute the next eligible run from durable state rather than resetting cadence from process-local memory.
- Preserve the existing six-hour default and user-configurable enable/interval settings; this block changes reliability and evidence, not throughput.
- Make the pre-warm status API read authoritative last/active/next-run state from the ledger while preserving existing response fields through additive compatibility fields.
- Add a compact operator-visible ledger view to the existing pre-warm UI showing the active cycle, last completed/failed cycle, next-due time, trigger, stop reason, and a bounded recent-cycle history.
- Record meaningful structured lifecycle events without creating Cloud Transfer cards, manual transfer ownership, or user notifications for passive work.

## Out Of Scope

- Changing candidate vectors, per-lane budgets, ranking, or cursor traversal.
- Adding release variants or changing A/B/C availability semantics.
- Deep browser verification, MediaFlow playback, or automatic AllDebrid downloads.
- Replacing PM2 or the existing interval scheduler with an external scheduling system.

## Likely Files Or Areas

- `src/moviebot/db/connection.py`
- `src/moviebot/db/prewarm_run_repo.py`
- `src/moviebot/core/background_prewarmer.py`
- `src/moviebot/api/webhook.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/web/app.js`
- `tests/test_background_prewarmer.py`
- `tests/test_web_ui_endpoints.py`

## Acceptance Criteria

- A completed cycle leaves one durable run row containing start, finish, trigger, phase counts, stop reason, and next-due time.
- A simulated process restart after cycle completion preserves the next-due time and does not immediately rerun solely because in-memory state was lost.
- A stale `running` row is reconciled as `interrupted` on startup before a new cycle may acquire the lease.
- A failed Plex startup sync does not prevent the pre-warm scheduler from starting, and the sync failure remains separately observable.
- Concurrent startup/manual-trigger attempts result in at most one active cycle and a structured skipped/busy result for the other attempt.
- Existing enable/interval settings and manual-trigger compatibility remain intact.
- The existing pre-warm UI visibly distinguishes scheduled, running, completed, failed, interrupted, and skipped cycles and obtains those states from the durable ledger rather than process-local memory.
- Passive cycles do not create `cloud_transfer_intents`, transfer cards, completion notifications, or provider-wide cleanup actions.
- Public/read APIs expose no secrets, raw magnets, provider URLs, private filesystem paths, or credentials.

## Verification

- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest tests\test_background_prewarmer.py tests\test_web_ui_endpoints.py -q --basetemp scratch\pytesttmp-block-5-5e`
- Add deterministic fake-clock tests for normal cadence, restart recovery, stale-run reconciliation, Plex-sync failure, lease contention, manual trigger, and disabled scheduling.
- `$env:PYTHONPATH='src'; .\.venv\Scripts\python.exe -m pytest --ignore=tests\test_mcp_server.py -q --basetemp scratch\pytesttmp-block-5-5e-full`
- `git diff --check`
- Restart only `media-bot` through PM2 and verify the status API reports the durable last run and next due time. Do not trigger a broad live provider cycle without separate authorization.
