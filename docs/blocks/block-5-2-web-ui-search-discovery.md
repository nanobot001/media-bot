# Block 5.2: Web UI Search & Discovery

## Objective
Implement the "Discovery" (Search) tab in the Web UI to allow users to search for new movies using Jackett/Prowlarr and queue them for download via IDM, directly bypassing Discord.

## Requirements
- Consume the backend search endpoints (leveraging `search_sources_tool`).
- Display search results in a clean list or grid, prioritizing the highest quality/seeders.
- Provide a "Download" button on each result that triggers `enqueue_download_tool`.
- Once a download is queued, gracefully transition the UI state (perhaps redirecting to the Dashboard or showing a success toast) and rely on the SSE stream to show progress.

## Acceptance Criteria
- [ ] A search bar is available on the Discovery tab.
- [ ] Searching successfully queries Jackett and displays parsed results.
- [ ] Each result clearly shows resolution, size, and source tracker.
- [ ] Clicking "Download" sends the payload to the backend and adds it to the SQLite queue.
