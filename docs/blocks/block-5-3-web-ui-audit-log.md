# Block 5.3: Web UI Audit Log & Dashboard

## Objective
Implement the "Audit" and "Dashboard" tabs to provide a high-level overview of system health and historical events.

## Requirements
- **Dashboard**: Use the SSE stream (`/api/stream`) to show real-time metrics, active downloads (from IDM), and PM2 uptime.
- **Audit Log**: Consume `get_recent_events_tool` to display a tabular, searchable view of the system's chronological event log (which is currently stored in SQLite via `EventRepository`).
- The Audit log must support pagination or virtualization if the list grows too large.

## Acceptance Criteria
- [ ] The Dashboard tab shows active background tasks and current system state.
- [ ] The Audit tab renders a table of recent events (INFO, WARN, ERROR).
- [ ] The UI scales gracefully on mobile devices.
