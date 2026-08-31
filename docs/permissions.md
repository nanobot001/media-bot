# Tool Permissions

Every tool must have a risk level.

## Risk Levels

- `public_read`: safe for normal users, such as basic status or public recent events.
- `trusted_read`: may expose operational details, such as logs, local paths, config summaries, or debug traces.
- `write_action`: changes state but is not destructive, such as retrying a failed item or refreshing a cache.
- `admin_action`: controls runtime or configuration, such as restart, pause, resume, or polling changes.
- `destructive_action`: deletes, clears, purges, overwrites, or removes data.

## Rules

- `write_action` and above should support dry-run.
- `admin_action` and above should require explicit confirmation.
- `destructive_action` should always require explicit confirmation.
- Public outputs must not expose secrets, tokens, private paths, or sensitive local details.
- All write/admin/destructive calls should be recorded in `tool_calls`.

## Local MediaFlow Routes

- `GET /api/mediaflow/status`: `trusted_read`, localhost-only, sanitized configuration and health state.
- `GET /api/mediaflow/diagnostics`: `trusted_read`, localhost-only, bounded versioned failure/admission evidence projected according to the configured diagnostics mode.
- `POST /api/mediaflow/playback`: `write_action`, localhost-only, supports `dry_run`, and records a structured playback-prepared or playback-failed event.
- `POST /api/mediaflow/sessions/{session_id}/events`: `write_action`, localhost-only, accepts only allowlisted playback events and sanitized metrics.
- `POST /api/mediaflow/sessions/{session_id}/seek`: `write_action`, localhost-only, accepts only a numeric timeline position and rotates the existing opaque session without exposing the source.
- `DELETE /api/mediaflow/sessions/{session_id}`: bounded lifecycle cleanup for one opaque local session; it cannot delete catalog, provider, or media data.
