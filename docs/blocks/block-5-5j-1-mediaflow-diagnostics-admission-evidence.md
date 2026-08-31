# Block 5-5j-1: MediaFlow Diagnostics And Admission Evidence

> Status: Implemented on 2026-08-30.
> Result: Implemented.
> Verification: `57` focused MediaFlow/web tests and `413` full non-MCP tests passed initially; the publication checkpoint subsequently passed all `432` tests, Python/JavaScript compilation, Compose configuration, and `git diff --check`.
> Notes: Added configurable versioned diagnostics, stage-specific admission evidence, a bounded localhost read route, stale-decision projection, and a permanently visible dashboard `Diagnostics` view. Delivery thresholds and segmented streaming remain unchanged.

## Goal

Make every MediaFlow preparation failure and admission decision gracefully debuggable. Operators must be able to see where an attempt failed, which sanitized measurements and rules were used, whether the evidence is current, and what action is safe next. Diagnostic verbosity must be configurable without disabling safety or returning to opaque errors.

## Scope

- Add `MEDIAFLOW_DIAGNOSTICS_MODE=off|summary|detailed`, defaulting to `summary`; invalid values fail safely to `summary`.
- Define a versioned sanitized diagnostics envelope containing decision version, stage, code, retryability, timestamp, exact variant ID, delivery decision, reason labels, source size/duration, workload/profile source, configured guardrails, and current capacity where available.
- Attach stage-specific diagnostics to adapter errors for configuration, source resolution/unlock, probe, delivery policy, admission, capacity reservation, URL generation, browser playback, seek, and cleanup boundaries as applicable to the existing implementation.
- Persist bounded diagnostics in structured MediaFlow events. `off` retains schema version, stage, code, and retryability; `summary` adds concise decision/reason/capacity fields; `detailed` adds the full allowlisted evidence envelope.
- Add a localhost-only trusted-read diagnostics route with bounded recent attempts and mode/current decision-version state.
- Add a dashboard summary and a user-visible `Why?` explanation for the latest failure. The view must distinguish policy rejection, measured admission rejection, busy capacity, probe/provider failure, startup/playback failure, and seek/cleanup failure.
- Mark legacy or mismatched decision-version evidence as stale in the diagnostics projection; do not delete or rewrite historical events.

## Out Of Scope

- Relaxing or recalibrating current admission thresholds.
- Claiming the NeoNoir release is playable before its measured decision and segmented path are verified.
- Implementing the segmented producer, HDR tone mapping/preservation, automatic alternate-variant playback, or worker cancellation changes.
- Database migration or destructive cleanup of existing MediaFlow outcomes.
- Live provider playback or provider retries.

## Likely Files Or Areas

- `.env.example`
- `src/moviebot/config.py`
- `src/moviebot/core/mediaflow_adapter.py`
- `src/moviebot/core/mediaflow_diagnostics.py`
- `src/moviebot/api/web_routes.py`
- `src/moviebot/web/app.js`
- `src/moviebot/web/index.html`
- `tests/test_mediaflow_production_adapter.py`
- `tests/test_web_ui_endpoints.py`
- `docs/event-log-schema.md`
- `docs/permissions.md`
- `docs/tool-surface.md`

## Acceptance Criteria

- The same rejected HEVC/10-bit fixture that returns `MEDIAFLOW_TRANSCODE_TOO_EXPENSIVE` also reports `stage=admission`, the exact allowlisted reason labels, measured source size/duration, workload/profile source, guardrails, decision/schema version, and safe next action in detailed mode.
- Summary mode returns a concise stage/code/reason projection; off mode returns only minimal stage/code/retryability/version fields. None of the modes changes admission, capacity, playback, or fallback behavior.
- Recent diagnostics are available only from localhost, are bounded, identify stale decision versions, and never expose source URLs, magnets, credentials, headers, command lines, or private paths.
- Dashboard status shows diagnostics mode and the latest failure; `Why?` presents a readable explanation and safe next action without requiring raw PM2 or Docker logs.
- Existing structured error fields remain backward-compatible and MediaFlow evidence still cannot promote canonical state C.
- Focused tests cover modes, sanitization, admission evidence, stale-version projection, route locality/bounds, and dashboard strings.

## Verification

- `.\.venv\Scripts\python.exe -m pytest tests\test_mediaflow_production_adapter.py tests\test_web_ui_endpoints.py -q --basetemp scratch\pytesttmp-block-5-5j-1`
- `node --check src\moviebot\web\app.js`
- `.\.venv\Scripts\python.exe -m py_compile src\moviebot\core\mediaflow_adapter.py src\moviebot\core\mediaflow_diagnostics.py src\moviebot\api\web_routes.py`
- `git diff --check`
