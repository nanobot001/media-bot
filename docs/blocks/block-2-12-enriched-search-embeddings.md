# Block 2-12: Enriched Search Embeddings & Backfill

> Status: Planned.
> Result: Not implemented.
> Notes: Replaces raw synopsis embeddings with metadata-enriched composite search documents (Title + Genres + Tones + Themes + Synopsis) to improve semantic classification and eliminate false positives in subjective searches.

## Goal

Transition the library's vector representation from raw movie synopses to metadata-enriched composite search documents. Provide a database-wide backfill runner to regenerate all vector embeddings, and enable/verify subjective query routing using the regression test suite.

## Scope

- **Composite Document Construction:**
  - Define a standard formatting function to build a text document for embedding. Format:
    ```text
    Title: [Title] ([Year])
    Genres: [Genre1, Genre2, ...]
    Tones: [Tone1, Tone2, ...]
    Themes: [Theme1, Theme2, ...]
    Synopsis: [Synopsis]
    ```
- **Ingestion & Sync Pipeline Update:**
  - Update `moviebot/api/webhook.py` (webhook syncs) and `moviebot/tools/sync_enrichment_tool.py` (enrichment syncs) to embed the composite document rather than the raw synopsis.
  - Update the hash tracking logic. Since metadata updates (like new tone tags) should trigger re-embedding, compile a `composite_hash` (MD5/SHA256 of the composite document string) and store it in `synopsis_hash` (or a new column, though reusing `synopsis_hash` is simpler and avoids migration churn).
- **Backfill Script:**
  - Create a PowerShell script `scripts/run-embeddings-backfill.ps1` that:
    - Backs up the SQLite database before performing writes.
    - Loops through all library items in batches.
    - Computes the new composite document and fetches its vector embedding.
    - Respects API rate limits (cooldown/pacing).
    - Saves the updated vector and hash back to the database.
- **Regression Harness Activation:**
  - Remove the `@pytest.mark.xfail` decorator from the subjective query tests in `tests/test_query_library_semantic_regression.py` (e.g. `test_sad_movies_does_not_return_john_wick`).
  - Prove that semantic search correctly isolates subjective/mood query intent.

## Out Of Scope

- Do not perform schema migrations or add new vector columns if we can reuse `synopsis_vector` and `synopsis_hash`.
- Do not change the vector embedding model (`gemini-embedding-001`).
- Do not introduce natural language explanation or answer generation.

## Likely Files Or Areas

- `src/moviebot/core/embeddings.py`
- `src/moviebot/tools/sync_enrichment_tool.py`
- `src/moviebot/api/webhook.py`
- `src/moviebot/cli/tool_cli.py`
- `scripts/run-embeddings-backfill.ps1`
- `tests/test_query_library_semantic_regression.py`

## Acceptance Criteria

- The backfill script regenerates vectors for the entire library successfully.
- Webhook syncs automatically compute embeddings using the composite document format.
- Changing a movie's metadata (e.g., adding a new tone tag) changes its composite hash and triggers re-embedding on the next sync.
- `pytest tests/test_query_library_semantic_regression.py` passes all assertions, proving that `"sad movies"` ranks the somber drama highly and does **not** return action thrillers like *John Wick*.

## Verification

- `py -3.12 -m pytest tests/test_query_library_semantic_regression.py`
- Execute the backfill script in dry-run/audit mode, confirming correct composite document strings are generated.
- Run a non-dry-run backfill on a small batch to confirm vectors and hashes are persisted correctly.
