# Block 03: Tautulli Webhook & Event Integration

**Status: PLANNED**

## Goal
Implement a lightweight HTTP listener endpoint inside the bot container to receive stream notification events from Tautulli, automatically triggering library database syncs and activity logs.

## Scope
*   Extend `src/moviebot/main.py` or a dedicated listener to start an HTTP server (e.g. using `http.server` or `fastapi` if added) on port `8000` to listen for webhooks.
*   Implement support for Tautulli notification event payloads (specifically `on_play`, `on_stop`, and `on_watched`).
*   Trigger a selective Plex sync (`PlexClient().fetch_movie_details()`) when a movie is watched to update the local database `library_items` mirror.
*   Log stream events to the SQLite `events` database table.

## Out Of Scope
*   Building user notifications or Discord channel logs.
*   Enqueuing any downloads from webhook triggers.

## Acceptance Criteria
*   The webhook endpoint successfully validates incoming payloads.
*   Receiving a `watched` notification containing an IMDb ID updates that item's local DB entry.
*   Activity logs are correctly populated in the `events` table with standard schemas.
