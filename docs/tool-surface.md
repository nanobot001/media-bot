# Tool Surface

## Baseline Tools

Every tool-friendly project should aim to expose:

- `project.status`
- `project.health`
- `project.recent_events`
- `project.recent_errors`
- `project.tail_logs`
- `project.tool_manifest`

`project.tail_logs` may accept an optional logical `source` name for monitored logs. Treat this as a named source, not as an arbitrary local path supplied by a caller.

## Domain Tools

Add project-specific tools here.

### Media Intelligence Tools

- `query_library`: Public-read search over the local library intelligence database. Supports exact filters, Plex factual metadata filters, structured enrichment filters, hard-fact discovery filters for awards/source material/popularity/cultural impact, content-warning exclusions, FTS5 text search, and optional semantic ranking when embeddings are available. Results must not expose private filesystem paths.
- `recommend_movies`: Trusted-read recommendation tool that ranks owned, unwatched library items using taste vectors and local watch metadata.
- `audit_collections`: Public-read collection gap audit that reports owned items, likely missing entries, confidence, and search-ready missing-title labels.
- `sync_intelligence`: Admin/write-action backfill tool for refreshing metadata, FTS rows, and later embedding state. Must support `dry_run` and must not change download queue state.
- `sync_enrichment`: Write-action backfill tool for generating structured enrichment metadata from existing library fields using either local rules or Gemini. Must support dry-run by default and must not change download queue state.

## Existing Interface Mapping

For existing projects, document how existing commands, routes, or scripts map to the standardized tool surface.

## Output Contract

All tool outputs should be structured JSON.

Success shape:

```json
{
  "ok": true,
  "tool": "project.status",
  "timestamp": "2026-05-26T00:00:00-04:00",
  "data": {}
}
```

Error shape:

```json
{
  "ok": false,
  "tool": "project.status",
  "timestamp": "2026-05-26T00:00:00-04:00",
  "error": {
    "code": "STATE_DB_UNAVAILABLE",
    "message": "Could not open the local durable state database.",
    "retryable": true,
    "severity": "error"
  }
}
```
