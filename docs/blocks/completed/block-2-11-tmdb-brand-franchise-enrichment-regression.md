# Block 2-11: TMDb Franchise & Brand Enrichment Regression

> Status: Implemented on 2026-06-03.
> Result: Implemented.
> Verification: `pytest` - passed.
> Notes: Fully integrated TMDb-backed brand, franchise, universe, and source property facts, resolved alias mapping, added deterministic semantic regression test cases, and ran library-wide backfill on 427 movies.

## Goal

Add a TMDb-backed enrichment pass that stores normalized brand, franchise, universe, collection, and source-property facts for library movies, so compound library queries like `star wars space opera`, `pixar animated movies`, `bond spy movies`, `marvel superhero movies`, and `dc superhero movies` are answered from structured database truth instead of semantic similarity alone.

## Scope

- Add a TMDb fact provider that uses configured `TMDB_BEARER_TOKEN` or `TMDB_API_KEY` without exposing secrets in logs, tool output, events, or tests.
- Add explicit request throttling and resumable batching for TMDb lookups:
  - configurable batch size and delay between batches
  - conservative default request pacing
  - cooldown handling for `429`, `503`, timeout, and transient network errors
  - resume support with `limit`, `offset`, and/or `only_missing_*` filters.
- Prefer identifier-based lookups over title guessing:
  - use IMDb ID when available via TMDb `/find/{imdb_id}`
  - fall back to title/year search only with explicit source/confidence notes
  - fetch movie details with useful appended metadata such as keywords, credits, external IDs, and collections.
- Add durable normalized fields for franchise/brand/source-property style facts, likely including:
  - `brand_tags`
  - `franchise_tags`
  - `universe_tags`
  - `source_property_tags`
  - `brand_evidence_json`
  - `franchise_evidence_json`
  - `universe_evidence_json`
  - `source_property_evidence_json`
  - optional `tmdb_id` if not already persisted elsewhere.
- Build a deterministic alias resolver that maps raw TMDb/Plex/Wikidata/Gemini facts into canonical tags across many franchises and brands. Initial examples should include, but not be limited to:
  - `Marvel Studios`, `Marvel Comics`, `Marvel Cinematic Universe`, `MCU` -> `Marvel`
  - `DC Comics`, `DC Studios`, `DC Extended Universe`, `DCEU` -> `DC`
  - `Lucasfilm`, `Star Wars Collection`, `Star Wars` -> `Star Wars`
  - `Pixar Animation Studios`, `Pixar` -> `Pixar`
  - `Eon Productions`, `James Bond Collection`, `007` -> `James Bond`
  - `Wizarding World`, `Harry Potter Collection`, `Fantastic Beasts Collection` -> `Wizarding World`
  - `Middle-earth`, `The Lord of the Rings Collection`, `The Hobbit Collection` -> `Middle-earth`
  - `Jurassic Park Collection`, `Jurassic World Collection` -> `Jurassic Park`
  - `Star Trek`, `Star Trek Collection` -> `Star Trek`
  - `Fast & Furious Collection`, `The Fast and the Furious Collection` -> `Fast & Furious`
  - `Mission: Impossible Collection` -> `Mission: Impossible`
  - `Alien Collection`, `Predator Collection`, `Alien vs. Predator Collection` -> canonical collection/source-property tags without collapsing unrelated properties too aggressively.
  - preserve evidence showing which source and raw value supported each canonical tag.
- Integrate TMDb facts into the existing enrichment flow before Gemini normalization, while keeping Wikidata and Gemini as supplemental sources.
- Teach `query_library_tool` to decompose compound franchise/brand/category queries before semantic ranking:
  - `star wars space opera` -> franchise/source property `Star Wars` plus space-opera/category filters when available
  - `pixar animated movies` -> brand `Pixar` plus animation/category filters
  - `bond spy movies` -> franchise/source property `James Bond` plus spy/category filters
  - `marvel superhero movies` -> brand `Marvel` plus superhero/theme/source category
  - `dc superhero movies` -> brand `DC` plus superhero/theme/source category
  - `marvel movies`, `jurassic movies`, `mission impossible movies` -> matching canonical franchise/brand/source-property tags
  - `superhero movies` -> superhero/theme/source category without a brand filter.
- Create a focused regression harness for semantic-query truth claims, preferably split out from the large `tests/test_intelligence.py` into a dedicated module.
- Add or update a PowerShell runner for live backfills, following the existing `scripts/run-wikidata-enrichment.ps1` and `scripts/run-gemini-enrichment.ps1` pattern:
  - dry-run/audit first
  - optional database backup before non-dry-run writes
  - small batches
  - cooldown on rate limits
  - JSON response parsing
  - safe progress reporting without printing secrets.
- Preserve structured JSON tool envelopes, dry-run behavior, public-read redaction, and structured event recording for any non-dry-run enrichment pass.

## Out Of Scope

- Do not add TheTVDB in this block. Revisit it only if TMDb plus current Wikidata/Gemini enrichment cannot cover important franchise/brand/source-property gaps.
- Do not add conversational RAG, LLM answer synthesis, or natural-language explanations.
- Do not manually curate the full library in code.
- Do not let embeddings decide franchise, brand, universe, or source-property membership.
- Do not expose raw API tokens, private filesystem paths, or full unsanitized external API payloads in public tool responses.
- Do not change the PM2/runtime deployment model.

## Likely Files Or Areas

- `src/moviebot/config.py`
- `src/moviebot/db/connection.py`
- `src/moviebot/db/repositories.py`
- `src/moviebot/tools/tmdb_fact_provider.py`
- `src/moviebot/core/franchise_aliases.py`
- `src/moviebot/tools/fact_normalizer.py`
- `src/moviebot/tools/sync_enrichment_tool.py`
- `src/moviebot/tools/query_library_tool.py`
- `src/moviebot/cli/tool_cli.py`
- `src/moviebot/cli/mcp_server.py`
- `scripts/run-tmdb-enrichment.ps1`
- `scripts/run-gemini-enrichment.ps1`
- `scripts/run-wikidata-enrichment.ps1`
- `docs/tool-surface.md`
- `docs/tool-manifest.yaml`
- `tests/test_query_library_semantic_regression.py`
- `tests/test_intelligence.py`
- `tests/test_mcp_server.py`

## Suggested Design

- Keep TMDb access behind a small provider class with mocked HTTP tests.
- Support both auth modes:
  - bearer token via `Authorization: Bearer ...`
  - v3 API key via `api_key=...`
- Keep provider-level pacing independent from script-level batching. The provider should avoid rapid retry loops, while the PowerShell script should control full-library batch cadence.
- Treat TMDb rate-limit/availability failures as structured, retryable errors unless the response proves a permanent configuration or auth problem.
- Return a compact internal fact payload, not the raw TMDb response. Example:

```json
{
  "source": "tmdb",
  "tmdb_id": 1726,
  "imdb_id": "tt0371746",
  "title": "Iron Man",
  "collection": "Iron Man Collection",
  "production_companies": ["Marvel Studios"],
  "keywords": ["superhero", "based on comic"],
  "genres": ["Action", "Science Fiction", "Adventure"]
}
```

- Store normalized tags separately from raw evidence:
  - `brand_tags`: `["Marvel"]`
  - `franchise_tags`: `["Iron Man Collection", "Marvel Cinematic Universe"]` when supported
  - `universe_tags`: `["Marvel Cinematic Universe"]`, `["Wizarding World"]`, or `["Middle-earth"]` when supported
  - `source_property_tags`: `["Batman"]`, `["James Bond"]`, `["Star Wars"]`, or `["Jurassic Park"]` when supported
  - `source_material_tags`: include `comic book` or `comic book adaptation` when supported
  - `theme_tags` or `central_theme_tags`: include `superhero` when supported by TMDb keywords/genres or Gemini classification with evidence.
- Extend `hard_fact_sources_json` or add evidence fields so an operator can see whether a tag came from TMDb, Wikidata, Plex metadata, Gemini, or a resolver rule.
- In query routing, match known brand aliases as tokens inside longer phrases rather than treating the whole phrase before `movies` as a studio candidate.
- Keep semantic ranking secondary: structured filters decide membership, then similarity can rank within the filtered set.

## Regression Harness

Create deterministic fixtures that seed a tiny isolated SQLite database with:

- a Marvel superhero movie
- a DC superhero movie
- a Marvel non-superhero movie
- a non-Marvel superhero movie
- a Pixar animated movie
- a non-Pixar animated movie
- a James Bond spy movie
- a non-Bond spy movie
- a Star Wars space-opera/sci-fi movie
- a non-Star-Wars space/sci-fi movie
- at least one anti-case such as `Dark Superhero Movie` that must not infer brand `Dark`
- a gritty action movie with a tragic backstory (like *John Wick* with tragedy in the synopsis but no drama/somber tones)
- a slow somber drama movie (like *Schindler's List* with drama genre and somber/grieving tones)

Tests should prove:

- `marvel superhero movies` returns only the Marvel superhero fixture.
- `dc superhero movies` returns only the DC superhero fixture.
- `marvel movies` returns Marvel fixtures, including the non-superhero item.
- `superhero movies` returns both superhero fixtures across brands.
- `pixar animated movies` returns Pixar animation without returning every animated movie.
- `bond spy movies` returns James Bond spy fixtures without returning every spy movie.
- `star wars space movies` or `star wars sci-fi movies` returns Star Wars fixtures without returning every space/sci-fi movie.
- General category queries like `animated movies`, `spy movies`, and `space movies` remain broader when no franchise/brand token is present.
- `dark superhero movies` does not infer a `Dark` brand.
- Query routing reports structured filters such as `brand_tag`, `franchise_tag`, `source_property_tag`, and `theme_tag` or equivalent canonical names.
- Public result rows do not include `file_path`, raw vector blobs, API keys, or raw external payloads.
- Semantic metadata remains present when `semantic_query` is supplied, but semantic ranking cannot add rows excluded by structured filters.
- **Subjective / Mood Queries (Expected Failures in 2-11, to be resolved in 2-12):**
  - `sad movies` should return the somber drama fixture and **never** the gritty action movie fixture. (This test case must be marked with `@pytest.mark.xfail` in Block 2-11, to be enabled fully in Block 2-12).
  - `action movies` should return the gritty action movie fixture.

## Acceptance Criteria

- `settings` exposes TMDb config values and loads the existing `TMDB_BEARER_TOKEN` / `TMDB_BASE_URL` env entries.
- A TMDb provider can fetch or mock facts by IMDb ID and returns compact fact payloads with source attribution.
- TMDb lookup code has bounded timeout, retry/cooldown behavior, and tests for transient errors.
- The enrichment sync can run dry-run-first with TMDb facts included in previews and no database mutation.
- A non-dry-run enrichment pass persists normalized brand/franchise evidence and records a structured event.
- A PowerShell runner exists for TMDb enrichment, includes a backup step before writes, parses JSON responses, uses small batches, and cools down on rate-limit signals.
- `query_library_tool` supports compound franchise/brand/category routing for representative queries across superhero, animation, spy, and space/sci-fi examples.
- The regression harness proves the key positive and anti-case queries listed above.
- Existing hard-fact queries from Blocks 2-9 and 2-10 continue to pass.
- No public-read tool output exposes secrets, private paths, raw vectors, or full raw TMDb payloads.

## Verification

- `py -3.12 -m pytest tests/test_query_library_semantic_regression.py -q --basetemp C:\tmp\media-bot-pytest-semantic-regression`
- `py -3.12 -m pytest tests/test_intelligence.py tests/test_mcp_server.py -q --basetemp C:\tmp\media-bot-pytest-tmdb-enrichment`
- Dry-run TMDb enrichment command returns a JSON envelope with proposed brand/franchise tags and no DB mutation.
- PowerShell runner dry-run/audit mode completes without writing and without printing `TMDB_BEARER_TOKEN` or `TMDB_API_KEY`.
- A small non-dry-run enrichment pass writes normalized fields and records a structured local event.

## Deferred Follow-Up

- Evaluate TheTVDB only after this block shows concrete TMDb coverage gaps for franchise, source-property, or company facts.
- Consider an evaluation-set report for broader semantic discovery quality after deterministic regression coverage exists.
