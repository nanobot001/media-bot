# Block 02: Discord Gateway, Constraints & Audits

**Status: PLANNED**

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
