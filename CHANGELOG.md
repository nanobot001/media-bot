# Changelog

## Unreleased

- **Block 03 — Tautulli Webhooks**:
  - Implemented a FastAPI webhook listener on port 8000.
  - Added webhook security authentication using a shared API key/token (`TAUTULLI_WEBHOOK_SECRET`) supporting both `Authorization: Bearer` headers and query parameter `?token=`.
  - Created a database schema and `EventRepository` to log incoming Tautulli webhook events to the SQLite `events` table.
  - Implemented selective Plex library database syncs for `watched` events, using the Plex rating key to retrieve movie details via a new `PlexClient().fetch_movie_details` endpoint and update `library_items`.
  - Added a complete unit/integration test suite (`tests/test_tautulli_webhook.py`) verifying webhook authentication, db events logger, and Plex database sync.
- **Block 02 — Discord Gateway, Constraints & Audits**:
  - Implemented channel restrictions for Discord slash commands using `@in_allowed_channel()` decorator.
  - Added structured SQLite database error logging (`errors` table) and routing alerts to a designated Discord admin channel.
  - Integrated auto-pruning logic in `ErrorLogRepository` to cap recorded errors to 500.
  - Created a robust pytest suite in `tests/test_discord_app.py` covering constraints, error handling, alerts, and database pruning.
- Initial project scaffold.
