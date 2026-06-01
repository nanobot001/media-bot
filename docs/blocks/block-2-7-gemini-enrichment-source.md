# Block 2-7: Gemini Enrichment Source

## Status

Completed

> Status: Implemented on 2026-05-31.
> Result: Implemented with limitations.
> Verification: Focused tests for Gemini provider and MCP delegation passed; live Gemini dry-run was not run in this block.
> Notes: Adds opt-in Gemini metadata generation for `sync-enrichment` while keeping rule enrichment as fallback and preserving dry-run defaults.

## Objective

Use Gemini as an optional metadata enrichment source that fills the typed enrichment v2 contract from existing title, year, genres, directors, and synopsis metadata.

## Scope

- Add a Gemini `generateContent` enrichment path.
- Keep rule-based enrichment as the default and fallback.
- Do not call Gemini from `/library`.
- Keep `sync-enrichment` dry-run by default.
- Preserve the existing JSON tool envelope.
- Store the provider/model used in enrichment metadata.

## Acceptance Criteria

- `sync-enrichment --provider gemini --limit N --json` previews Gemini enrichment without writing by default.
- `sync-enrichment --provider gemini --no-dry-run --limit N --json` writes Gemini-backed metadata.
- If Gemini is unavailable, the tool returns a structured error or falls back to rules with provider metadata.
- MCP `sync_enrichment` accepts the provider parameter.
- Tests cover Gemini output normalization without making live network calls.

## Notes

- This block does not require a full 421-row live Gemini backfill.
- A live backfill should be done in small batches to avoid free-tier rate limits.
