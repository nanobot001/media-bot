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

Events are derived from the local SQLite `events` database table. The FastAPI webhook listener running on port `8000` intercepts payloads pushed from a local Tautulli instance and maps them into this table structure:

```sql
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,         -- e.g., 'watched', 'added'
    source TEXT NOT NULL,             -- e.g., 'tautulli', 'plex'
    title TEXT,                       -- Movie title
    summary TEXT,                     -- Description summary
    entity_type TEXT,                 -- e.g., 'movie'
    entity_id TEXT,                   -- Plex rating key
    status TEXT,                      -- e.g., 'completed'
    severity TEXT NOT NULL DEFAULT 'info',
    occurred_at TEXT NOT NULL,        -- ISO timestamp
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_json TEXT                    -- Raw payload dump
);
```

## Project-Specific Events

### Tautulli "Watched" Webhook Event

Pushed by Tautulli when a home-server user finishes viewing a movie. Triggers a database sync to mark the item as watched or update local cache ratings.

```json
{
  "eventType": "watched",
  "source": "tautulli",
  "title": "The Matrix",
  "summary": "User admin finished watching The Matrix",
  "entityType": "movie",
  "entityId": "12345",
  "status": "completed",
  "severity": "info",
  "occurredAt": "2026-05-29T01:30:00Z",
  "data": {
    "user": "admin",
    "player": "Plex Web",
    "percentage": 100
  }
}
```

