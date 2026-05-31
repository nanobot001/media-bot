# Block 2-2: Vector Embedding & Similarity Engine

> Status: Proposed
> Result: Pending
> Verification: Run `pytest tests/test_intelligence.py` to verify API fallback execution and cosine-similarity correctness.

## Goal
Implement a vector embeddings utility to retrieve 768-dimension synopsis vectors from Gemini or local Ollama endpoints and calculate cosine similarity in Python.

## Scope
* **Embeddings API Integration**:
  * Create `moviebot/core/embeddings.py`.
  * Support loading `GEMINI_API_KEY` from environment.
  * If API key is present, target the Google AI Studio embeddings endpoint:
    `https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent`
  * Support a local Ollama configuration fallback (calling `http://localhost:11434/api/embeddings` with `nomic-embed-text`).
  * If no API keys or local services are available (e.g. offline testing), return a mock vector (768 floats).
* **Caching Layer**:
  * Ensure that when syncing a movie, an embedding call is made **only if** the movie's `synopsis_vector` is empty, `synopsis_hash` has changed, or the stored `synopsis_vector_model` / `synopsis_vector_dim` no longer matches the configured embedding model.
  * Persist `synopsis_vector_model`, `synopsis_vector_dim`, and `synopsis_vector_updated_at` when vectors are written.
* **Vector Math (Cosine Similarity)**:
  * Implement `cosine_similarity(v1: List[float], v2: List[float]) -> float` using standard math utilities (pure Python or lightweight helper, avoiding heavy scipy/numpy dependencies if possible, or using clean pure Python math for ease of containerization).
  * Expose vector encoding/decoding helpers to store raw lists of floats as BLOBs in SQLite database.

## Out Of Scope
* Implementing Tautulli logs parsing or recommendations.
* Implementing Discord interface.

## Implementation Instructions
1. Implement `get_embedding(text: str) -> List[float]` inside `src/moviebot/core/embeddings.py`.
2. Convert lists of floats to binary bytes (using `struct.pack('f' * 768, *vector)`) for DB BLOB storage, and `struct.unpack` on reading.
3. Write `cosine_similarity` using pure-Python:
   ```python
   def cosine_similarity(v1, v2):
       dot_product = sum(a * b for a, b in zip(v1, v2))
       norm_a = sum(a * a for a in v1) ** 0.5
       norm_b = sum(b * b for b in v2) ** 0.5
       if not norm_a or not norm_b:
           return 0.0
       return dot_product / (norm_a * norm_b)
   ```

## Acceptance Criteria
* Embedding retrieval correctly calls the Gemini REST endpoint when a valid API key is set.
* Offline mode falls back to generating consistent mock vectors for unit tests without network calls.
* Cosine similarity calculations match mathematical expectations (e.g. similarity of a vector with itself is 1.0, and perpendicular vectors is 0.0).
* Floats are encoded/decoded from SQLite database BLOB columns cleanly without precision loss.
* Re-running enrichment skips unchanged rows and re-embeds rows whose synopsis hash or embedding model metadata has changed.

## Verification Commands
```powershell
$env:PYTHONPATH="src"
pytest tests/test_intelligence.py -k "test_embeddings_and_similarity"
```
