# Block 2-3: Taste Recommender & Collection Gap Audit

> Status: Proposed
> Result: Pending
> Verification: Run `pytest tests/test_intelligence.py` to verify recommendation matching and gap calculations.

## Goal
Implement a recommendation profiler using Tautulli watch stats (building Taste Vectors and matching unwatched items) and a Collection Gap Auditing utility to find missing parts in film series.

## Scope
* **Taste Profiler**:
  * Create `moviebot/core/taste_profiler.py`.
  * Retrieve watch history stats from Tautulli database/API (counting watched genres and directors).
  * Load synopsis vectors of movies the user has watched.
  * Compute a **Taste Vector** by averaging the dimensions of the watched movies' vectors.
  * Compare the Taste Vector against unwatched movies' vectors using cosine similarity.
  * Combine with statistical preferences (matches in favorite genres/directors) to return the top recommendations.
* **Collection Gap Audit**:
  * Aggregate the library items by Plex Collection.
  * Prefer stable collection identifiers such as TMDb collection IDs when available; otherwise fall back to Plex collection titles.
  * Parse collection titles and index names (e.g. "John Wick Collection" or "The Dark Knight Trilogy") as a best-effort local fallback.
  * Analyze sequence gaps (identifying missing index numbers, sequels, or checking TMDb/Plex metadata rules to identify which parts are missing) and mark confidence in the result.
  * Return a gap report structure listing the collection name, owned items, and missing items.

## Out Of Scope
* Implementing the Discord UI buttons or embed formatting (this will be done in the interface block).
* Modifying database tables.

## Implementation Instructions
1. Implement `generate_taste_vector(watched_vectors: List[List[float]]) -> List[float]` inside `src/moviebot/core/taste_profiler.py`.
2. Write `recommend_movies(db_conn) -> List[Dict]` returning ranked list of movies.
3. Write `audit_collections(db_conn) -> List[Dict]` returning collections with missing sequences.

## Acceptance Criteria
* Statistical taste aggregation accurately weights the user's top genres based on Tautulli watch counts.
* If a user has watched several Action/Sci-Fi movies, the recommendation system ranks other Action/Sci-Fi movies higher.
* The collection gap auditor correctly flags that *John Wick: Chapter 3* is missing if the user only has parts 1, 2, and 4 in their library.
* Gap reports include a confidence field so title-parsing guesses are distinguishable from metadata-backed collection matches.

## Verification Commands
```powershell
$env:PYTHONPATH="src"
pytest tests/test_intelligence.py -k "test_taste_recommender"
pytest tests/test_intelligence.py -k "test_collection_gaps"
```
