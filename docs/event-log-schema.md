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

### Discord Playback Notification Event

Created by media-bot after receiving Tautulli playback start, stop, or watched events and attempting to post or update the corresponding Discord playback card. The `kv_store` playback session keys store only non-secret Discord channel/message IDs and Tautulli session identifiers.

```json
{
  "eventType": "playback_notification",
  "source": "discord",
  "title": "Boys' Night",
  "summary": "Updated playback card.",
  "entityType": "episode",
  "entityId": "12345",
  "status": "updated",
  "severity": "info",
  "occurredAt": "2026-06-07T01:30:00Z",
  "data": {
    "tautulli_event": "watched",
    "session_key": "abc123",
    "user": "dorothyfung",
    "player": "AFTSSS"
  }
}
```

### Manual AllDebrid Cloud Events

Manual browser-copy and generic cloud-cache requests record structured lifecycle events. Passive pre-warm checks do not emit these events or create notification ownership.

- `browser_stream_prepare_requested`: an exact browser-compatible release was manually queued.
- `browser_stream_ready`: the completed AllDebrid file was verified as MP4/M4V + H.264/AVC + AAC/MP3.
- `browser_stream_prepare_failed`: the completed file failed browser verification.
- `cloud_transfer_requested`: a generic instant-download copy was manually queued.
- `cloud_transfer_ready`: that generic copy completed in AllDebrid; browser playback is not implied.

The event `entityId` is the manual AllDebrid transfer ID when one exists. Media identity, purpose, selected release reference, and verification filename are stored in `data_json`.

### Passive Pre-warm Runtime Events

The durable pre-warm scheduler records sanitized lifecycle events without creating manual transfer ownership or notifications:

- `cache_prewarm_cycle_scheduled`
- `cache_prewarm_cycle_running`
- `cache_prewarm_cycle_completed`
- `cache_prewarm_cycle_failed`
- `cache_prewarm_cycle_interrupted`
- `cache_prewarm_cycle_skipped`
- `plex_startup_sync_failed` when Plex startup synchronization fails while the independent pre-warm scheduler remains available

The event `entityId` is the opaque `cycle_id`; `data_json` may contain trigger source, bounded counts, elapsed time, and sanitized error codes. It must not contain raw magnets, provider URLs, credentials, private paths, or provider payloads.
