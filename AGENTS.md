# Agent Instructions

Use `docs/project-charter.md` as the top-level project authority. Use `docs/blocks/` for scoped AI-buildable tickets and implement one selected block at a time.

When implementing a block, update project docs only when the work creates or changes durable knowledge future blocks need. Use the relevant docs area and avoid documentation churn for trivial edits.

For numbered block work, use the global `implement-block` skill. Do not create project-specific local skills unless a repeated workflow becomes too specialized for this file and the project docs.

## Tool-Friendly Project Rules

This project may be called by another program, bot, supervisor, CLI wrapper, local HTTP API, or future MCP-style wrapper.

Before changing worker behavior, state persistence, tool outputs, permissions, or adapter routes, read:

- `docs/tool-adapter-memory.md`
- `docs/tool-surface.md`
- `docs/tool-manifest.yaml`
- `docs/permissions.md`
- `docs/event-log-schema.md`

Rules:

- Preserve structured JSON outputs for tool-facing commands.
- Do not remove dry-run behavior from write/admin/destructive tools.
- Do not expose secrets, private paths, API keys, tokens, or sensitive local details in public-read tools.
- Do not treat human text logs as the source of truth if structured state exists.
- Keep tool names stable once published.
- Record meaningful domain events in the local state layer.
- Record structured errors.
- Keep a cheap verification command for the tool contract.
- Preserve the project's normal runtime model, including PM2, cron, Task Scheduler, Docker Compose, or systemd if used.
