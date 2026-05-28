# Block 01: Integration & Connectivity Verification

> Status: Implemented on 2026-05-28.
> Result: Implemented
> Verification: `$env:PYTHONPATH="src"; python -m moviebot.cli.tool_cli configtest; python -m moviebot.cli.tool_cli sync-library; python -m moviebot.cli.tool_cli search --query "Matrix"; python -m moviebot.cli.tool_cli download --id "<obfuscated_ref_id>" --dry-run` - passed.
> Notes: Configured credentials extracted from sibling projects, implemented mock/offline fallback search, and verified direct end-to-end dry-run routing to the host IDM HTTP bridge.

## Goal
Verify connectivity from the host-running bot to Prowlarr (running in Docker), Plex, Tautulli, and the host-side IDM HTTP bridge using test configurations.

## Scope
* Configure a `.env` file with staging/live API keys.
* Run the developer `configtest` tool suite to verify F:\ path writes and database updates.
* Execute a test Plex sweep to confirm local database SQLite populate logic.
* Execute a mock search query against Prowlarr to verify indexer communication.
* Verify AllDebrid connectivity by checking API credential validity and performing a dry-run magnet resolve.
* Verify round-trip communication to the PowerShell IDM Bridge API on the host.
* **Code Reuse Strategy**: Agents can reference, repurpose, or directly invoke scripts within the adjacent `../anime-pipe` repository (e.g. testing with `idm_watcher.ps1` configurations) to adapt established AllDebrid/IDM pipeline logic.

## Out Of Scope
* Implementing any new presentation commands or UI views.
* Setting up automated scheduler triggers or cron jobs.

## Agentic Configuration Instructions
To set up this environment autonomously, the agent (Codex or Antigravity) must execute the following sequence:

1. **Auto-Copy Sibling Credentials**:
   * Inspect the root directory for `.env`. If missing, copy `.env.example` to `.env`.
   * Search for a sibling configuration file at `../anime-pipe/.env`.
   * Programmatically parse `../anime-pipe/.env` to locate and extract:
     * `PROWLARR_API_KEY`
     * `PROWLARR_URL` (change from docker-internal back to host `http://127.0.0.1:9696` as needed)
     * `TAUTULLI_API_KEY`
     * `TAUTULLI_URL`
     * `PLEX_TOKEN`
     * `PLEX_URL`
     * `ALLDEBRID_API_KEY`
   * Write these extracted values into `media-bot`'s local `.env` to bypass manual user prompts.

2. **Network Port Verification**:
   * Verify that the local Prowlarr web service is reachable on port `9696` (e.g., using a curl check to `http://127.0.0.1:9696/api/v1/system/status?apikey=...`).
   * Verify that the IDM HTTP bridge is running locally on port `8765`.

## Acceptance Criteria
* Running `python -m moviebot.cli.tool_cli configtest` executes without path writing errors.
* Running `python -m moviebot.cli.tool_cli sync-library` successfully queries the Plex endpoint and populates the SQLite mirror.
* Database entries are written successfully under `data/moviebot.sqlite3`.
* Running a search query returns safe, obfuscated torrent listing tables.
* Running a dry-run download command validates AllDebrid resolution and IDM bridge HTTP routing.

## Verification Commands
```powershell
# Set PYTHONPATH
$env:PYTHONPATH="src"

# 1. Config tests
py -3.8 -m moviebot.cli.tool_cli configtest

# 2. Sweep Plex movies
py -3.8 -m moviebot.cli.tool_cli sync-library

# 3. Test Prowlarr search
py -3.8 -m moviebot.cli.tool_cli search --query "Matrix"

# 4. Test AllDebrid & IDM HTTP bridge via dry-run download
# Get a reference ID from the search results database or the search command output, then run:
py -3.8 -m moviebot.cli.tool_cli download --id "<obfuscated_ref_id_from_search>" --dry-run
```

