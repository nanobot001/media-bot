# Block 03: Tautulli Webhook & Event Integration

**Status: COMPLETED**

## Execution Notes
This block was implemented and verified successfully:
- **Server Scaffold**: Created a FastAPI instance running concurrently with the Discord client on the same asyncio event loop. The web server listens on port `8000`.
- **Security Check**: Enforced webhook verification using `verify_token` middleware, which expects `TAUTULLI_WEBHOOK_SECRET` passed in the `Authorization: Bearer <secret>` header or the `token` URL query parameter.
- **Database Schema**: Appended the `events` table to `SCHEMA_SQL` in `connection.py` to allow logging events directly inside the bot lifecycle.
- **Repository Interface**: Built `EventRepository` to insert incoming event logs (event type, source, title, summary, status, occurred_at, and raw payload data as JSON) and retrieve logs for auditing.
- **Selective Sync**: Implemented selective Plex Media Server syncing. When a `watched`/`on_watched` event is received with a `rating_key`, the server calls `PlexClient().fetch_movie_details()` to get details of that specific asset, and uses `LibraryItemRepository.upsert` to update/sync the local database mirror.
- **Verification**: Created `tests/test_tautulli_webhook.py` to assert correct authentication blocks (allowing query tokens and bearer headers, blocking unauthorized requests), successful database event logging, and selective library synchronization. All tests pass successfully.


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
