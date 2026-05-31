# Blocks Index: Media Bot

This folder contains numbered, bounded, and verifiable tickets for developing the `media-bot` MVP.

---

## 📋 Block Status Index

| Block ID | Title | Status | Main Deliverables |
| :--- | :--- | :--- | :--- |
| **[Block 00](completed/block-00-project-definition.md)** | Project Definition | Done | Charter, design principles, and locked rules. |
| **[Block 01](completed/block-01-integration-verification.md)** | Integration Verification | Done | Automated validation checks and API token configurations. |
| **[Block 02](completed/block-02-discord-gateway.md)** | Discord Gateway | Done | Slash commands registration, channel constraints, status cards. |
| **[Block 03](completed/block-03-tautulli-webhooks.md)** | Tautulli Webhooks | Done | Webhook receiver to sync library on media events. |
| **[Block 04](completed/block-04-space-management.md)** | Space Management Guard | Deprecated | Disk monitor with auto-cleanup of watched files (Handled by external media-watcher). |
| **[Block 04-1](completed/block-04-1-jobs-and-diagnostics.md)** | Active Jobs & Diagnostics | Completed | Job tracking, debrid resolver background loop, error log inspector. |
| **[Block 05](completed/block-05-mcp-integration.md)** | MCP Server Wrapper | Completed | Exposing tools to AI agents using Model Context Protocol. |
| **[Block 06](completed/block-06-system-diagnostics.md)** | System Diagnostics | Completed | Observability tools, FastAPI telemetry routes, slash commands `/status` & `/health`, unit tests. |
| **[Block 07](completed/block-07-discord-observability-matchdoctor.md)** | Discord Match Doctor | Completed | Mismatch Guard engine, Plex rematching API, interactive Discord repair UI, `/debug` command. |
| **[Block 08](completed/block-08-pipeline-status-card.md)** | Pipeline Status Card | Done | Live Discord status card tracking each download across Debrid → IDM → media-watcher → Plex. |
| **[Block 2-1](completed/block-2-1-library-schema-fts5.md)** | Media Intelligence Schema & FTS5 | Completed | SQLite schema migrations, trigger-backed FTS5 virtual tables, metadata hashing, and dry-run intelligence backfill. |
| **[Block 2-1b](completed/block-2-1b-quality-upgrade-dedupe.md)** | Quality Upgrade Deduplication | Completed | Conservative quality-upgrade allowance while preserving duplicate protection. |
| **[Block 2-2](block-2-2-embeddings-similarity.md)** | Vector Embedding & Similarity Engine | Proposed | Google Gemini / local Ollama embedding retrieval with caching, and cosine-similarity math. |
| **[Block 2-3](block-2-3-recommendation-taste-vector.md)** | Taste Recommender & Collection Audit | Proposed | Tautulli statistics taste vectors, cosine-similarity recommendations, and series gap auditing. |
| **[Block 2-4](block-2-4-discord-library-interface.md)** | Unified Discord & MCP Interface | Proposed | `/library`, `/recommend`, and `/audit` Discord commands with gap search buttons, MCP tools, and CLI subcommands. |

---

## 🤝 Block Guidelines

1. **Implement One Block at a Time**: Use the global `implement-block` skill. Do not write code for subsequent blocks until the active block is verified.
2. **Preserve JSON Envelopes**: Maintain strict separation of concerns; presentation layers must invoke the JSON tools, not execute raw adapter commands.
3. **Verify Every Step**: Write unit or integration tests for each block.
