# Block 07: Discord Pipeline Debugger & Match Doctor

**Status: PROPOSED**

## Goal
Implement a creative and highly interactive Discord-based media ingestion monitoring and matching repair suite. This includes:
1. An **Interactive Ingestion Progress Card** in Discord that displays the status of a movie download across its lifecycle stages in real-time.
2. A **Plex Mismatch Guard** daemon that automatically detects mismatch discrepancies between download jobs and Plex matched items.
3. An **Interactive Match Doctor** utilizing Discord modals and buttons to trigger programmatic unmatching and rematching of Plex items directly from Discord.
4. A unified `/debug` panel aggregating logs, database states, and folder searches in a single view with remediative actions.

---

## Scope

### 1. Adapters & Core Clients
*   **Plex Client Enrichment**:
    *   Expose matching endpoints to interact with Plex Server API:
        *   `PUT /library/metadata/<rating_key>/unmatch`: Break current association.
        *   `GET /library/metadata/<rating_key>/matches`: Query match suggestions from agents.
        *   `PUT /library/metadata/<rating_key>/match`: Apply chosen match ID (IMDb/TMDb/Plex GUID).
*   **Database Synchronizer**:
    *   On a successful match correction, immediately fetch updated metadata from Plex and synchronize it into the SQLite `library_items` mirror to prevent state desynchronization.

### 2. Core Logic & Guards
*   **Mismatch Guard Daemon**:
    *   Compare completed `download_jobs` details (file names, expected release years) against Plex metadata library entries.
    *   Use lightweight string distance/similarity logic (e.g. Jaro-Winkler or standard Levenshtein) to identify mismatches.
    *   Trigger audits upon receiving Plex webhook library additions or completed download alerts.

### 3. Presentation Layer (Discord Bot UI)
*   **Discord Modal UI (`RematchModal`)**:
    *   Text input fields for title/year/metadata ID.
    *   Asynchronous execution handling to bypass Discord's strict 3-second interaction window.
*   **Pipeline Status embeds (`IngestionProgressView`)**:
    *   Live progress embeds showing: `Search -> Debrid Cache -> IDM Downloader -> Intake Folder -> Plex Library`.
*   **Mismatch Alerts (`MismatchAlertView`)**:
    *   Rich embeds highlighted in warning orange/red when mismatch metrics trigger.
    *   Includes `[🔧 Fix Match]` button to spawn the rematch modal, and `[✅ Keep Match]` to confirm and whitelist.
*   **Slash Command `/debug`**:
    *   An interactive diagnostic control panel for any movie.

---

## Acceptance Criteria
*   The Plex adapter successfully queries match candidates and rematches items programmatically.
*   The `mismatch_guard` successfully flags mismatched test entries (e.g., "Predator Badlands" mapping to "Predator (1987)") and ignores close/exact matches.
*   Discord buttons and modals handle Plex operations asynchronously, preventing interaction timeouts (exceeding 3s).
*   Corrected Plex matches automatically synchronize back to the local SQLite database.
*   A comprehensive unit and integration testing suite validates similarity matching and Plex API mock behaviors.
