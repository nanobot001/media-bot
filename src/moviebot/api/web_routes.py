import json
import asyncio
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, HTTPException
from moviebot.config import settings

from moviebot.tools.discover_media_tool import discover_media_tool
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.tools.tmdb_fact_provider import TMDbFactProvider
from moviebot.core.release_parser import parse_release_details, format_size_bytes
from moviebot.db.repositories import DownloadJobRepository, LibraryItemRepository, TVLibraryRepository
from moviebot.adapters.media_watcher_client import MediaWatcherClient
from moviebot.db.connection import get_db_connection


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["web_dashboard"])


from moviebot.core.discovery_cache import get_cached_detail, set_cached_detail, start_background_prewarming

@router.get("/discover")
async def api_discover(
    domain: str = Query(default="movies", description="Target domain (movies, tv, tv_classic)"),
    feed: str = Query(default="available_now", description="Feed category (available_now, trending, popular, top_rated, new)"),
    genre: Optional[str] = Query(default=None, description="Optional genre name"),
    sort_by: Optional[str] = Query(default=None, description="Optional sort order (date.desc, popularity.desc, rating.desc, votes.desc, title.asc)"),
    time_range: Optional[str] = Query(default=None, description="Optional release time window (30d, 60d, 90d, 6m, 1y, all)"),
    tier: Optional[str] = Query(default=None, description="Optional tier filter (major, indie)"),
    era: Optional[str] = Query(default=None, description="Optional era filter (e.g. 1980s)"),
    network: Optional[str] = Query(default=None, description="Optional TV network (e.g. HBO, NBC)"),
    language: Optional[str] = Query(default=None, description="Optional spoken/original language (e.g. en, ja, ko, es, fr, de, it, zh)"),
    page: int = Query(default=1, ge=1, description="Page number for pagination"),
    limit: int = Query(default=48, ge=1, le=100, description="Max results to return"),
) -> Dict[str, Any]:
    """Retrieves discovery cards from TMDb cross-referenced with local Plex library state."""
    start_background_prewarming()
    db_domain = "classic_tv" if domain in ("tv_classic", "classic_tv") else domain
    res = await discover_media_tool(
        domain=db_domain,
        feed=feed,
        genre=genre,
        sort_by=sort_by,
        time_range=time_range,
        tier=tier,
        decade=era,
        network=network,
        language=language,
        page=page,
        limit=limit
    )
    return res



@router.get("/details")
async def api_details(
    tmdb_id: int = Query(..., description="TMDb media ID"),
    domain: str = Query(default="movies", description="Domain: movies, tv, classic_tv"),
) -> Dict[str, Any]:
    """Fetches full deep details (cast, crew, runtime, trailer, etc.) for a movie or TV show."""
    dom_norm = domain.strip().lower()
    cached = get_cached_detail(dom_norm, tmdb_id)
    if cached is not None:
        return {"ok": True, "details": cached}

    provider = TMDbFactProvider()
    is_tv = dom_norm in ("tv", "tv_classic", "classic_tv")

    if is_tv:
        details = await asyncio.to_thread(provider.get_tv_full_details, tmdb_id)
    else:
        details = await asyncio.to_thread(provider.get_movie_details, tmdb_id)

    if not details:
        raise HTTPException(status_code=404, detail=f"Details not found for tmdb_id={tmdb_id}")

    set_cached_detail(dom_norm, tmdb_id, details)
    return {"ok": True, "details": details}


@router.get("/search")
async def api_search(
    query: str = Query(..., min_length=1, description="Search keywords or media title"),
    domain: str = Query(default="movies", description="Media domain (movies, tv, classic_tv, tv_classic)"),
    season: Optional[int] = Query(default=None, ge=1, description="Optional season number for TV"),
    episode: Optional[int] = Query(default=None, ge=1, description="Optional episode number for TV"),
    imdb_id: Optional[str] = Query(default=None, description="Optional IMDb ID (e.g. tt15239678)"),
    tvdb_id: Optional[str] = Query(default=None, description="Optional TVDb ID"),
    check_cache: bool = Query(default=True, description="Whether to check AllDebrid instant availability"),
    limit: int = Query(default=50, ge=1, le=100, description="Max releases to return"),
) -> Dict[str, Any]:
    """
    Searches Prowlarr indexers for torrent releases across domains (2000 for Movies, 5000 for TV/Classic TV),
    verifies AllDebrid ⚡ Lightning Instant Cache status in batch, parses release details,
    and returns prioritized results with cached releases pinned to top.
    """
    db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain

    try:
        res = await search_sources_tool(
            query=query,
            domain=db_domain,
            season=season,
            episode=episode,
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
            limit=limit,
            check_cache=check_cache,
        )

        if not res.get("ok"):
            err_msg = res.get("error", {}).get("message", "Search failed")
            return {
                "ok": False,
                "domain": db_domain,
                "query": query,
                "error": err_msg,
                "count": 0,
                "cached_count": 0,
                "results": []
            }

        raw_results = res.get("data", {}).get("results", [])
        library_status = res.get("data", {}).get("library_status", {})

        enriched_results = []
        for r in raw_results:
            title = r.get("title", "Unknown Title")
            parsed = parse_release_details(title)
            size_bytes = r.get("size_bytes", 0)
            is_cached = bool(r.get("cached", False))

            enriched_results.append({
                "reference_id": r.get("reference_id"),
                "title": title,
                "size_bytes": size_bytes,
                "formatted_size": format_size_bytes(size_bytes),
                "seeders": r.get("seeders", 0),
                "indexer": r.get("indexer", "Unknown"),
                "published_at": r.get("published_at"),
                "cached": is_cached,
                "cache_badge": "lightning" if is_cached else "uncached",
                "cache_badge_label": "⚡ Lightning (Instant Cache)" if is_cached else "⏳ Uncached (P2P)",
                "resolution": parsed["resolution"],
                "source_type": parsed["source_type"],
                "quality_label": parsed["quality_label"],
                "hdr": parsed["hdr"],
                "codec": parsed["codec"],
                "audio": parsed["audio"],
                "channels": parsed["channels"],
                "release_group": parsed["release_group"],
            })

        # Pinned ranking: Cached releases sorted to top, then seeders descending, then size descending
        enriched_results.sort(
            key=lambda x: (1 if x["cached"] else 0, x["seeders"] or 0, x["size_bytes"] or 0),
            reverse=True
        )

        cached_count = sum(1 for item in enriched_results if item["cached"])

        return {
            "ok": True,
            "domain": db_domain,
            "query": query,
            "season": season,
            "episode": episode,
            "count": len(enriched_results),
            "cached_count": cached_count,
            "library_status": library_status,
            "results": enriched_results
        }

    except Exception as e:
        logger.error("api_search error for query '%s': %s", query, e, exc_info=True)
        return {
            "ok": False,
            "domain": db_domain,
            "query": query,
            "error": f"Search failed: {str(e)}",
            "count": 0,
            "cached_count": 0,
            "results": []
        }









@router.get("/history")
async def api_history(
    domain: Optional[str] = Query(default=None, description="Media domain or 'all'"),
    limit: int = Query(default=50, ge=1, le=100, description="Max jobs to return"),
) -> Dict[str, Any]:
    """
    Retrieves download job history across domains, enriched with live
    media-watcher processing status and Plex placement.
    """
    target_domain = domain if domain and domain != "all" else "all"
    jobs = DownloadJobRepository.get_all_jobs(limit=limit, domain=target_domain)

    # Enrich jobs with live media-watcher state
    watcher = MediaWatcherClient()
    enriched_jobs = []
    for j in jobs:
        job_copy = dict(j)
        filename = job_copy.get("selected_file_name") or ""
        raw_status = job_copy.get("status") or "unknown"

        # Determine synthesized stage
        watcher_status, watcher_err = watcher.get_file_status(filename) if filename else ("unknown", None)
        
        if watcher_status == "tracking":
            display_status = "processing"
            status_label = "Media-Watcher Processing"
            badge_color = "amber"
        elif watcher_status == "processed" or raw_status == "completed":
            display_status = "completed"
            status_label = "Added to Plex"
            badge_color = "green"
        elif raw_status == "dry_run":
            display_status = "dry_run"
            status_label = "Dry-Run Tested"
            badge_color = "purple"
        elif raw_status in ("downloading", "pending"):
            display_status = "downloading"
            status_label = "IDM Downloading"
            badge_color = "blue"
        elif watcher_status == "failed" or raw_status == "failed":
            display_status = "failed"
            status_label = "Failed"
            badge_color = "red"
        else:
            display_status = raw_status
            status_label = raw_status.capitalize()
            badge_color = "gray"

        job_copy["display_status"] = display_status
        job_copy["status_label"] = status_label
        job_copy["badge_color"] = badge_color
        job_copy["watcher_status"] = watcher_status
        if watcher_err:
            job_copy["watcher_error"] = watcher_err

        enriched_jobs.append(job_copy)

    return {
        "ok": True,
        "domain": target_domain,
        "count": len(enriched_jobs),
        "jobs": enriched_jobs
    }


@router.get("/domains")
async def api_domains() -> Dict[str, Any]:
    """Returns overview stats, counts, and staging paths for all media domains."""
    stats = {}

    # Movies
    try:
        with get_db_connection("movies") as conn:
            movie_count = conn.execute("SELECT COUNT(*) FROM library_items").fetchone()[0]
    except Exception:
        movie_count = 0

    # TV
    try:
        with get_db_connection("tv") as conn:
            tv_shows = conn.execute("SELECT COUNT(*) FROM tv_shows").fetchone()[0]
            tv_episodes = conn.execute("SELECT COUNT(*) FROM tv_episodes").fetchone()[0]
    except Exception:
        tv_shows, tv_episodes = 0, 0

    # Classic TV
    try:
        with get_db_connection("tv_classic") as conn:
            classic_shows = conn.execute("SELECT COUNT(*) FROM tv_shows").fetchone()[0]
            classic_episodes = conn.execute("SELECT COUNT(*) FROM tv_episodes").fetchone()[0]
    except Exception:
        classic_shows, classic_episodes = 0, 0

    return {
        "ok": True,
        "domains": {
            "movies": {
                "label": "Movies",
                "icon": "film",
                "item_count": movie_count,
                "output_dir": settings.output_dir,
            },
            "tv": {
                "label": "TV Series",
                "icon": "tv",
                "show_count": tv_shows,
                "episode_count": tv_episodes,
                "output_dir": settings.tv_output_dir,
            },
            "tv_classic": {
                "label": "Classic TV",
                "icon": "radio",
                "show_count": classic_shows,
                "episode_count": classic_episodes,
                "output_dir": settings.tv_classic_output_dir,
            }
        }
    }


DEFAULT_SETTINGS: Dict[str, Any] = {
    # Global & Navigation
    "default_domain": "movies",
    "page_limit": 48,
    "min_seeders": 3,
    "prefer_instant_cache": True,

    # 🎬 Movies Domain Defaults
    "movies_default_language": "en_us",
    "movies_default_time_range": "30d",
    "movies_default_sort": "date.desc",
    "movies_default_tier": "",
    "movies_default_feed": "available_now",
    "movies_quality_preset": "1080p Web-DL",
    "movies_hide_owned": False,

    # 📺 TV Series Domain Defaults (Modern TV)
    "tv_default_language": "en_us",
    "tv_default_time_range": "all",
    "tv_default_sort": "popularity.desc",
    "tv_default_tier": "major",
    "tv_quality_preset": "1080p Web-DL",
    "tv_hide_owned": False,

    # 📻 Classic TV Domain Defaults
    "classic_tv_default_language": "en_us",
    "classic_tv_default_time_range": "all",
    "classic_tv_default_sort": "popularity.desc",
    "classic_tv_default_tier": "major",
    "classic_tv_quality_preset": "1080p Remaster",
    "classic_tv_hide_owned": False,

    # 🔔 Discord & Notifications
    "discord_notify_complete": True,
    "discord_watchlist_alerts": True,
    "discord_weekly_digest": True,
    "digest_day": "Sunday",
    "digest_time": "18:00",
}



@router.get("/settings")
async def api_get_settings() -> Dict[str, Any]:
    """Retrieves current application settings and system integration health status."""
    from moviebot.db.repositories import KeyValueRepository
    stored_str = KeyValueRepository.get("user_settings")
    user_settings = {}
    if stored_str:
        try:
            user_settings = json.loads(stored_str)
        except Exception as e:
            logger.warning("Failed to parse user_settings from kv_store: %s", e)

    merged = {**DEFAULT_SETTINGS, **user_settings}

    system_info = {
        "output_dirs": {
            "movies": settings.output_dir,
            "tv": settings.tv_output_dir,
            "tv_classic": settings.tv_classic_output_dir,
        },
        "integrations": {
            "tmdb": bool(settings.tmdb_api_key or settings.tmdb_bearer_token),
            "alldebrid": bool(getattr(settings, "alldebrid_api_key", None)),
            "prowlarr": bool(getattr(settings, "prowlarr_api_key", None) or getattr(settings, "prowlarr_url", None)),
            "plex": bool(getattr(settings, "plex_url", None)),
        }

    }

    return {
        "ok": True,
        "data": {
            "settings": merged,
            "system_info": system_info,
        }
    }


@router.post("/settings")
async def api_save_settings(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Saves user settings into SQLite kv_store and returns updated settings."""
    from moviebot.db.repositories import KeyValueRepository
    stored_str = KeyValueRepository.get("user_settings")
    existing = {}
    if stored_str:
        try:
            existing = json.loads(stored_str)
        except Exception:
            existing = {}

    # Merge incoming payload with existing settings
    updated = {**DEFAULT_SETTINGS, **existing, **payload}
    try:
        KeyValueRepository.set("user_settings", json.dumps(updated))
    except Exception as e:
        logger.error("Failed to save user_settings into kv_store: %s", e)
        raise HTTPException(status_code=500, detail="Failed to save settings to database")

    return {
        "ok": True,
        "data": updated,
        "message": "Settings saved successfully"
    }

