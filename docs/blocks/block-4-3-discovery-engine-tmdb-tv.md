# Block 4.3: Discovery Engine & TMDb TV Extension

> Status: Implemented on 2026-08-22.
> Result: Implemented.
> Verification: `pytest tests/test_discover_media.py tests/test_mcp_server.py` and `pytest` - 265 passed.
> Notes: Unified media discovery across Movies, TV, and Classic TV with TMDb TV extensions, genre/era/network filters, local library deduplication, CLI discover command, and FastMCP discover_media tool.

## Objective
Create a unified, domain-parameterized media discovery tool that fetches trending/popular releases from TMDb for Movies, TV, and Classic TV. Extend `TMDbFactProvider` with TV endpoints since every downstream block requires them. Deduplicate results against the local library.

## Requirements

### TMDb TV Extension (`tmdb_fact_provider.py`)
- Add TV-capable methods to the existing `TMDbFactProvider`:
  - `get_tv_id_by_imdb_id(imdb_id)` — reads `tv_results` from `/find/{imdb_id}`
  - `get_tv_id_by_title_year(title, year)` — calls `/search/tv`
  - `get_tv_show_facts(tv_id)` — calls `/tv/{id}?append_to_response=keywords,content_ratings`
  - `get_tv_season_facts(tv_id, season)` — calls `/tv/{id}/season/{n}`
  - `get_trending_movies(time_window)` — calls `/trending/movie/{day|week}`
  - `get_trending_tv(time_window)` — calls `/trending/tv/{day|week}`
  - `discover_movies(filters)` — calls `/discover/movie`
  - `discover_tv(filters)` — calls `/discover/tv`
- Parse TV content ratings from `content_ratings` (not `release_dates`).
- Respect existing 0.2s rate pacing and 429 backoff.

### Unified Discovery Tool (`tools/discover_media_tool.py`)
- Single tool with `domain` parameter (`movies`, `tv`, `classic_tv`):
  - `movies`: Trending Daily/Weekly, Popular English, New Digital/BluRay releases.
  - `tv`: Trending TV, Popular Airing, Top Rated Current Seasons.
  - `classic_tv`: Same as `tv` but with `first_air_date.lte=2010-01-01` default, era/decade presets (`50s`–`2000s`), and network filters (`NBC`, `CBS`, `ABC`, `FOX`, `HBO`, `BBC`).
- Filtering parameters:
  - `feed`: `trending` | `popular` | `digital` | `top_rated`
  - `genre`, `min_rating`, `year_range` / `decade`, `language` (default `en`)
  - `network` / `studio` (for TV/Classic TV)
  - `exclude_owned: bool` — cross-reference `LibraryItemRepository` to flag/filter already-owned titles
- Returns standardized JSON envelope with poster URLs, synopsis, TMDb ratings, year, genre tags, and `owned: bool` badge.

### Interfaces
- CLI: `python -m moviebot.cli.tool_cli discover [--domain movies|tv|classic_tv] [--feed trending] [--genre Action] [--min-rating 7.5] [--exclude-owned]`
- MCP tool: `discover_media`

### Explicitly Out of Scope
- **No FastAPI routes** (Phase 5 Block 5-1 owns API endpoints)
- **No ⚡ Lightning Cache Preview** (Phase 5 Block 5-2 owns cache badging at click-time)
- **No Discord presentation** (Block 4-9 owns Discord digest)

## Acceptance Criteria
- [x] `TMDbFactProvider` TV methods return structured show metadata (title, overview, genres, seasons, episode counts, networks, poster, ratings).
- [x] `discover_media_tool` returns filtered, deduped lists for all three domains.
- [x] Classic TV queries correctly apply era/decade and network presets.
- [x] `exclude_owned=True` accurately filters titles present in `LibraryItemRepository`.
- [x] CLI subcommand returns structured output and formatted table.
- [x] Unit tests cover TMDb TV endpoint calls (mocked), filtering logic, and dedup accuracy.

