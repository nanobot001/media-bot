import sys
from typing import Optional, Any, Dict, List
from mcp.server.fastmcp import FastMCP

from moviebot.db.connection import init_db
from moviebot.tools.search_library_tool import search_library_tool
from moviebot.tools.dedupe_check_tool import dedupe_check_tool
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.tools.enqueue_download_tool import enqueue_download_tool
from moviebot.tools.get_download_jobs_tool import get_download_jobs_tool
from moviebot.tools.get_error_logs_tool import get_error_logs_tool
from moviebot.tools.query_watch_history_tool import query_watch_history_tool
from moviebot.tools.resolve_pending_jobs_tool import resolve_pending_jobs_tool
from moviebot.tools.check_movie_state_tool import check_movie_state_tool
from moviebot.tools.get_system_health_tool import get_system_health_tool
from moviebot.tools.get_tool_manifest_tool import get_tool_manifest_tool
from moviebot.tools.get_recent_events_tool import get_recent_events_tool
from moviebot.tools.tail_logs_tool import tail_logs_tool
from moviebot.tools.query_library_tool import query_library_tool
from moviebot.tools.recommend_movies_tool import recommend_movies_tool
from moviebot.tools.audit_collections_tool import audit_collections_tool
from moviebot.tools.sync_enrichment_tool import sync_enrichment_tool


# Initialize the FastMCP server
mcp = FastMCP("media-bot")


@mcp.tool(name="query_library")
async def mcp_query_library(
    query: Optional[str] = None,
    semantic_query: Optional[str] = None,
    genre: Optional[str] = None,
    director: Optional[str] = None,
    resolution: Optional[str] = None,
    watch_status: Optional[str] = None,
    max_runtime: Optional[int] = None,
    min_rating: Optional[float] = None,
    setting_location: Optional[str] = None,
    premise_tag: Optional[str] = None,
    character_tag: Optional[str] = None,
    theme_tag: Optional[str] = None,
    tone_tag: Optional[str] = None,
    craft_tag: Optional[str] = None,
    studio: Optional[str] = None,
    brand: Optional[str] = None,
    franchise: Optional[str] = None,
    universe: Optional[str] = None,
    source_property: Optional[str] = None,
    actor: Optional[str] = None,
    content_rating: Optional[str] = None,
    award_tag: Optional[str] = None,
    source_material_tag: Optional[str] = None,
    popularity_tag: Optional[str] = None,
    cultural_impact_tag: Optional[str] = None,
    exclude_content_warnings: Optional[List[str]] = None,
    exclude_warning_level: str = "mild",
    include_unknown_content_warnings: bool = False,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Search the local media intelligence database with exact filters, FTS5 text matching, and optional semantic ranking.

    Args:
        query: FTS5 match query against title, synopsis, genres, directors.
        semantic_query: Text prompt for semantic vector similarity matching.
        genre: Case-insensitive genre filter.
        director: Case-insensitive director filter.
        resolution: Exact/case-insensitive resolution filter.
        watch_status: Exact/case-insensitive watch status filter.
        max_runtime: Upper limit for movie runtime.
        min_rating: Lower limit for movie rating.
        setting_location: Exact structured setting location filter.
        premise_tag: Exact structured premise tag filter.
        character_tag: Exact structured character tag filter.
        theme_tag: Exact structured theme tag filter.
        tone_tag: Exact structured tone tag filter.
        craft_tag: Exact structured craft tag filter.
        studio: Studio/brand filter.
        brand: Brand filter.
        franchise: Franchise filter.
        universe: Universe filter.
        source_property: Source property filter.
        actor: Actor/cast-name filter.
        content_rating: Plex content rating filter.
        award_tag: Award/acclaim hard-fact tag filter.
        source_material_tag: Source material hard-fact tag filter.
        popularity_tag: Popularity hard-fact tag filter.
        cultural_impact_tag: Cultural impact hard-fact tag filter.
        exclude_content_warnings: Warning names to exclude.
        exclude_warning_level: Minimum warning severity to exclude.
        include_unknown_content_warnings: Include unknown warning rows instead of excluding conservatively.
        limit: Max number of records to return.
    """
    return await query_library_tool(
        query=query,
        semantic_query=semantic_query,
        genre=genre,
        director=director,
        resolution=resolution,
        watch_status=watch_status,
        max_runtime=max_runtime,
        min_rating=min_rating,
        setting_location=setting_location,
        premise_tag=premise_tag,
        character_tag=character_tag,
        theme_tag=theme_tag,
        tone_tag=tone_tag,
        craft_tag=craft_tag,
        studio=studio,
        brand=brand,
        franchise=franchise,
        universe=universe,
        source_property=source_property,
        actor=actor,
        content_rating=content_rating,
        award_tag=award_tag,
        source_material_tag=source_material_tag,
        popularity_tag=popularity_tag,
        cultural_impact_tag=cultural_impact_tag,
        exclude_content_warnings=exclude_content_warnings,
        exclude_warning_level=exclude_warning_level,
        include_unknown_content_warnings=include_unknown_content_warnings,
        limit=limit
    )


@mcp.tool(name="recommend_movies")
async def mcp_recommend_movies(user: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
    """
    Runs the taste recommender algorithm to rank owned, unwatched library items using taste vectors.

    Args:
        user: Filter watch history by viewer username.
        limit: Max number of recommendation entries to return.
    """
    return await recommend_movies_tool(user=user, limit=limit)


@mcp.tool(name="audit_collections")
async def mcp_audit_collections() -> Dict[str, Any]:
    """
    Scans the database for movies tagged with collections, groups them, and audits them for sequence gaps or missing sequels.
    """
    return await audit_collections_tool()


@mcp.tool(name="sync_enrichment")
async def mcp_sync_enrichment(
    dry_run: bool = True,
    limit: int = 50,
    provider: str = "rules",
    offset: int = 0,
    only_missing_hard_facts: bool = False,
    only_missing_brands: bool = False,
) -> Dict[str, Any]:
    """
    Generate structured setting, premise, character, theme, tone, craft, and content-warning metadata.

    Args:
        dry_run: Preview output without writing to SQLite.
        limit: Max number of library items to process.
        provider: Metadata provider, either rules or gemini.
        offset: Skip this many matching rows before processing.
        only_missing_hard_facts: Process only rows with at least one empty hard-fact field.
        only_missing_brands: Process only rows missing TMDb brand/franchise metadata.
    """
    return await sync_enrichment_tool(
        dry_run=dry_run,
        limit=limit,
        provider=provider,
        offset=offset,
        only_missing_hard_facts=only_missing_hard_facts,
        only_missing_brands=only_missing_brands,
    )


@mcp.tool(name="search_library")
async def mcp_search_library(title: str, year: Optional[int] = None) -> Dict[str, Any]:
    """
    Search the local SQLite state mirror for a movie.

    Args:
        title: The title of the movie to search for.
        year: The optional release year of the movie.
    """
    return await search_library_tool(title=title, year=year)


@mcp.tool(name="dedupe_check")
async def mcp_dedupe_check(title: str, year: int, imdb_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Applies the tiered normalization engine to classify input titles against the library mirror.

    Args:
        title: Movie title string.
        year: Movie release year.
        imdb_id: Optional IMDb identifier (e.g., tt1234567).
    """
    return await dedupe_check_tool(title=title, year=year, imdb_id=imdb_id)


@mcp.tool(name="search_sources")
async def mcp_search_sources(query: str, imdb_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Search Prowlarr indexers for movies, filtering to category 2000 and obfuscating URLs.

    Args:
        query: Search keywords query.
        imdb_id: Optional IMDb identifier (e.g., tt1234567).
    """
    return await search_sources_tool(query=query, imdb_id=imdb_id)


@mcp.tool(name="enqueue_download")
async def mcp_enqueue_download(
    reference_id: str,
    dry_run: bool = False,
    selected_file_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Downloads torrent/magnet from Prowlarr via AllDebrid and delegates to IDM.

    Args:
        reference_id: Obfuscated reference hash key from search results.
        dry_run: Perform dry-run flow validation without sending to real IDM or AllDebrid.
        selected_file_id: Optional file ID to bypass variance prompts.
    """
    return await enqueue_download_tool(
        reference_id=reference_id,
        dry_run=dry_run,
        selected_file_id=selected_file_id
    )


@mcp.tool(name="get_download_jobs")
async def mcp_get_download_jobs(active_only: bool = True, limit: int = 50) -> Dict[str, Any]:
    """
    Retrieve active or historical download jobs from the local database.

    Args:
        active_only: List only active jobs (downloading/pending/requires_selection) (default: True).
        limit: Max entries to return when listing all historical jobs (default: 50).
    """
    return await get_download_jobs_tool(active_only=active_only, limit=limit)


@mcp.tool(name="get_error_logs")
async def mcp_get_error_logs(limit: int = 50) -> Dict[str, Any]:
    """
    Retrieve recent diagnostic error logs from the database.

    Args:
        limit: Max error log entries to return (default: 50).
    """
    return await get_error_logs_tool(limit=limit)


@mcp.tool(name="query_watch_history")
async def mcp_query_watch_history(
    user: Optional[str] = None,
    title: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Query Plex watch history logs from Tautulli to answer who watched what, when, and how.

    Args:
        user: Filter by viewer username.
        title: Filter by movie title search term.
        limit: Max entries to return (default: 50).
    """
    return await query_watch_history_tool(user=user, title=title, limit=limit)


@mcp.tool(name="resolve_pending_jobs")
async def mcp_resolve_pending_jobs(dry_run: bool = False) -> Dict[str, Any]:
    """
    Sweeps database for jobs in 'pending' status, queries AllDebrid,
    resolves direct links, sends to IDM, and updates database statuses.

    Args:
        dry_run: Perform dry-run flow validation.
    """
    return await resolve_pending_jobs_tool(dry_run=dry_run)


@mcp.tool(name="check_movie_state")
async def mcp_check_movie_state(title: str, year: Optional[int] = None) -> Dict[str, Any]:
    """
    Search Plex DB mirror, AllDebrid downloads, active IDM jobs, folders, and logs for a movie.

    Args:
        title: Title of the movie to search.
        year: Optional release year.
    """
    return await check_movie_state_tool(title=title, year=year)


@mcp.tool(name="get_system_health")
async def mcp_get_system_health() -> Dict[str, Any]:
    """
    Get deep system monitoring (PM2 process metrics, disk spaces, API connectivity).
    """
    return await get_system_health_tool()


@mcp.tool(name="get_tool_manifest")
async def mcp_get_tool_manifest() -> Dict[str, Any]:
    """
    Load and parse the tool-manifest.yaml file describing all available tools.
    """
    return await get_tool_manifest_tool()


@mcp.tool(name="get_recent_events")
async def mcp_get_recent_events(limit: int = 50) -> Dict[str, Any]:
    """
    Retrieves the most recent system event logs from the SQLite database.

    Args:
        limit: Max events to retrieve (default: 50).
    """
    return await get_recent_events_tool(limit=limit)


@mcp.tool(name="tail_logs")
async def mcp_tail_logs(source: str, lines: int = 100) -> Dict[str, Any]:
    """
    Tails specified logs ('watcher', 'bot-out', 'bot-err') for troubleshooting.

    Args:
        source: Log file source name.
        lines: Number of lines to tail (default: 100, max: 500).
    """
    return await tail_logs_tool(source=source, lines=lines)



def main():
    try:
        init_db()
    except Exception as e:
        print(f"Failed to initialize database: {e}", file=sys.stderr)
        sys.exit(1)
    
    # FastMCP uses stdio transport by default when run() is called
    mcp.run()


if __name__ == "__main__":
    main()
