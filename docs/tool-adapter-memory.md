# Tool Adapter Memory

## Project Role

TODO: Describe what this project does.

## Classification

TODO: New tool-friendly project, existing tool/service adapted for tool-friendliness, or tool-capable project with light notes only.

## Runtime Model

TODO: one-shot CLI, long-running worker, PM2-managed worker, scheduled job, local HTTP service, Docker service, n8n workflow wrapper, or other.

## Source Of Truth

TODO: SQLite, Postgres, JSONL, external API, files/folders, or other.

## Existing Pieces Reused

For existing projects, list entrypoints, API routes, CLI commands, PM2 config, databases, logs, and state files that were found and reused.

## Adaptation Gaps Filled

For existing projects, list what was added or normalized.

## Tool Surface

List planned or implemented tools.

## Permission Boundaries

Describe which tools are public-read, trusted-read, write-action, admin-action, or destructive-action.

## State/Event Schema

Describe what gets stored and why.

Do not store raw tokens, API keys, session cookies, OAuth credentials, or private secrets in `kv_store` unless this project has an explicit local secret-storage policy.

## Bot Usage Notes

Describe how a Discord bot, supervisor, or other program should call this project.

## Do Not Break

List assumptions future agents must preserve.

## Known Limitations

List what is not implemented yet.

## Verification Commands

List commands to prove the tool adapter still works.
