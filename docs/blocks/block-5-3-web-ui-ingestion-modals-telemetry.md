# Block 5.3: Web UI Ingestion Modals & Telemetry

> Status: Implemented on 2026-08-25.
> Result: Implemented.
> Verification: `pytest tests/test_web_ingest_telemetry.py` and `pytest` - passed (303/303 tests).
> Notes: Added 1-click movie grabs (/api/ingest), TV season/episode picker checklist modal with Plex inventory awareness (/api/tv/series-manifest, /api/tv/ingest-episodes), and floating live SSE telemetry bar (/api/stream).

## Objective
Implement domain-specific download modals (1-click Movie grabs, TV season/episode picker) with IDM handoff and a non-intrusive live download telemetry bar powered by SSE.

## Requirements
- Movie Download Modal:
  - 1-click `⚡ Download to IDM` button with automatic file selection and toast feedback.
- TV / Classic TV Download Modal:
  - Show header with series metadata, poster, and 1-click `⚡ Ingest Complete Series Pack (1080p)`.
  - Tabbed season switcher (`Season 1`, `Season 2`, `Complete Boxset`).
  - Interactive episode checklist (`S01E01`, `S01E02`), duration, file sizes, and `Download Selected Episodes` action.
- Live Telemetry Bar:
  - Fixed bottom status strip powered by SSE (`/api/stream`).
  - Displays real-time IDM download speeds (e.g. `32 MB/s`), active job counts, and engine status.

## Acceptance Criteria
- [x] Movie 1-click downloads dispatch directly to IDM and update live telemetry.
- [x] TV modal supports selecting individual episodes or full season packs for download.
- [x] SSE stream continuously updates live download speeds and job counts in the telemetry bar.
