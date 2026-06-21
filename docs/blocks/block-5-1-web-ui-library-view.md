# Block 5.1: Web UI Library View

## Objective
Implement the "Library" tab in the React Web UI to render a grid of all movies tracked in the local SQLite database (`LibraryItemRepository`), matching the glassmorphic aesthetic defined in `index.css`.

## Requirements
- Consume the existing `check_movie_state_tool` or a dedicated library REST endpoint to fetch all items.
- Display a responsive grid of movie posters (using TMDB poster URLs if available, or fallbacks).
- Render visual badges on the posters to indicate state (`MONITORED`, `DOWNLOADING`, `AVAILABLE`).
- Support basic client-side filtering (e.g., "Show Only Available", "Show Downloading").
- Strict enforcement of the "Tool-First" rule: the UI logic should be entirely decoupled and only consume the JSON output of the backend.

## Acceptance Criteria
- [ ] The Library tab successfully queries the FastAPI backend for the current movie roster.
- [ ] A 3-column (desktop) or 1-column (mobile) grid is displayed.
- [ ] Items show their title, release year, and current state.
- [ ] Clicking an item displays a modal or expanded view with more metadata.
