# System Architecture

## 1. Overview
The `movie-media-bot` is structured as a **tool-first, interface-second** application. The Discord bot interface and the Command Line Interface (CLI) are thin presentation layers that interact with the application logic through deterministic, schema-validated functional wrappers ("Tools").

---

## 2. Call Topology

```
[Discord Command UI]   OR   [CLI Terminal Client]   OR   [External Script/Cron]
          │                          │                         │
          └──────────────────────────┼─────────────────────────┘
                                     ▼
                      [Application Core / Orchestrator]
                                     │
                                     ▼
                        [Unified Tool Interface] 
                    (Accepts typed inputs, returns JSON)
                                     │
                                     ▼
                          [System Adapter Layer]
          (Plex, Prowlarr, AllDebrid, IDM Bridge, Tautulli)
                                     │
                                     ▼
                         [Target APIs / Local EXE]
```

Phase 5 durable availability state is also held in the primary Movies database:

- `release_variants` retains multiple exact releases per movie title/year or explicit TV scope, with independent AllDebrid, direct-play, and MediaFlow evidence plus first/last observation history.
- `release_catalog_checks` records bounded scope-level provider coverage. A fresh complete check with zero cached variants is required before deriving state A (`not_cached`).
- `prewarmed_cache` remains readable during the compatibility migration; catalog initialization adds or updates catalog rows without deleting legacy history.
- The optional production MediaFlow adapter consumes one exact freshly cached `release_variants` row, keeps signed local playback URLs behind short-lived opaque in-memory sessions, and persists only sanitized per-variant MediaFlow evidence and lifecycle events. Heavy work now passes a calibrated-profile or conservative-fallback admission gate with atomic CPU, memory, GPU, encoder-slot, and session reservations; it does not own direct-play truth or canonical A/B/C.
- MediaFlow failures use a versioned diagnostics projection with configuration, source-resolution, unlock, probe, delivery-policy, admission, capacity, URL-generation, browser-playback, and seek stages. A bounded localhost-only read route and dashboard `Why?` view expose only the configured off/summary/detailed projection; structured minimal failure truth remains active when verbose diagnostics are off.

---

## 3. Data Layout (Local SQLite Mirror)
The bot maintains a local state mirror in `data/moviebot.sqlite3` to reduce API latency when making queries to Plex and Tautulli.

### Schema Blueprint

```sql
-- local mirror tracking items currently on media servers
CREATE TABLE library_items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,          -- 'plex' or 'tautulli'
    rating_key TEXT,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,-- Alphanumeric clean string
    year INTEGER,
    imdb_id TEXT,
    file_path TEXT,
    size_bytes INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ledger of Prowlarr indexer search output results
CREATE TABLE search_results (
    id TEXT PRIMARY KEY,
    query_string TEXT NOT NULL,
    indexer TEXT NOT NULL,
    title TEXT NOT NULL,
    size_bytes INTEGER,
    seeders INTEGER,
    magnet_uri_hash TEXT NOT NULL, -- Redacted tracker representation
    raw_json_payload TEXT          -- Complete debug json payload dump
);

-- status tracking for AllDebrid magnet uploads to local IDM sweeps
CREATE TABLE download_jobs (
    id TEXT PRIMARY KEY,
    alldebrid_magnet_id TEXT,
    selected_file_name TEXT,
    target_dir TEXT DEFAULT 'F:\_temp\movies',
    status TEXT NOT NULL,          -- 'pending', 'downloading', 'completed', 'failed'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 4. Adapter Component Boundaries

*   **`ProwlarrClient`**: Communicates with the Prowlarr HTTP API categories endpoint (restricting search queries to category `2000` - Movies). Strips authentication/private tracker details before returning indexer links to the tool/UI layer.
*   **`AllDebridClient`**: Checks cache status of magnet hashes (`/v4/magnet/instant`), uploads magnets (`/v4/magnet/upload`), and resolves download links.
*   **`IdmAdapter`**: Manages download delegation. 
    *   *Container Mode:* Resolves URLs and posts payload to the Host-Side IDM Bridge listener running on the Windows host.
    *   *Monolithic Host Mode:* Interacts directly with the local Windows installation of `IDMan.exe` using command arguments.
*   **`PlexClient`**: Syncs active media libraries on Plex to the local SQLite mirror.
*   **`TautulliClient`**: Sweeps watch histories and confirms user watching metrics.
