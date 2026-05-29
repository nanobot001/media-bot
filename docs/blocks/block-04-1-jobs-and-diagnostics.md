# Block 04-1: Active Jobs, Pending Job Resolution, and Diagnostics

**Status: COMPLETED**

## Goal
Implement download job tracking, background pending torrent resolution, and error logging diagnostic tools to make the download pipeline self-healing and auditable before introducing the Model Context Protocol (MCP) server layer.

## Scope
*   **Database Schema & Repositories**:
    *   Extend `DownloadJobRepository` in `repositories.py` with `get_active_jobs()`, `get_all_jobs()`, and `update_job_details()`.
*   **Core Logic Layer (Tools)**:
    *   Create `get_download_jobs_tool` to list active and historical download jobs.
    *   Create `resolve_pending_jobs_tool` to sweep the database for jobs with status `pending`, query their magnet download status in AllDebrid, perform file selection heuristically, unlock direct links, forward links to IDM, and transition statuses.
    *   Create `get_error_logs_tool` to retrieve structured exception logs from the database.
*   **Presentation Layer (Discord & CLI)**:
    *   Add `/jobs` command to list active/recent jobs.
    *   Add `/resolve` command to manually trigger the pending jobs sweep.
    *   Add `/errors` command (admin restricted) to inspect recent runtime stack traces.
    *   Implement an asynchronous background loop in `discord_app.py` running every 60 seconds to automatically trigger `resolve_pending_jobs_tool`.
    *   Expose matching subcommands (`jobs`, `resolve-pending`, `errors`) in `tool_cli.py`.

## Out Of Scope
*   Exposing the new tools via Model Context Protocol (deferred to Block 05).
*   Adding manual file selection options inside the automated background loop (if selection is ambiguous, the job status simply transitions to `requires_selection`).

## Acceptance Criteria
*   The `resolve_pending_jobs_tool` successfully resolves debrid torrent files, pushes them to IDM, and moves status to `downloading` (or `dry_run`).
*   Jobs requiring manual intervention are correctly labeled as `requires_selection`.
*   The background worker resolves pending jobs automatically without user input.
*   Discord commands `/jobs`, `/resolve`, and `/errors` display outputs correctly.
*   Automated tests verify DB operations, resolution logic, and error log retrieval.
