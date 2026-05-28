# Search, Deduplication, & Download Pipeline Flow

This document details the step-by-step path a media request takes from initial query to final IDM local queue enqueueing. Future agents must respect this flow when implementing updates.

---

## 🔄 The Pipeline Loop

```mermaid
sequenceDiagram
    actor User as Discord User / Agent
    participant Bot as Discord / CLI Presentation
    participant DB as SQLite Mirror
    participant Tools as Tool Surface (JSON)
    participant Prov as External Providers (Prowlarr/Plex/Debrid)
    participant Bridge as IDM HTTP Bridge

    User->>Bot: Request "/search <title>"
    Bot->>Tools: Run dedupe_check_tool(title)
    Tools->>DB: Query library_items table (Levenshtein match)
    DB-->>Tools: Local matches list
    Bot->>Tools: Run search_sources_tool(title)
    Tools->>Prov: Prowlarr API search (category 2000)
    Prov-->>Tools: Magnet & torrent results
    Tools->>DB: Store raw payloads & map ref_id hashes
    Tools-->>Bot: Safe results array (URLs obfuscated)
    Bot-->>User: Render local alerts + search buttons

    User->>Bot: Click download button (#index)
    Bot->>Tools: Run enqueue_download_tool(ref_id)
    Tools->>DB: Retrieve payload by ref_id hash
    Tools->>Prov: Upload magnet/torrent link (AllDebrid)
    Prov-->>Tools: Magnet ID & file manifest
    Tools->>Tools: Evaluate file_selection.py heuristics (exclude sample/trailers)
    alt Multiple video files within 10% size variance
        Tools-->>Bot: Return "requires_file_selection" status + candidates
        Bot-->>User: Display drop-down list of choices
        User->>Bot: Select file ID
        Bot->>Tools: Re-run enqueue_download_tool(ref_id, selected_file_id)
    end
    Tools->>Prov: Unlock stream link (AllDebrid)
    Prov-->>Tools: Direct direct-download URL
    Tools->>Bridge: Route POST /downloads with secret (IDM Bridge)
    Bridge->>Bridge: Start native IDMan.exe process
    Bridge-->>Tools: 200 OK / Success
    Tools->>DB: Write active record to download_jobs table
    Tools-->>Bot: Return success payload
    Bot-->>User: Post success confirmation card
```

---

## 🛠️ Verification Paths for Agents

To verify this flow programmatically without loading Discord:

1. **Query Local Mirror**:
   ```powershell
   py -3.8 -m moviebot.cli.tool_cli sync-library
   ```
2. **Perform Deduplication Check**:
   ```powershell
   py -3.8 -m moviebot.cli.tool_cli dedupe --title "The Matrix" --year 1999
   ```
3. **Trigger Prowlarr Search**:
   ```powershell
   py -3.8 -m moviebot.cli.tool_cli search --query "Matrix Resurrections"
   ```
4. **Trigger Flow (Dry Run)**:
   ```powershell
   py -3.8 -m moviebot.cli.tool_cli download --id "<obfuscated_ref_id>" --dry-run
   ```
5. **Query Watch History**:
   ```powershell
   py -3.8 -m moviebot.cli.tool_cli history --limit 5
   ```

---

## 📊 Watch History & Analytics Flow (Tautulli)

To support natural queries answering *"who watched what and when"*, the system exposes the Tautulli adapter logic:

1. **Parameters & Filtering**:
   The tool `query_watch_history_tool` handles filters for specific users (`--user`) or movie titles (`--query`).
2. **Generic API Gateway**:
   It issues calls to Tautulli's `get_history` API endpoint, translating raw Unix timestamps into formatted ISO datetime strings, and normalizing session percentages and media players.
3. **Structured Outputs**:
   The resulting schema returns a simplified list of logs detailing:
   * **`title`**: Movie or media item name.
   * **`user`**: The Plex account viewer.
   * **`date`**: ISO timestamp.
   * **`duration_minutes`**: Precise watching time.
   * **`player` & `media_type`**: Client device, resolution profiles, and category types.
