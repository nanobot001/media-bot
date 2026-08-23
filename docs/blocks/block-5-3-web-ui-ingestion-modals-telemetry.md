# Block 5.3: Web UI Ingestion Modals & Telemetry

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
- [ ] Movie 1-click downloads dispatch directly to IDM and update live telemetry.
- [ ] TV modal supports selecting individual episodes or full season packs for download.
- [ ] SSE stream continuously updates live download speeds and job counts in the telemetry bar.
