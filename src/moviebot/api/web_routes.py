import re
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List
from fastapi import APIRouter, Query, HTTPException, Body
from pydantic import BaseModel
from moviebot.config import settings

from moviebot.tools.discover_media_tool import discover_media_tool
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.tools.enqueue_download_tool import enqueue_download_tool
from moviebot.tools.tmdb_fact_provider import TMDbFactProvider
from moviebot.core.release_parser import parse_release_details, format_size_bytes
from moviebot.core.dedupe import normalize_title
from moviebot.db.repositories import DownloadJobRepository, LibraryItemRepository, TVLibraryRepository, SearchResultRepository
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
        
        # Check Plex library presence by matching normalized title
        in_plex = False
        if filename:
            clean_name = re.sub(r'\.(mkv|mp4|avi)$', '', filename, flags=re.IGNORECASE)
            year_match = re.search(r'\b(19\d{2}|20\d{2})\b', clean_name)
            title_part = clean_name[:year_match.start()].strip(' ._-') if year_match else clean_name
            norm_title = normalize_title(title_part)
            if norm_title:
                matches = LibraryItemRepository.search_by_normalized_title(norm_title)
                if matches:
                    in_plex = True

        if watcher_status == "tracking":
            display_status = "processing"
            status_label = "Media-Watcher Processing"
            badge_color = "amber"
        elif in_plex or watcher_status == "processed" or raw_status == "completed":
            display_status = "completed"
            status_label = "Added to Plex"
            badge_color = "green"
            if raw_status != "completed" and job_copy.get("id"):
                try:
                    DownloadJobRepository.update_status(job_copy["id"], "completed")
                except Exception:
                    pass
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

        # Construct 5-stage progress pipeline array
        stages = [
            {"id": "search", "name": "Indexer Search", "icon": "search", "status": "completed"},
            {"id": "debrid", "name": "Debrid Unrestrict", "icon": "zap", "status": "completed"},
            {"id": "idm", "name": "IDM Download", "icon": "download", "status": "pending"},
            {"id": "watcher", "name": "Media-Watcher", "icon": "box", "status": "pending"},
            {"id": "plex", "name": "Added to Plex", "icon": "check-circle", "status": "pending"},
        ]
        if display_status == "downloading":
            stages[2]["status"] = "in_progress"
        elif display_status == "processing":
            stages[2]["status"] = "completed"
            stages[3]["status"] = "in_progress"
        elif display_status == "completed":
            stages[2]["status"] = "completed"
            stages[3]["status"] = "completed"
            stages[4]["status"] = "completed"
        elif display_status == "failed":
            if watcher_status == "failed":
                stages[2]["status"] = "completed"
                stages[3]["status"] = "failed"
            else:
                stages[2]["status"] = "failed"

        job_copy["pipeline_stages"] = stages
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


@router.get("/diagnostics")
async def api_diagnostics() -> Dict[str, Any]:
    """Provides system diagnostics, bridge statuses, and recent error events."""
    from moviebot.tools.get_system_health_tool import get_system_health_tool
    from moviebot.tools.get_recent_events_tool import get_recent_events_tool

    health = await get_system_health_tool()
    events = await get_recent_events_tool(limit=15, domain="movies")
    error_events = [e for e in (events.get("data", {}).get("events", []) if events.get("ok") else []) if e.get("level") == "error"]

    return {
        "ok": True,
        "health": health.get("data", {}) if health.get("ok") else {},
        "recent_errors": error_events
    }


class IngestRequest(BaseModel):
    reference_id: Optional[str] = None
    title: Optional[str] = None
    domain: str = "movies"
    dry_run: bool = False
    season: Optional[int] = None
    episode_numbers: Optional[List[int]] = None
    pack_mode: bool = False
    tmdb_id: Optional[int] = None


@router.post("/ingest")
async def api_ingest(req: IngestRequest) -> Dict[str, Any]:
    """
    1-Click Ingest endpoint for Movies and TV releases.
    Routes to AllDebrid unrestrict and IDM queueing via enqueue_download_tool.
    """
    db_domain = "tv_classic" if req.domain in ("tv_classic", "classic_tv") else req.domain
    ref_id = req.reference_id

    # If no reference_id provided but title is given, run an instant search to resolve best release
    if not ref_id and req.title:
        from moviebot.core.release_parser import score_and_rank_releases
        from moviebot.db.repositories import KeyValueRepository
        stored_str = KeyValueRepository.get("user_settings")
        user_settings = {}
        if stored_str:
            try:
                user_settings = json.loads(stored_str)
            except Exception:
                pass

        pref_key = f"{db_domain}_quality_preset" if db_domain != "tv_classic" else "classic_tv_quality_preset"
        preferred_quality = user_settings.get(pref_key, DEFAULT_SETTINGS.get(pref_key, "1080p Web-DL"))
        prefer_cached = user_settings.get("prefer_instant_cache", True)

        search_res = await search_sources_tool(
            query=req.title,
            domain=db_domain,
            season=req.season,
            limit=25,
            check_cache=True
        )
        if search_res.get("ok"):
            results = search_res.get("data", {}).get("results", [])
            ranked = score_and_rank_releases(
                results,
                preferred_quality=preferred_quality,
                prefer_cached=prefer_cached
            )
            if ranked:
                ref_id = ranked[0].get("reference_id")

    if not ref_id:
        return {
            "ok": False,
            "error_code": "UNRELEASED_OR_NO_SOURCES",
            "error": f"No digital release found for '{req.title}'. This title may be an upcoming theatrical film or not yet released on digital platforms.",
            "title": req.title,
            "domain": db_domain
        }

    res = await enqueue_download_tool(
        reference_id=ref_id,
        domain=db_domain,
        dry_run=req.dry_run
    )

    if not res.get("ok"):
        err_obj = res.get("error", {})
        err_msg = err_obj.get("message", "Download enqueueing failed")
        return {
            "ok": False,
            "error": err_msg,
            "title": req.title,
            "domain": db_domain,
            "details": res
        }

    job_data = res.get("data", {})
    return {
        "ok": True,
        "job_id": job_data.get("job_id"),
        "title": req.title or job_data.get("filename") or "Media Download",
        "domain": db_domain,
        "status": "queued",
        "message": f"⚡ Successfully queued in IDM: {req.title or job_data.get('filename') or 'Download'}",
        "data": job_data
    }


@router.get("/tv/series-manifest")
async def api_tv_series_manifest(
    tmdb_id: int = Query(..., description="TMDb TV series ID"),
    domain: str = Query(default="tv", description="Domain: tv or tv_classic"),
) -> Dict[str, Any]:
    """
    Retrieves season and episode breakdown for a TV series from TMDb
    cross-referenced with owned episodes in the local Plex SQLite database.
    """
    db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain
    cache_key_domain = f"tv_manifest_{db_domain}"
    cached_manifest = get_cached_detail(cache_key_domain, tmdb_id)
    if cached_manifest:
        return cached_manifest

    provider = TMDbFactProvider()

    details = provider.get_tv_full_details(tmdb_id)
    if not details:
        details = provider._get_json(f"tv/{tmdb_id}")

    if not details:
        raise HTTPException(status_code=404, detail="TV series details could not be retrieved from TMDb")

    title = details.get("title") or details.get("name") or details.get("original_name") or "Unknown TV Show"
    poster_url = details.get("poster_url")
    if not poster_url and details.get("poster_path"):
        poster_url = f"https://image.tmdb.org/t/p/w500{details.get('poster_path')}"
    banner_url = details.get("backdrop_url")
    if not banner_url and details.get("backdrop_path"):
        banner_url = f"https://image.tmdb.org/t/p/original{details.get('backdrop_path')}"

    # Get local Plex owned episodes
    show = TVLibraryRepository.get_show_by_tmdb_id(tmdb_id, domain=db_domain)
    if not show:
        from moviebot.core.dedupe import normalize_title
        norm = normalize_title(title)
        first_air = details.get("first_air_date") or ""
        year = int(first_air[:4]) if len(first_air) >= 4 and first_air[:4].isdigit() else None
        show = TVLibraryRepository.get_show_by_normalized_title_and_year(norm, year=year, domain=db_domain)

    show_id = show["id"] if show else f"tmdb-tv-{tmdb_id}"
    owned_set = TVLibraryRepository.get_owned_episodes(show_id, domain=db_domain) if show else set()

    raw_seasons = details.get("seasons", [])
    seasons_manifest = []
    total_owned_episodes = 0
    total_manifest_episodes = 0

    valid_seasons = [s for s in raw_seasons if s.get("season_number", 0) > 0]
    # Fetch Season 1 full facts immediately for rich initial display
    s1_facts = None
    if valid_seasons:
        try:
            s1_facts = provider.get_tv_season_facts(tmdb_id, valid_seasons[0].get("season_number", 1))
        except Exception:
            s1_facts = None

    for idx, s in enumerate(valid_seasons):
        s_num = s.get("season_number", 1)
        s_name = s.get("name") or f"Season {s_num}"
        ep_count = s.get("episode_count", 0)

        episodes_list = []
        owned_in_season = 0

        # Use rich facts for the primary season if available
        if idx == 0 and s1_facts and "episodes" in s1_facts:
            for ep in s1_facts["episodes"]:
                ep_num = ep.get("episode_number")
                ep_name = ep.get("name") or f"Episode {ep_num}"
                air_date = ep.get("air_date")
                runtime = ep.get("runtime")
                is_owned = (s_num, ep_num) in owned_set
                if is_owned:
                    owned_in_season += 1
                    total_owned_episodes += 1
                total_manifest_episodes += 1
                episodes_list.append({
                    "episode_number": ep_num,
                    "title": ep_name,
                    "air_date": air_date,
                    "runtime_min": runtime,
                    "overview": ep.get("overview", ""),
                    "owned": is_owned,
                })
        else:
            for ep_num in range(1, ep_count + 1):
                is_owned = (s_num, ep_num) in owned_set
                if is_owned:
                    owned_in_season += 1
                    total_owned_episodes += 1
                total_manifest_episodes += 1
                episodes_list.append({
                    "episode_number": ep_num,
                    "title": f"Episode {ep_num}",
                    "air_date": None,
                    "runtime_min": None,
                    "overview": "",
                    "owned": is_owned,
                })

        seasons_manifest.append({
            "season_number": s_num,
            "name": s_name,
            "episode_count": len(episodes_list),
            "owned_count": owned_in_season,
            "missing_count": len(episodes_list) - owned_in_season,
            "episodes": episodes_list
        })

    res_manifest = {
        "ok": True,
        "tmdb_id": tmdb_id,
        "title": title,
        "year": details.get("first_air_date", "")[:4] if details.get("first_air_date") else None,
        "domain": db_domain,
        "poster_url": poster_url,
        "banner_url": banner_url,
        "overview": details.get("overview", ""),
        "total_seasons": len(seasons_manifest),
        "total_episodes": total_manifest_episodes,
        "total_owned_episodes": total_owned_episodes,
        "total_missing_episodes": total_manifest_episodes - total_owned_episodes,
        "seasons": seasons_manifest
    }
    set_cached_detail(cache_key_domain, tmdb_id, res_manifest)
    return res_manifest


class TVIngestEpisodesRequest(BaseModel):
    tmdb_id: int
    title: str
    domain: str = "tv"
    season: int
    episode_numbers: Optional[List[int]] = None
    pack_mode: bool = False
    dry_run: bool = False


@router.post("/tv/ingest-episodes")
async def api_tv_ingest_episodes(req: TVIngestEpisodesRequest) -> Dict[str, Any]:
    """
    Ingests TV episodes or season packs by querying Prowlarr and queueing into IDM.
    """
    db_domain = "tv_classic" if req.domain in ("tv_classic", "classic_tv") else req.domain
    search_query = req.title

    # 1. Search Prowlarr for matching season or pack
    search_res = await search_sources_tool(
        query=search_query,
        domain=db_domain,
        season=req.season,
        limit=10,
        check_cache=True
    )

    if not search_res.get("ok"):
        return {
            "ok": False,
            "error": search_res.get("error", {}).get("message", "Search failed for TV episodes"),
            "title": req.title,
            "domain": db_domain
        }

    results = search_res.get("data", {}).get("results", [])
    if not results:
        return {
            "ok": False,
            "error": f"No torrent releases found for {req.title} Season {req.season}",
            "title": req.title,
            "domain": db_domain
        }

    # Prioritize ⚡ Instant Cached releases, then highest seeders
    cached_candidates = [r for r in results if r.get("cached")]
    target_release = cached_candidates[0] if cached_candidates else results[0]
    ref_id = target_release.get("reference_id")

    res = await enqueue_download_tool(
        reference_id=ref_id,
        domain=db_domain,
        dry_run=req.dry_run
    )

    if not res.get("ok"):
        return {
            "ok": False,
            "error": res.get("error", {}).get("message", "Failed to enqueue TV download"),
            "title": req.title,
            "domain": db_domain
        }

    job_data = res.get("data", {})
    return {
        "ok": True,
        "job_id": job_data.get("job_id"),
        "title": req.title,
        "season": req.season,
        "domain": db_domain,
        "status": "queued",
        "message": f"⚡ Queued {req.title} S{req.season:02d} for IDM ingestion",
        "data": job_data
    }


