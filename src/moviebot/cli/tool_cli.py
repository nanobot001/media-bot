import argparse
import asyncio
import json
import sys
from pathlib import Path
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.db.repositories import LibraryItemRepository
from moviebot.adapters.plex_client import PlexClient
from moviebot.core.dedupe import evaluate_deduplication, normalize_title
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.tools.enqueue_download_tool import enqueue_download_tool
from moviebot.tools.query_watch_history_tool import query_watch_history_tool


def cmd_configtest(args) -> int:
    """Executes environment checkups, directory existences, and DB connection readiness."""
    print("=== MovieBot System Configuration Test ===")
    
    # 1. Output directory check
    out_dir = Path(settings.output_dir)
    print(f"Checking Output Path: {out_dir}")
    if not out_dir.exists():
        print(f"  [ERROR] Output directory '{out_dir}' does not exist on this host.")
        print(f"  Please ensure the F:\\ drive is mounted or adjust OUTPUT_DIR in .env.")
        return 1
    
    # Check writability
    try:
        test_file = out_dir / ".write_test"
        test_file.touch()
        test_file.unlink()
        print("  [OK] Output directory is writable.")
    except Exception as e:
        print(f"  [ERROR] Output directory '{out_dir}' is NOT writable: {str(e)}")
        return 1

    # 2. Database verification
    db_path = Path(settings.database_path)
    print(f"Checking Database: {db_path}")
    try:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        # Attempt to run migrations/init
        init_db()
        print("  [OK] SQLite database successfully initialized and schema applied.")
    except Exception as e:
        print(f"  [ERROR] Failed to initialize SQLite database: {str(e)}")
        return 1

    # 3. Environment parameters checks
    warnings = 0
    services = {
        "Discord Token": settings.discord_token,
        "Prowlarr ApiKey": settings.prowlarr_api_key,
        "AllDebrid ApiKey": settings.alldebrid_api_key,
        "Plex Token": settings.plex_token,
        "Tautulli ApiKey": settings.tautulli_api_key,
    }
    for service, val in services.items():
        if not val:
            print(f"  [WARNING] Key missing: {service}")
            warnings += 1
        else:
            print(f"  [OK] Value set for: {service}")
            
    print(f"Config validation finished with {warnings} warnings.")
    return 0


async def cmd_sync_library(args) -> int:
    """Queries Plex movies and populates/syncs the local SQLite mirror database."""
    print("Syncing media items from Plex to local database mirror...")
    try:
        client = PlexClient()
        movies = await client.fetch_all_movies()
        print(f"Retrieved {len(movies)} movies from Plex API.")
        
        for m in movies:
            norm = normalize_title(m["title"])
            LibraryItemRepository.upsert(
                id=m["id"],
                source=m["source"],
                rating_key=m["rating_key"],
                title=m["title"],
                normalized_title=norm,
                year=m["year"],
                imdb_id=m["imdb_id"],
                file_path=m["file_path"],
                size_bytes=m["size_bytes"]
            )
        print("Successfully synchronized local database mirror.")
        return 0
    except Exception as e:
        print(f"Sync failed: {str(e)}")
        return 1


def cmd_dedupe(args) -> int:
    """Manually test the deduplication classification matrix against SQLite database."""
    print(f"Running Deduplication Check:")
    print(f"  Input Title: {args.title}")
    print(f"  Input Year:  {args.year}")
    print(f"  Input IMDb:  {args.imdb}")
    
    tier, action, details, item = evaluate_deduplication(
        title=args.title,
        year=args.year,
        imdb_id=args.imdb
    )
    
    print("\nResult:")
    print(f"  Match Rating: {tier}")
    print(f"  Action:       {action}")
    print(f"  Details:      {details}")
    if item:
        print(f"  Matched Item: {item['title']} ({item['year']}) [{item['source']}]")
    return 0


async def cmd_search(args) -> int:
    """Run search sources query via Prowlarr API."""
    print(f"Searching indexers for: '{args.query}'")
    res = await search_sources_tool(query=args.query, imdb_id=args.imdb)
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_download(args) -> int:
    """Downloads a torrent file via debrid by reference id."""
    print(f"Enqueuing download for reference ID: {args.id} (dryrun={args.dry_run})")
    res = await enqueue_download_tool(
        reference_id=args.id,
        dry_run=args.dry_run,
        selected_file_id=args.file_id
    )
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


async def cmd_history(args) -> int:
    """Queries Tautulli watch logs for active analytics and log histories."""
    print(f"Querying Tautulli watch history (user={args.user}, search={args.query}, limit={args.limit}):")
    res = await query_watch_history_tool(
        user=args.user,
        title=args.query,
        limit=args.limit
    )
    print(json.dumps(res, indent=2))
    return 0 if res["ok"] else 1


def main():
    parser = argparse.ArgumentParser(description="MovieBot Developer Command Line Tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # configtest
    subparsers.add_parser("configtest", help="Verify system configs and directory mounts")

    # sync-library
    subparsers.add_parser("sync-library", help="Sync Plex items to SQLite local database")

    # dedupe
    dedupe_parser = subparsers.add_parser("dedupe", help="Test title normalization & deduplication")
    dedupe_parser.add_argument("--title", required=True, help="Movie title string")
    dedupe_parser.add_argument("--year", type=int, required=True, help="Movie release year")
    dedupe_parser.add_argument("--imdb", help="Optional IMDb identifier")

    # search
    search_parser = subparsers.add_parser("search", help="Search Prowlarr indexers")
    search_parser.add_argument("--query", required=True, help="Search keywords query")
    search_parser.add_argument("--imdb", help="Optional IMDb identifier")

    # download
    download_parser = subparsers.add_parser("download", help="Download reference to debrid + IDM")
    download_parser.add_argument("--id", required=True, help="Obfuscated reference hash key from search results")
    download_parser.add_argument("--dry-run", action="store_true", help="Perform dry-run flow validation")
    download_parser.add_argument("--file-id", help="Optional file ID to bypass variance prompts")

    # history
    history_parser = subparsers.add_parser("history", help="Query Tautulli movie watch history log records")
    history_parser.add_argument("--user", help="Filter by viewer username")
    history_parser.add_argument("--query", help="Filter by movie title search term")
    history_parser.add_argument("--limit", type=int, default=10, help="Max entries to return (default: 10)")

    args = parser.parse_args()

    if args.command == "configtest":
        sys.exit(cmd_configtest(args))
    elif args.command == "sync-library":
        sys.exit(asyncio.run(cmd_sync_library(args)))
    elif args.command == "dedupe":
        sys.exit(cmd_dedupe(args))
    elif args.command == "search":
        sys.exit(asyncio.run(cmd_search(args)))
    elif args.command == "download":
        sys.exit(asyncio.run(cmd_download(args)))
    elif args.command == "history":
        sys.exit(asyncio.run(cmd_history(args)))


if __name__ == "__main__":
    main()

