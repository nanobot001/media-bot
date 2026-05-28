# Tool Surface

## Baseline Tools

Every tool-friendly project should aim to expose:

- `project.status`
- `project.health`
- `project.recent_events`
- `project.recent_errors`
- `project.tail_logs`
- `project.tool_manifest`

`project.tail_logs` may accept an optional logical `source` name for monitored logs. Treat this as a named source, not as an arbitrary local path supplied by a caller.

## Domain Tools

Add project-specific tools here.

## Existing Interface Mapping

For existing projects, document how existing commands, routes, or scripts map to the standardized tool surface.

## Output Contract

All tool outputs should be structured JSON.

Success shape:

```json
{
  "ok": true,
  "tool": "project.status",
  "timestamp": "2026-05-26T00:00:00-04:00",
  "data": {}
}
```

Error shape:

```json
{
  "ok": false,
  "tool": "project.status",
  "timestamp": "2026-05-26T00:00:00-04:00",
  "error": {
    "code": "STATE_DB_UNAVAILABLE",
    "message": "Could not open the local durable state database.",
    "retryable": true,
    "severity": "error"
  }
}
```
