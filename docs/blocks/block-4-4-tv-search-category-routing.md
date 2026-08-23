# Block 4.4: TV Prowlarr Search & Category Routing

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
- [ ] `ProwlarrClient.search_tv` queries category 5000 properly.
- [ ] Queries for full seasons vs individual episodes format search terms accurately.
- [ ] Obfuscated magnet tokens are generated and cached for TV results.
- [ ] Unit tests cover TV search queries, category mappings, and mock responses.
