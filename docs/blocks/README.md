# Blocks Index: Media Bot

This folder contains numbered, bounded, and verifiable tickets for developing the `media-bot` MVP.

---

## 📋 Block Status Index

| Block ID | Title | Status | Main Deliverables |
| :--- | :--- | :--- | :--- |
| **[Block 00](block-00-project-definition.md)** | Project Definition | Done | Charter, design principles, and locked rules. |
| **[Block 01](block-01-integration-verification.md)** | Integration Verification | Done | Automated validation checks and API token configurations. |
| **[Block 02](block-02-discord-gateway.md)** | Discord Gateway | Planned | Slash commands registration, channel constraints, status cards. |
| **[Block 03](block-03-tautulli-webhooks.md)** | Tautulli Webhooks | Planned | Webhook receiver to sync library on media events. |
| **[Block 04](block-04-space-management.md)** | Space Management Guard | Planned | Disk monitor with auto-cleanup of watched files. |
| **[Block 05](block-05-mcp-integration.md)** | MCP Server Wrapper | Planned | Exposing tools to AI agents using Model Context Protocol. |

---

## 🤝 Block Guidelines

1. **Implement One Block at a Time**: Use the global `implement-block` skill. Do not write code for subsequent blocks until the active block is verified.
2. **Preserve JSON Envelopes**: Maintain strict separation of concerns; presentation layers must invoke the JSON tools, not execute raw adapter commands.
3. **Verify Every Step**: Write unit or integration tests for each block.
