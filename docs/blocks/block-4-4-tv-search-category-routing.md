# Block 4.4: TV Prowlarr Search & Category Routing

> Status: Implemented on 2026-08-23.
> Result: Implemented.
> Verification: `pytest tests/test_prowlarr_tv_search.py tests/test_mcp_server.py` and `pytest` - 279 passed.
> Notes: Implemented Category 5000/5030/5040/5045 TV search, structured season/episode query formatting, real-time AllDebrid instant cache checks, domain-isolated SQLite token caching (tvbot.sqlite3/tvclassicbot.sqlite3), CLI search-tv command, and FastMCP search_sources update.

## Objective
Generalize the Prowlarr search adapter to support Category `5000` (TV) queries alongside Category `2000` (Movies), with support for structured show titles, season numbers, and episode tags.

## Requirements
- Update `ProwlarrClient` to accept `categories` parameter (default 2000 for movies, 5000 for TV, or specific TV subcategories like 5030 for SD, 5040 for HD, 5045 for UHD).
- Support structured TV query parsing:
  - Show Title only (e.g. `Shogun`).
  - Season query (e.g. `Shogun S01`, `Shogun Season 1 Complete`).
  - Episode query (e.g. `Shogun S01E01`, `Shogun 1x01`).
- Cache and obfuscate magnet URLs in the `search_results` SQLite repository using temporary hash tokens.
- Maintain backwards compatibility for existing movie search callers.

## Acceptance Criteria
- [x] `ProwlarrClient.search_tv` queries category 5000 properly.
- [x] Queries for full seasons vs individual episodes format search terms accurately.
- [x] Obfuscated magnet tokens are generated and cached for TV results.
- [x] Unit tests cover TV search queries, category mappings, and mock responses.

