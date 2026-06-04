# Block 2-8: Plex Factual Discovery Fields

## Status

Completed

> Status: Implemented on 2026-05-31.
> Result: Implemented.
> Verification: Focused Plex metadata parsing and schema tests added; live Plex backfill not run in this block.
> Notes: Adds factual Plex metadata columns so studio/brand/person/audience queries have a stronger source before Gemini inference.

## Objective

Expand the Plex metadata mirror to store factual discovery fields that Plex already exposes, reducing avoidable reliance on LLM inference for queries like “Pixar movies,” actor searches, audience ratings, and content ratings.

## Fields

- `studios`
- `writers`
- `producers`
- `cast`
- `countries`
- `content_rating`
- `audience_rating`
- `tagline`
- `originally_available_at`
- `labels`

## Scope

- Parse the fields from Plex item metadata.
- Persist them in `library_items`.
- Include them in library sync and intelligence sync writes.
- Keep JSON arrays as JSON-encoded text, consistent with `genres`, `directors`, and `collections`.
- Do not add a third-party metadata API in this block.

## Follow-Up

Gemini enrichment should consume these factual fields before inferring brand/franchise/acclaim/audience facets.
