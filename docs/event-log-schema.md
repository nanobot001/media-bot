# Event Log Schema

This project should record meaningful domain events in structured state.

Do not rely on human text logs as the source of truth for bot queries.

Use `kv_store` only for non-secret lightweight state such as cursors, pause flags, and last-seen IDs. Do not store raw tokens, API keys, session cookies, OAuth credentials, or private secrets in `kv_store` unless this project has an explicit local secret-storage policy.

## Generic Event Shape

```json
{
  "eventType": "example_event",
  "source": "project-name",
  "title": "Human-readable title",
  "summary": "Short summary",
  "entityType": "optional-domain-entity",
  "entityId": "optional-id",
  "status": "completed",
  "severity": "info",
  "occurredAt": "2026-05-26T00:00:00-04:00",
  "data": {}
}
```

## Existing Event Sources

For existing projects, document whether events are derived from an existing database, structured files, API responses, logs, or new event capture added by the adapter.

## Project-Specific Events

Add project-specific examples here.
