# Blocks Index: Media Bot

This folder contains numbered, bounded, and verifiable tickets for developing the `media-bot` MVP.

---

## 📋 Block Status Index

| Block ID | Title | Status | Main Deliverables |
| :--- | :--- | :--- | :--- |
| **[Block 00](block-00-project-definition.md)** | Project Definition | Done | Charter, design principles, and locked rules. |
| **[Block 01](block-01-integration-verification.md)** | Integration Verification | Done | Automated validation checks and API token configurations. |
| **[Block 02](block-02-discord-gateway.md)** | Discord Gateway | Done | Slash commands registration, channel constraints, status cards. |
| **[Block 03](block-03-tautulli-webhooks.md)** | Tautulli Webhooks | Done | Webhook receiver to sync library on media events. |
| **[Block 04](block-04-space-management.md)** | Space Management Guard | Deprecated | Disk monitor with auto-cleanup of watched files (Handled by external media-watcher). |
| **[Block 04-1](block-04-1-jobs-and-diagnostics.md)** | Active Jobs & Diagnostics | Completed | Job tracking, debrid resolver background loop, error log inspector. |
| **[Block 05](block-05-mcp-integration.md)** | MCP Server Wrapper | Completed | Exposing tools to AI agents using Model Context Protocol. |
| **[Block 06](block-06-system-diagnostics.md)** | System Diagnostics | Completed | Observability tools, FastAPI telemetry routes, slash commands `/status` & `/health`, unit tests. |
| **[Block 07](block-07-discord-observability-matchdoctor.md)** | Discord Match Doctor | Proposed | Interactive pipeline status, mismatch alert guard, Plex API rematching via Discord modals. |

---

## 🤝 Block Guidelines

1. **Implement One Block at a Time**: Use the global `implement-block` skill. Do not write code for subsequent blocks until the active block is verified.
2. **Preserve JSON Envelopes**: Maintain strict separation of concerns; presentation layers must invoke the JSON tools, not execute raw adapter commands.
3. **Verify Every Step**: Write unit or integration tests for each block.
