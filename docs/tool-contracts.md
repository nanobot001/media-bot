# Tool Surface Contracts

This document defines the strict Input and Output JSON schemas for the core tools in `movie-media-bot`.

---

## 1. General Response Envelope

Every tool execution must return a standardized JSON format.

### Success Envelope
```json
{
  "ok": true,
  "tool": "tool_name",
  "timestamp": "2026-10-24T14:32:00Z",
  "data": {}
}
```

### Error Envelope
```json
{
  "ok": false,
  "tool": "tool_name",
  "timestamp": "2026-10-24T14:32:00Z",
  "error": {
    "code": "ERROR_CODE_IDENTIFIER",
    "message": "Human-readable description of what failed.",
    "retryable": false,
    "severity": "error"
  }
}
```

---

## 2. Tool Definitions

### `search_library_tool`
Checks the local SQLite state mirror for matching titles.

*   **Input Schema:**
    ```json
    {
      "title": "string",
      "year": "integer (optional)"
    }
    ```
*   **Output Data (`data`):**
    ```json
    {
      "matches": [
        {
          "id": "item_id",
          "source": "plex",
          "title": "The Matrix",
          "year": 1999,
          "imdb_id": "tt0133093",
          "file_path": "F:\\movies\\The Matrix (1999)\\The Matrix (1999).mkv"
        }
      ]
    }
    ```

---

### `dedupe_check_tool`
Applies the tiered normalization engine to classify input titles against the mirror db.

*   **Input Schema:**
    ```json
    {
      "title": "string",
      "year": "integer",
      "imdb_id": "string (optional)"
    }
    ```
*   **Output Data (`data`):**
    ```json
    {
      "match_rating": "exact_guid | exact_title_year | fuzzy_likely | not_found",
      "action": "block | warn | allow",
      "details": "string description",
      "matched_item": {}
    }
    ```

---

### `search_sources_tool`
Queries Prowlarr indexers for the movie, filtering by Category 2000 (Movies). Obfuscates magnet hashes and direct tracker URLs.

*   **Input Schema:**
    ```json
    {
      "query": "string",
      "imdb_id": "string (optional)"
    }
    ```
*   **Output Data (`data`):**
    ```json
    {
      "results": [
        {
          "reference_id": "obfuscated_hash_key",
          "title": "The Matrix Resurrections 2021 1080p BluRay",
          "size_bytes": 12845620942,
          "seeders": 45,
          "indexer": "YTS"
        }
      ]
    }
    ```

---

### `enqueue_download_tool`
Sends the magnet or torrent link to the debrid layer, selects the primary video file using pruning heuristics, and passes the resolved URL to the IDM bridge.

*   **Input Schema:**
    ```json
    {
      "reference_id": "string",
      "dry_run": "boolean"
    }
    ```
*   **Output Data (`data`):**
    ```json
    {
      "job_id": "generated_uuid_or_id",
      "magnet_id": "alldebrid_magnet_upload_id",
      "selected_file": "The.Matrix.Resurrections.2021.1080p.mkv",
      "target_dir": "F:\\_temp\\movies",
      "status": "pending | downloading | completed | failed",
      "dry_run": "boolean"
    }
    ```

*   **Payload Key Resolution:**
    The tool resolves the download URL from the cached `raw_json_payload` using this fallback chain:
    1. `downloadUrl` — used by Prowlarr search results and manual `/download` entries.
    2. `guid` — legacy Prowlarr field, used as fallback for older indexer payloads.

    Two entry points write `search_results` records:
    - **`/search` path**: `ProwlarrClient.search_movies()` stores the full Prowlarr API response object. The `downloadUrl` key is set by Prowlarr.
    - **`/download` path**: `discord_app.py` stores a minimal `{"downloadUrl": "<user_input>"}` payload. The `magnet_uri_hash` is a SHA-256 of the input URL.

