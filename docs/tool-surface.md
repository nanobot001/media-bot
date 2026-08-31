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

## Multi-Library Domains & Routing

To scale across multiple media types, the system implements a domain database router. The following canonical domains are defined:
- `movies`: Routed to the baseline movie database (default).
- `anime`: Routed to the anime database.
- `tv`: Routed to the TV database.
- `tv_classic`: Routed to the TV Classic database.

Database connections and schema initializations can optionally specify a target domain. If omitted, they default to `movies` to preserve baseline compatibility.

## Existing Interface Mapping

For existing projects, document how existing commands, routes, or scripts map to the standardized tool surface.

- `search_sources` retains its compatibility `cached` boolean and additively returns sanitized `cache_status`, `cache_checked`, and `cache_error_code` fields per result plus bounded catalog population counts. Provider failures and missing partial results remain non-cached unknown evidence rather than successful uncached checks.
- `/api/prewarm/status` cycle history includes catalog discovered, retained, checked, cached, uncached, unknown, and provider-error counts sourced from release-catalog writes for that cycle.
- `discover_media`, `search_sources`, `/api/discover`, `/api/search`, and `/api/prewarm/items` add one shared catalog-derived `availability` projection with canonical scope identity, `availability_state`, A/B/C tier, coverage/freshness, bounded sanitized variants, and C-only direct-play aliases.
- Search and pre-warm release rows add `variant_availability_state` so an exact release can remain unknown or uncached even when another variant makes the requested title/scope B or C. `classic_tv` inputs read the canonical `tv_classic` catalog.
- `GET /api/mediaflow/status` is a local trusted-read projection of the disabled-by-default production adapter. `POST /api/mediaflow/playback` is a local write action with dry-run support that accepts only one exact freshly cached catalog variant and returns an opaque local session reference.
- `GET /api/mediaflow/diagnostics` is a bounded local trusted-read projection of versioned structured MediaFlow events. Visibility follows `off`, `summary`, or `detailed` mode while minimal stage/code truth remains available in every mode.
- MediaFlow session event, seek, and close routes retain sanitized decision, codec, accelerator, latency, reconnect, exit, and cleanup evidence. They never expose or persist raw provider URLs, credentials, authorization headers, or private command arguments, and MediaFlow evidence never changes canonical A/B/C.

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
