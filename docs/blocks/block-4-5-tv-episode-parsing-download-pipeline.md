# Block 4.5: TV Episode Parsing & Download Pipeline

## Objective
Build the complete TV download pipeline: parse multi-file torrent manifests into structured episode lists, add batch AllDebrid link unlocking, extend IDM adapter for multi-file queueing, and route TV downloads to the correct destination directory. This is the single end-to-end block that makes TV downloading work.

## Requirements

### TV Episode File Selection (`core/tv_file_selection.py`)
- Parse multi-file torrent manifests (flat file lists from `AllDebridClient.get_magnet_files()`):
  - Extract Season and Episode numbers via regex patterns: `S(\d+)E(\d+)`, `(\d+)x(\d+)`, `Season (\d+)`, `E(\d+)`.
  - Distinguish single-episode releases from season packs (multiple episode files in one torrent).
  - Detect complete series box sets (files spanning multiple seasons).
- Heuristic exclusions: discard samples, trailers, `.nfo`, `.txt`, `.srt` zip containers, featurettes (reuse patterns from existing `file_selection.py`).
- Return structured episode envelopes:
  ```python
  [{"season": int, "episode": int, "filename": str, "size": int, "file_id": int, "link": str}, ...]
  ```

### Config & DB Infrastructure
- Add to `config.py` Settings:
  - `tv_output_dir: str = r"F:\_temp\tv"`
  - `tv_classic_output_dir: str = r"F:\temp\Classic Tv"`
- Fix `init_db()` in `connection.py` to bootstrap shared tables (`search_results`, `download_jobs`, `events`, `errors`, `kv_store`) for `tv` and `tv_classic` domains (currently skipped with `pass`).

### Batch AllDebrid Unlocking (`adapters/alldebrid_client.py`)
- Add `async def unlock_links(self, links: List[str]) -> List[str]` for batch stream URL resolution with rate pacing.

### Batch IDM Enqueue (`adapters/idm_adapter.py`)
- Add `async def send_batch_to_idm(self, downloads: List[Dict], dry_run: bool = False) -> List[Dict]` to queue multiple episode files without overwhelming the host bridge.
- Each item in the batch specifies `download_url`, `output_folder`, `file_name`.

### Extended Download Tool (`tools/enqueue_download_tool.py`)
- Add `domain: str = "movies"` parameter to route destination:
  - `movies` → `settings.output_dir` (`F:\_temp\movies`)
  - `tv` → `settings.tv_output_dir` (`F:\_temp\tv`)
  - `classic_tv` / `tv_classic` → `settings.tv_classic_output_dir` (`F:\temp\Classic Tv`)
- Add `selected_file_ids: Optional[List[int]]` parameter for multi-file TV episode selection.
- When multiple files are selected: unlock all links in batch → queue all to IDM → create one `download_jobs` record per episode.
- Maintain backward compatibility: single `selected_file_id` parameter still works for movies.

## Acceptance Criteria
- [ ] `tv_file_selection` correctly parses `S01E01`–`S01E24` from a season pack manifest and strips junk files.
- [ ] `init_db("tv")` and `init_db("tv_classic")` create shared tables without error.
- [ ] `tv_output_dir` and `tv_classic_output_dir` configs are available and default correctly.
- [ ] Batch `unlock_links` resolves multiple AllDebrid stream URLs.
- [ ] Batch `send_batch_to_idm` queues multiple files to IDM with structured responses.
- [ ] End-to-end test: search TV show → select episodes from manifest → unlock → queue to IDM at `F:\_temp\tv`.
- [ ] End-to-end test: search Classic TV show → select season pack → unlock → queue to IDM at `F:\temp\Classic Tv`.
- [ ] Existing movie download pipeline continues to work unchanged.
