# Block 02: Discord Gateway, Constraints & Audits

**Status: COMPLETED**

## Execution Notes
This block was implemented and verified successfully:
- **Configuration**: Introduced `ALLOWED_DISCORD_CHANNELS` (comma-separated lists) and `DISCORD_ERROR_CHANNEL_ID` in `config.py`.
- **Database Schema**: Created a dedicated `errors` table tracking command exceptions, stack traces, and user context.
- **Repository Interface**: Built `ErrorLogRepository` with automated pruning support (defaults to keeping the last 500 error entries) to prevent database bloat.
- **Command Security**: Implemented a channel restriction decorator (`@in_allowed_channel()`) checking incoming interactions against allowed channel lists, returning a clean, ephemeral embed when restricted.
- **Error Telemetry**: Configured the global CommandTree error handler (`on_app_command_error`) to catch runtime failures, log them to SQLite, alert the user ephemerally, and post an error report with the stack trace to the designated admin Discord channel.
- **Verification**: Created a full mock-based test suite (`tests/test_discord_app.py`) verifying all logic paths, including successful execution, channel block scenarios, error logging, formatting, and auto-pruning. All tests pass successfully.

## Goal
Connect the Discord bot application, enforce specific channel constraints for command usage (e.g. only responding in `#movie-requests`), and implement clean interactive embeds for slash commands, download statuses, and audits.

## Scope
*   Register and connect the Discord slash commands gateway.
*   Restrict slash command execution to configurable channel IDs read from the environment (`ALLOWED_DISCORD_CHANNELS`).
*   Verify end-to-end user loop via the five slash commands:
    *   `/search <query>`: Queries indexers, performs deduplication checks, and displays interactive download buttons.
    *   `/download <url>`: Direct download bypass. Input a magnet link or direct torrent URL to queue it straight into AllDebrid -> IDM.
    *   `/check <title> <year>`: Runs normalization algorithms to check if a title already exists in the Plex database mirror.
    *   `/sync`: Performs an on-demand cache sync of the Plex Media Server library.
    *   `/history [user] [title] [limit]`: Queries Plex/Tautulli watch records to show who watched what, when, and on what device.
*   Implement message embeds showing active download status (speed, completion, ETA) fetched from the IDM client status or AllDebrid.
*   Log runtime errors to a dedicated SQLite `errors` table and alert administrators in a designated `#media-errors` log channel.

## Out Of Scope
*   Push-based library syncing from webhooks (Tautulli).
*   Automatic disk cleanup or space warnings.

## Acceptance Criteria
*   The Discord gateway connects successfully and registers all 5 commands.
*   Commands invoked outside allowed channels return a helpful message and terminate early.
*   Errors automatically trigger an embed warning in the error log channel.
*   Interactive buttons for search results correctly trigger the AllDebrid -> IDM download pipeline.
