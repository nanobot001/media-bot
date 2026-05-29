import sys
from typing import Optional, Any, Dict
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

# Initialize the FastMCP server
mcp = FastMCP("media-bot")


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
