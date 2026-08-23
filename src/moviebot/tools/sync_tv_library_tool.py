import datetime
import logging
from typing import Dict, Any, Optional, List
from moviebot.adapters.plex_client import PlexClient
from moviebot.db.connection import init_db
from moviebot.db.repositories import TVLibraryRepository
from moviebot.core.dedupe import normalize_title

logger = logging.getLogger(__name__)


async def sync_tv_library_tool(
    domain: str = "tv",
    dry_run: bool = False,
    plex_client: Optional[PlexClient] = None
) -> Dict[str, Any]:
    """
    Synchronizes Plex TV and Classic TV library sections into SQLite databases
    ('tvbot.sqlite3' and 'tvclassicbot.sqlite3') with show hierarchies, season metadata,
    and granular episode inventories.

    Args:
        domain: Media domain to sync: 'tv' or 'tv_classic' (or 'classic_tv').
        dry_run: If True, fetches and reports items from Plex without modifying SQLite.
        plex_client: Optional injected PlexClient instance for testing.
    """
    tool_name = "sync_tv_library_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    domain_normalized = (domain or "tv").strip().lower()
    if domain_normalized in ("classic_tv", "tv_classic"):
        target_domain = "tv_classic"
    elif domain_normalized == "tv":
        target_domain = "tv"
    else:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "INVALID_DOMAIN",
                "message": f"Unsupported TV domain '{domain}'. Must be 'tv' or 'tv_classic' (or 'classic_tv').",
                "retryable": False,
                "severity": "error",
            }
        }

    client = plex_client or PlexClient()

    try:
        if not dry_run:
            init_db(target_domain)

        shows_data = await client.fetch_all_tv_shows(domain=target_domain)

        shows_synced = 0
        seasons_synced = 0
        episodes_synced = 0
        synced_shows_summary: List[Dict[str, Any]] = []

        for show in shows_data:
            show_id = show.get("id")
            title = show.get("title", "")
            norm_title = normalize_title(title)
            seasons = show.get("seasons", [])
            episodes = show.get("episodes", [])

            if not dry_run:
                TVLibraryRepository.upsert_show(
                    id=show_id,
                    rating_key=show.get("rating_key"),
                    title=title,
                    normalized_title=norm_title,
                    year=show.get("year"),
                    imdb_id=show.get("imdb_id"),
                    tmdb_id=show.get("tmdb_id"),
                    tvdb_id=show.get("tvdb_id"),
                    genres=show.get("genres"),
                    networks=show.get("networks"),
                    content_rating=show.get("content_rating"),
                    tagline=show.get("tagline"),
                    synopsis=show.get("synopsis"),
                    total_seasons=len(seasons),
                    total_episodes=len(episodes),
                    poster_url=show.get("poster_url"),
                    banner_url=show.get("banner_url"),
                    domain=target_domain,
                )

                for season in seasons:
                    TVLibraryRepository.upsert_season(
                        id=season.get("id"),
                        show_id=show_id,
                        season_number=season.get("season_number", 1),
                        title=season.get("title"),
                        episode_count=season.get("episode_count", 0),
                        domain=target_domain,
                    )

                for episode in episodes:
                    TVLibraryRepository.upsert_episode(
                        id=episode.get("id"),
                        show_id=show_id,
                        season_number=episode.get("season_number", 1),
                        episode_number=episode.get("episode_number", 1),
                        rating_key=episode.get("rating_key"),
                        title=episode.get("title"),
                        air_date=episode.get("air_date"),
                        synopsis=episode.get("synopsis"),
                        file_path=episode.get("file_path"),
                        size_bytes=episode.get("size_bytes"),
                        resolution=episode.get("resolution"),
                        bitrate_kbps=episode.get("bitrate_kbps"),
                        duration_ms=episode.get("duration_ms"),
                        domain=target_domain,
                    )

            shows_synced += 1
            seasons_synced += len(seasons)
            episodes_synced += len(episodes)

            synced_shows_summary.append({
                "id": show_id,
                "title": title,
                "year": show.get("year"),
                "tmdb_id": show.get("tmdb_id"),
                "imdb_id": show.get("imdb_id"),
                "seasons_count": len(seasons),
                "episodes_count": len(episodes),
            })

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "domain": target_domain,
                "dry_run": dry_run,
                "shows_synced": shows_synced,
                "seasons_synced": seasons_synced,
                "episodes_synced": episodes_synced,
                "shows": synced_shows_summary,
            }
        }

    except Exception as e:
        logger.exception("Error executing sync_tv_library_tool for domain '%s': %s", target_domain, e)
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "TV_SYNC_FAILED",
                "message": f"TV library sync failed for domain '{target_domain}': {str(e)}",
                "retryable": True,
                "severity": "error",
            }
        }
