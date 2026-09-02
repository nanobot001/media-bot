import re
import json
import asyncio
import datetime
import math
import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List
from urllib.parse import quote, urlsplit
from fastapi import APIRouter, Query, HTTPException, Body, Request
from fastapi.responses import PlainTextResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from moviebot.config import settings

from moviebot.tools.discover_media_tool import discover_media_tool
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.tools.enqueue_download_tool import enqueue_download_tool
from moviebot.tools.tmdb_fact_provider import TMDbFactProvider
from moviebot.core.release_parser import (
    compute_title_similarity,
    extract_year_from_title,
    parse_release_details,
    format_size_bytes,
    classify_browser_stream_candidate,
    is_browser_stream_compatible,
    is_exact_media_identity,
    score_and_rank_releases,
)
from moviebot.core.movie_quality_gate import (
    MOVIE_QUALITY_GATE_REJECTED,
    assess_movie_release,
    evaluate_movie_eligibility,
    filter_movie_releases,
    quality_gate_error,
)
from moviebot.core.availability_service import AvailabilityService
from moviebot.core.browser_stream_verifier import verify_stream_payload
from moviebot.core.mediaflow_adapter import (
    MediaFlowAdapterError,
    MediaFlowProductionAdapter,
    mediaflow_playback_registry,
    production_configuration,
    require_production_configuration,
)
from moviebot.core.mediaflow_pilot import sanitize_runtime_metrics
from moviebot.core.mediaflow_diagnostics import (
    MEDIAFLOW_DECISION_VERSION,
    MEDIAFLOW_DIAGNOSTICS_SCHEMA_VERSION,
    build_diagnostics,
    diagnostics_mode,
    project_diagnostics,
    recent_diagnostics,
)
from moviebot.core.mediaflow_segmented import (
    MediaFlowSegmentedError,
    fetch_segment_bytes,
)
from moviebot.core.dedupe import normalize_title
from moviebot.db.repositories import (
    DownloadJobRepository,
    EventRepository,
    LibraryItemRepository,
    TVLibraryRepository,
    SearchResultRepository,
)
from moviebot.db.cache_prewarm_repo import CachePrewarmRepository
from moviebot.db.cloud_transfer_repo import CloudTransferIntentRepository
from moviebot.db.release_variant_repo import ReleaseVariantRepository
from moviebot.adapters.media_watcher_client import MediaWatcherClient
from moviebot.adapters.mediaflow_client import MediaFlowClient, MediaFlowError
from moviebot.db.connection import get_db_connection


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["web_dashboard"])


from moviebot.core.discovery_cache import get_cached_detail, set_cached_detail, start_background_prewarming


async def _evaluate_movie_request(
    *,
    title: Optional[str],
    year: Optional[int] = None,
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        evaluate_movie_eligibility,
        title=title,
        year=year,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
    )


def _movie_quality_gate_response(
    decision: Dict[str, Any],
    *,
    title: Optional[str] = None,
    domain: str = "movies",
    year: Optional[int] = None,
) -> Dict[str, Any]:
    error = quality_gate_error(decision)
    return {
        "ok": False,
        "error_code": error["code"],
        "error": error["message"],
        "quality_gate": decision,
        "title": title,
        "domain": domain,
        "year": year,
    }


def _stream_candidate_summary(record: Optional[Dict[str, Any]], role: str) -> Optional[Dict[str, Any]]:
    """Expose selected release facts without exposing provider URLs or magnets."""
    if not record:
        return None
    release_title = record.get("browser_stream_release_title") if role == "browser" else record.get("release_title")
    release_title = release_title or record.get("release_title") or record.get("title") or ""
    parsed = parse_release_details(release_title)
    evidence = record.get("data", {}).get("browser_verification", {})
    if not isinstance(evidence, dict):
        evidence = {}
    verification_status = evidence.get("status")
    if not verification_status and evidence.get("verified") is True:
        verification_status = "verified_browser_ready"
    verified_browser_copy = bool(record.get("browser_stream_ready"))
    if role == "browser" and not verified_browser_copy:
        verified_browser_copy = bool(
            record.get("cached") and CachePrewarmRepository._has_fresh_browser_evidence(record)
        )
    container = Path(release_title.split("?", 1)[0]).suffix.lower().lstrip(".") or None
    return {
        "role": role,
        "release_title": release_title,
        "resolution": parsed.get("resolution") or record.get("resolution"),
        "source_type": parsed.get("source_type"),
        "container": container,
        "video_codec": parsed.get("codec"),
        "audio_codec": parsed.get("audio"),
        "channels": parsed.get("channels"),
        "size_bytes": record.get("size_bytes") or 0,
        "formatted_size": record.get("formatted_size") or format_size_bytes(record.get("size_bytes") or 0),
        "cached": bool(record.get("cloud_cached", record.get("cached"))),
        "verified": role == "browser" and verified_browser_copy,
        "verification_status": verification_status if role == "browser" else None,
        "verification_source": evidence.get("evidence_source") if role == "browser" else None,
        "verification_code": evidence.get("verification_code") if role == "browser" else None,
        "audio_track_present": evidence.get("audio_track_present") if role == "browser" else None,
        "verified_at": record.get("browser_stream_verified_at") if role == "browser" else None,
        "selection_reason": (
            "authoritative_file_verification"
            if role == "browser"
            else "provider_cache_available_for_download"
        ),
    }


def _movie_stream_state(item: Dict[str, Any]) -> Dict[str, Any]:
    """Expose authoritative, recent pre-warm state to discovery cards."""
    title = item.get("title") or ""
    year = item.get("year")
    quality_gate = item.get("quality_gate")
    if isinstance(quality_gate, dict) and not quality_gate.get("eligible"):
        return {
            "cloud_cached": False,
            "instant_download_ready": False,
            "instant_cached": False,
            "browser_stream_ready": False,
            "external_stream_ready": False,
            "instant_stream_status": "quality_gate_rejected",
            "stream_reference_id": None,
            "stream_release_title": None,
            "browser_stream_reference_id": None,
            "browser_stream_release_title": None,
            "download_reference_id": None,
            "download_release_title": None,
            "browser_stream_candidate": None,
            "download_candidate": None,
            "selected_stream_candidate": None,
            "stream_selection": None,
            "quality_gate": quality_gate,
            "stream_prepare_status": None,
        }
    prepare_intent = CloudTransferIntentRepository.get_latest_for_media(
        "movies", title, year=year, season=0
    )
    prepare_status = prepare_intent.get("status") if prepare_intent else None
    record = CachePrewarmRepository.get(
        "movies",
        title,
        season=0,
        year=year,
        max_age_hours=12,
    )
    verified_browser_record = CachePrewarmRepository.get_verified_browser_candidate(
        "movies",
        title,
        season=0,
        year=year,
        max_age_hours=12,
    )
    if not record:
        browser_summary = _stream_candidate_summary(verified_browser_record, "browser")
        download_summary = _stream_candidate_summary(verified_browser_record, "download")
        browser_reference_id = (
            verified_browser_record.get("browser_stream_reference_id")
            if verified_browser_record
            else None
        )
        browser_release_title = browser_summary.get("release_title") if browser_summary else None
        download_reference_id = (
            verified_browser_record.get("reference_id") if verified_browser_record else None
        )
        download_release_title = download_summary.get("release_title") if download_summary else None
        return {
            "cloud_cached": bool(verified_browser_record),
            "instant_download_ready": bool(verified_browser_record),
            "instant_cached": bool(browser_summary),
            "browser_stream_ready": bool(browser_summary),
            "external_stream_ready": False,
            "instant_stream_status": "browser_ready" if browser_summary else "searching",
            "stream_reference_id": browser_reference_id,
            "stream_release_title": browser_release_title,
            "browser_stream_reference_id": browser_reference_id,
            "browser_stream_release_title": browser_release_title,
            "download_reference_id": download_reference_id,
            "download_release_title": download_release_title,
            "browser_stream_candidate": browser_summary,
            "download_candidate": download_summary,
            "selected_stream_candidate": browser_summary,
            "stream_selection": "browser_verified" if browser_summary else None,
            "stream_prepare_status": prepare_status,
        }

    download_record = record if record.get("cloud_cached", record.get("cached")) else verified_browser_record
    record_browser_ready = bool(record.get("browser_stream_ready")) or bool(
        record.get("cached") and CachePrewarmRepository._has_fresh_browser_evidence(record)
    )
    browser_record = (
        verified_browser_record
        if verified_browser_record and verified_browser_record.get("browser_stream_ready")
        else (record if record_browser_ready else None)
    )
    browser_summary = _stream_candidate_summary(browser_record, "browser")
    download_summary = _stream_candidate_summary(download_record, "download")
    cloud_cached = bool(download_record and download_record.get("cloud_cached", download_record.get("cached")))
    browser_ready = bool(browser_summary)
    external_ready = cloud_cached and not browser_ready
    browser_reference_id = (
        browser_record.get("browser_stream_reference_id") if browser_record else None
    )
    browser_release_title = browser_summary.get("release_title") if browser_summary else None
    download_reference_id = download_record.get("reference_id") if download_record else None
    download_release_title = download_summary.get("release_title") if download_summary else None
    selected_stream_candidate = browser_summary if browser_ready else (download_summary if external_ready else None)
    return {
        "cloud_cached": cloud_cached,
        "instant_download_ready": cloud_cached,
        "instant_cached": browser_ready,
        "browser_stream_ready": browser_ready,
        "external_stream_ready": external_ready,
        "instant_stream_status": "browser_ready" if browser_ready else ("external_ready" if external_ready else "searching"),
        "stream_reference_id": browser_reference_id if browser_ready else (download_reference_id if external_ready else None),
        "stream_release_title": browser_release_title if browser_ready else (download_release_title if external_ready else None),
        "browser_stream_reference_id": browser_reference_id if browser_ready else None,
        "browser_stream_release_title": browser_release_title if browser_ready else None,
        "download_reference_id": download_reference_id if cloud_cached else None,
        "download_release_title": download_release_title if cloud_cached else None,
        "browser_stream_candidate": browser_summary,
        "download_candidate": download_summary,
        "selected_stream_candidate": selected_stream_candidate,
        "stream_selection": "browser_verified" if browser_ready else ("external_player" if external_ready else None),
        "stream_prepare_status": prepare_status,
    }


def _tv_stream_state(item: Dict[str, Any], db_domain: str) -> Dict[str, Any]:
    """Expose the best pre-warmed TV season candidate for a discovery card."""
    title = item.get("title") or ""
    requested_season = int(item.get("season") or 0)
    prepare_intent = CloudTransferIntentRepository.get_latest_for_media(
        db_domain, title, season=requested_season, purpose="browser_stream"
    )
    prepare_status = prepare_intent.get("status") if prepare_intent else None
    seasons = [requested_season] if requested_season > 0 else [1, 0]
    record = None
    stream_season = requested_season
    for season in seasons:
        record = CachePrewarmRepository.get(
            db_domain,
            title,
            season=season,
            max_age_hours=12,
        )
        if record:
            stream_season = season
            break
    if record is None:
        return {
            "cloud_cached": False,
            "instant_download_ready": False,
            "instant_cached": False,
            "browser_stream_ready": False,
            "external_stream_ready": False,
            "instant_stream_status": "searching",
            "stream_reference_id": None,
            "stream_release_title": None,
            "browser_stream_reference_id": None,
            "browser_stream_release_title": None,
            "download_reference_id": None,
            "download_release_title": None,
            "stream_season": None,
            "stream_prepare_status": prepare_status,
        }

    cloud_cached = bool(record.get("cloud_cached", record.get("cached")))
    browser_ready = record.get("browser_stream_ready")
    if browser_ready is None:
        browser_ready = CachePrewarmRepository._has_fresh_browser_evidence(record)
    browser_ready = bool(browser_ready)
    external_ready = cloud_cached and not browser_ready
    browser_ref = record.get("browser_stream_reference_id") or record.get("stream_reference_id")
    browser_title = record.get("browser_stream_release_title") or record.get("stream_release_title")
    if browser_ready and not browser_ref:
        browser_ref = record.get("reference_id")
    if browser_ready and not browser_title:
        browser_title = record.get("release_title")
    download_ref = record.get("download_reference_id") or record.get("reference_id")
    download_title = record.get("download_release_title") or record.get("release_title")
    return {
        "cloud_cached": cloud_cached,
        "instant_download_ready": cloud_cached,
        "instant_cached": browser_ready,
        "browser_stream_ready": browser_ready,
        "external_stream_ready": external_ready,
        "instant_stream_status": "browser_ready" if browser_ready else ("external_ready" if external_ready else "searching"),
        "stream_reference_id": browser_ref if browser_ready else (download_ref if external_ready else None),
        "stream_release_title": browser_title if browser_ready else (download_title if external_ready else None),
        "browser_stream_reference_id": browser_ref if browser_ready else None,
        "browser_stream_release_title": browser_title if browser_ready else None,
        "download_reference_id": download_ref if cloud_cached else None,
        "download_release_title": download_title if cloud_cached else None,
        "stream_season": stream_season,
        "stream_prepare_status": prepare_status,
    }


CATALOG_ITEM_FIELDS = (
    "availability_state",
    "availability_tier",
    "cached",
    "cloud_cached",
    "instant_download_ready",
    "instant_cached",
    "browser_stream_ready",
    "external_stream_ready",
    "instant_stream_status",
)


def _item_projection(item: Dict[str, Any], db_domain: str) -> Dict[str, Any]:
    existing = item.get("availability")
    if isinstance(existing, dict) and existing.get("projection_version") == 1:
        return existing
    season = int(item.get("season") or 0)
    episode = int(item.get("episode") or 0)
    scope_type = item.get("scope_type")
    if db_domain != "movies" and not scope_type:
        scope_type = "episode" if episode else ("season_pack" if season else "series")
    return AvailabilityService.project(
        domain=db_domain,
        title=item.get("title") or "",
        year=item.get("year"),
        tmdb_id=item.get("tmdb_id") or item.get("id"),
        season=season,
        episode=episode,
        scope_type=scope_type,
    )


def _merge_catalog_stream_state(
    item: Dict[str, Any],
    legacy_stream_state: Dict[str, Any],
    db_domain: str,
) -> Dict[str, Any]:
    """Keep opaque action references while catalog state owns availability."""
    projection = _item_projection(item, db_domain)
    merged = {**item, **legacy_stream_state}
    merged["availability"] = projection
    merged["availability_scope"] = projection["media"]
    merged["availability_coverage"] = projection["coverage"]
    merged["variant_count"] = projection["variant_count"]
    merged["cached_variant_count"] = projection["cached_variant_count"]
    merged["direct_play_variant_count"] = projection["direct_play_variant_count"]
    merged["cached_variants"] = projection["cached_variants"]
    for field in CATALOG_ITEM_FIELDS:
        merged[field] = projection[field]
    if projection["availability_state"] == "unknown":
        merged["stream_reference_id"] = None
        merged["browser_stream_reference_id"] = None
        merged["download_reference_id"] = None
    return merged


def _matching_public_variant(
    projection: Dict[str, Any],
    item: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    release_title = str(
        item.get("release_title") or item.get("title") or ""
    ).strip().lower()
    if not release_title:
        return None
    for variant in projection.get("variants", []):
        if str(variant.get("release_title") or "").strip().lower() == release_title:
            return variant
    return None


def _project_prewarm_item(item: Dict[str, Any]) -> Dict[str, Any]:
    db_domain = (
        "tv_classic"
        if item.get("domain") in {"classic_tv", "tv_classic"}
        else item.get("domain", "movies")
    )
    season = int(item.get("season") or 0)
    episode = int(item.get("episode") or 0)
    scope_type = item.get("scope_type")
    if db_domain != "movies" and not scope_type:
        scope_type = "episode" if episode else ("season_pack" if season else "series")
    projection = AvailabilityService.project(
        domain=db_domain,
        title=item.get("title") or "",
        year=item.get("year"),
        season=season,
        episode=episode,
        scope_type=scope_type,
    )
    variant = _matching_public_variant(projection, item)
    projected = dict(item)
    projected["domain"] = db_domain
    projected["availability"] = projection
    projected["availability_state"] = projection["availability_state"]
    projected["availability_tier"] = projection["availability_tier"]
    projected["availability_scope"] = projection["media"]
    projected["availability_coverage"] = projection["coverage"]
    projected["variant_count"] = projection["variant_count"]
    projected["cached_variant_count"] = projection["cached_variant_count"]
    projected["direct_play_variant_count"] = projection["direct_play_variant_count"]
    projected["cached_variants"] = projection["cached_variants"]
    projected["variant_availability"] = variant
    projected["variant_availability_state"] = (
        variant.get("availability_state") if variant else "unknown"
    )
    source = variant or AvailabilityService.unknown_projection(
        domain=db_domain,
        title=item.get("title") or "",
        year=item.get("year"),
        season=season,
        episode=episode,
        scope_type=scope_type,
    )
    for field in (
        "cached",
        "cloud_cached",
        "instant_download_ready",
        "instant_cached",
        "browser_stream_ready",
        "external_stream_ready",
        "instant_stream_status",
    ):
        projected[field] = source[field]
    return projected


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
    db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain
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

    if res.get("ok") and isinstance(res.get("data"), dict):
        # Do not mutate the discovery cache object in-place; cache readiness is
        # short-lived and must be re-read from the durable pre-warm table.
        response = dict(res)
        response_data = dict(res["data"])
        response_data["results"] = [
            _merge_catalog_stream_state(
                item,
                _movie_stream_state(item) if db_domain == "movies" else _tv_stream_state(item, db_domain),
                db_domain,
            )
            for item in response_data.get("results", [])
        ]
        response["data"] = response_data
        return response
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
    verifies AllDebrid cloud-cache status in batch, parses release details,
    classifies browser-stream readiness separately, and returns browser-ready
    candidates ahead of download-only cached releases.
    """
    db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain
    movie_eligibility = None
    if db_domain == "movies":
        movie_eligibility = await _evaluate_movie_request(
            title=query,
            imdb_id=imdb_id,
        )
        if not movie_eligibility.get("eligible"):
            return _movie_quality_gate_response(
                movie_eligibility,
                title=query,
                domain=db_domain,
            )

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
            movie_eligibility=movie_eligibility,
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
        response_data = res.get("data", {})
        scope_projection = response_data.get("availability") or {}
        eligibility = response_data.get("eligibility") or movie_eligibility
        if db_domain == "movies" and isinstance(eligibility, dict) and not eligibility.get("eligible"):
            return {
                "ok": True,
                "domain": db_domain,
                "query": query,
                "season": season,
                "episode": episode,
                "count": 0,
                "cached_count": 0,
                "instant_cached_count": 0,
                "cloud_cached_count": 0,
                "external_cached_count": 0,
                "library_status": library_status,
                "results": [],
                "rejected_results": response_data.get("rejected_results", []),
                "rejected_count": response_data.get("rejected_count", 0),
                "quality_gate": eligibility,
            }
        library_owned = bool(library_status.get("in_library"))

        enriched_results = []
        for r in raw_results:
            title = r.get("title", "Unknown Title")
            parsed = parse_release_details(title)
            size_bytes = r.get("size_bytes", 0)
            is_cached = bool(r.get("cached", False))
            cache_status = str(r.get("cache_status") or ("cached" if is_cached else "unknown"))
            cache_error_code = r.get("cache_error_code")
            verified_record = CachePrewarmRepository.get_by_browser_reference_id(
                db_domain, r.get("reference_id") or ""
            )
            browser_ready = bool(r.get("browser_stream_ready"))
            external_ready = bool(r.get("external_stream_ready"))
            variant_state = str(r.get("variant_availability_state") or "unknown")

            enriched_results.append({
                "reference_id": r.get("reference_id"),
                "title": title,
                "size_bytes": size_bytes,
                "formatted_size": format_size_bytes(size_bytes),
                "seeders": r.get("seeders", 0),
                "indexer": r.get("indexer", "Unknown"),
                "published_at": r.get("published_at"),
                "cached": is_cached,
                "cache_status": cache_status,
                "cache_checked": bool(r.get("cache_checked", False)),
                "cache_error": (
                    {
                        "code": str(cache_error_code)[:100],
                        "retryable": True,
                    }
                    if cache_error_code
                    else None
                ),
                "cloud_cached": is_cached,
                "instant_download_ready": is_cached,
                "instant_cached": browser_ready,
                "browser_stream_ready": browser_ready,
                "external_stream_ready": external_ready,
                "instant_stream_status": r.get("instant_stream_status") or "unknown",
                "stream_reference_id": r.get("reference_id") if is_cached else None,
                "browser_stream_reference_id": (
                    verified_record.get("browser_stream_reference_id")
                    if browser_ready and verified_record
                    else None
                ),
                "download_reference_id": r.get("reference_id") if is_cached else None,
                "cache_badge": (
                    "lightning"
                    if browser_ready
                    else (
                        "external"
                        if external_ready
                        else ("uncached" if variant_state == "not_cached" else "unknown")
                    )
                ),
                "cache_badge_label": (
                    "⚡ Browser Stream + Cached Download"
                    if browser_ready
                    else (
                        "☁️ Cached for Download (External Player)"
                        if external_ready
                        else (
                            "⏳ Uncached (P2P)"
                            if variant_state == "not_cached"
                            else "? Availability Unknown"
                        )
                    )
                ),
                "resolution": parsed["resolution"],
                "source_type": parsed["source_type"],
                "quality_label": parsed["quality_label"],
                "hdr": parsed["hdr"],
                "codec": parsed["codec"],
                "audio": parsed["audio"],
                "channels": parsed["channels"],
                "release_group": parsed["release_group"],
                "owned": library_owned,
                "in_library": library_owned,
                "quality_gate": r.get("quality_gate") or eligibility,
                "availability": r.get("availability") or scope_projection,
                "availability_state": (
                    r.get("availability_state")
                    or scope_projection.get("availability_state", "unknown")
                ),
                "availability_tier": (
                    r.get("availability_tier")
                    or scope_projection.get("availability_tier", "unknown")
                ),
                "availability_scope": r.get("availability_scope") or scope_projection.get("media"),
                "availability_coverage": (
                    r.get("availability_coverage") or scope_projection.get("coverage")
                ),
                "variant_count": int(
                    r.get("variant_count") or scope_projection.get("variant_count") or 0
                ),
                "cached_variant_count": int(
                    r.get("cached_variant_count")
                    or scope_projection.get("cached_variant_count")
                    or 0
                ),
                "direct_play_variant_count": int(
                    r.get("direct_play_variant_count")
                    or scope_projection.get("direct_play_variant_count")
                    or 0
                ),
                "cached_variants": (
                    r.get("cached_variants") or scope_projection.get("cached_variants", [])
                ),
                "variant_availability": r.get("variant_availability"),
                "variant_availability_state": variant_state,
            })

        # Pinned ranking: browser-stream candidates first, then cached download
        # candidates, then uncached releases.
        enriched_results.sort(
            key=lambda x: (
                2 if x["instant_cached"] else (1 if x["cloud_cached"] else 0),
                x["seeders"] or 0,
                x["size_bytes"] or 0,
            ),
            reverse=True
        )

        cached_count = sum(1 for item in enriched_results if item["instant_cached"])
        cloud_cached_count = sum(1 for item in enriched_results if item["cloud_cached"])
        external_cached_count = sum(1 for item in enriched_results if item["external_stream_ready"])
        cache_unknown_count = sum(
            1 for item in enriched_results
            if item["cache_status"] in {"unknown", "unresolvable"}
        )
        cache_provider_error_count = sum(
            1 for item in enriched_results if item["cache_status"] == "provider_error"
        )

        return {
            "ok": True,
            "domain": db_domain,
            "query": query,
            "season": season,
            "episode": episode,
            "count": len(enriched_results),
            "cached_count": cached_count,
            "instant_cached_count": cached_count,
            "cloud_cached_count": cloud_cached_count,
            "external_cached_count": external_cached_count,
            "cache_unknown_count": cache_unknown_count,
            "cache_provider_error_count": cache_provider_error_count,
            "library_status": library_status,
            "catalog": response_data.get("catalog"),
            "availability": scope_projection,
            "rejected_results": response_data.get("rejected_results", []),
            "rejected_count": response_data.get("rejected_count", 0),
            "quality_gate": eligibility,
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

    # ⚡ Background Cache Pre-Warmer
    "background_prewarm_enabled": True,
    "prewarm_interval_hours": 6,
    "prewarm_depth_per_domain": 25,
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

    from moviebot.db.cache_prewarm_repo import CachePrewarmRepository

    health = await get_system_health_tool()
    events = await get_recent_events_tool(limit=15, domain="movies")
    error_events = [e for e in (events.get("data", {}).get("events", []) if events.get("ok") else []) if e.get("level") == "error"]
    prewarm_stats = CachePrewarmRepository.get_stats()

    return {
        "ok": True,
        "health": health.get("data", {}) if health.get("ok") else {},
        "prewarm_cache": prewarm_stats,
        "recent_errors": error_events
    }


@router.post("/prewarm/trigger")
async def api_trigger_prewarm() -> Dict[str, Any]:
    """
    Manually triggers an immediate background AllDebrid cache pre-warming pass.
    """
    from moviebot.core.background_prewarmer import (
        prepare_cache_prewarm_cycle,
        run_cache_prewarm_cycle,
    )

    reservation = prepare_cache_prewarm_cycle(trigger_source="manual")
    if not reservation.get("accepted"):
        return {
            "ok": False,
            "status": "skipped",
            "error": {
                "code": reservation.get("error_code", "PREWARM_BUSY"),
                "message": "Another pre-warm cycle is already running.",
                "retryable": True,
            },
            "cycle_id": reservation.get("cycle_id"),
            "active_cycle_id": reservation.get("active_cycle_id"),
        }

    asyncio.create_task(
        run_cache_prewarm_cycle(
            trigger_source="manual",
            prepared=reservation,
        )
    )
    return {
        "ok": True,
        "status": "running",
        "cycle_id": reservation["cycle_id"],
        "message": "Background AllDebrid & indexer cache pre-warming cycle triggered.",
    }


@router.get("/prewarm/status")
async def api_get_prewarm_status(
    limit: int = Query(default=10, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> Dict[str, Any]:
    """Return sanitized authoritative runtime-ledger state."""
    from moviebot.db.prewarm_run_repo import PrewarmRunRepository

    return {"ok": True, **PrewarmRunRepository.status(limit=limit, offset=offset)}


@router.get("/prewarm/items")
async def api_get_prewarm_items(
    domain: str = Query(default="all"),
    status: str = Query(default="all"),
    only_cached: bool = Query(default=False),
    limit: int = Query(default=1000)
) -> Dict[str, Any]:
    """
    Retrieves records from the SQLite prewarmed_cache repository and real-time scoreboard metrics.
    """
    from moviebot.db.cache_prewarm_repo import CachePrewarmRepository
    from moviebot.core.background_prewarmer import get_prewarm_status

    raw_items = CachePrewarmRepository.get_items(domain=domain, status="all", limit=max(limit, 1000))
    items = [_project_prewarm_item(item) for item in raw_items]
    effective_status = "cached" if only_cached else status
    if effective_status == "cached":
        items = [item for item in items if item["variant_availability_state"] in {"ad_cached", "direct_play_ready"}]
    elif effective_status == "uncached":
        items = [item for item in items if item["variant_availability_state"] == "not_cached"]
    elif effective_status == "unknown":
        items = [item for item in items if item["variant_availability_state"] == "unknown"]
    elif effective_status == "dropped":
        items = [item for item in items if item.get("dropped")]
    items = items[:limit]
    scoreboard = CachePrewarmRepository.get_scoreboard_stats(domain=domain)
    availability_breakdown = {
        state: sum(1 for item in items if item["availability_state"] == state)
        for state in ("unknown", "not_cached", "ad_cached", "direct_play_ready")
    }
    scoreboard = {**scoreboard, "availability_breakdown": availability_breakdown}
    prewarm_status = get_prewarm_status()

    return {
        "ok": True,
        "items": items,
        "scoreboard": scoreboard,
        "stats": scoreboard,
        "is_prewarming": prewarm_status.get("is_prewarming", False),
        "last_stats": prewarm_status.get("last_stats"),
        "active_cycle": prewarm_status.get("active_cycle"),
        "last_cycle": prewarm_status.get("last_cycle"),
        "next_due_at": prewarm_status.get("next_due_at"),
        "recent_cycles": prewarm_status.get("recent_cycles", []),
    }


@router.get("/prewarm/catalog")
async def api_inspect_release_catalog(
    title: str = Query(..., min_length=1, description="Exact movie or TV title"),
    domain: str = Query(default="movies", description="movies, tv, or tv_classic"),
    year: Optional[int] = Query(default=None, ge=1900, le=2100),
    tmdb_id: Optional[int] = Query(default=None, ge=1),
    season: int = Query(default=0, ge=0),
    episode: int = Query(default=0, ge=0),
    scope_type: Optional[str] = Query(
        default=None,
        description="movie, series, season_pack, episode, or complete_series",
    ),
    limit: int = Query(default=100, ge=1, le=100),
) -> Dict[str, Any]:
    """Inspect one exact catalog scope without exposing provider references."""
    from moviebot.core.availability_service import AvailabilityService

    try:
        inspection = AvailabilityService.inspect(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, **inspection}


@router.post("/library/sync")
async def api_sync_library(domain: str = Query(default="movies")) -> Dict[str, Any]:
    """
    Syncs Plex library items for movies or TV into the local database
    and invalidates the in-memory ownership cache so Discover immediately reflects owned status.
    """
    from moviebot.adapters.plex_client import PlexClient
    from moviebot.core.conversational_rag import normalize_title
    from moviebot.db.repositories import LibraryItemRepository
    from moviebot.tools.discover_media_tool import _owned_cache
    from moviebot.tools.sync_tv_library_tool import sync_tv_library_tool

    db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain

    if db_domain in ("tv", "tv_classic"):
        res = await sync_tv_library_tool(domain=db_domain)
        _owned_cache.clear()
        return res

    client = PlexClient()
    movies = await client.fetch_all_movies()
    count = 0
    for m in movies:
        LibraryItemRepository.upsert(
            id=m["id"],
            source=m["source"],
            rating_key=m["rating_key"],
            title=m["title"],
            normalized_title=normalize_title(m["title"]),
            year=m["year"],
            imdb_id=m["imdb_id"],
            file_path=m["file_path"],
            size_bytes=m["size_bytes"],
            genres=m.get("genres"),
            directors=m.get("directors"),
            studios=m.get("studios"),
            writers=m.get("writers"),
            producers=m.get("producers"),
            cast=m.get("cast"),
            countries=m.get("countries"),
            content_rating=m.get("content_rating"),
            audience_rating=m.get("audience_rating"),
            tagline=m.get("tagline"),
            originally_available_at=m.get("originally_available_at"),
            labels=m.get("labels"),
            rating=m.get("rating"),
            runtime=m.get("runtime"),
            collections=m.get("collections"),
            resolution=m.get("resolution"),
            bitrate_kbps=m.get("bitrate_kbps"),
            watch_status=m.get("watch_status"),
            watch_count=m.get("watch_count"),
            last_watched_at=m.get("last_watched_at"),
            synopsis=m.get("synopsis"),
            synopsis_hash=m.get("synopsis_hash"),
            poster_url=m.get("poster_url")
        )
        count += 1

    _owned_cache.clear()
    return {
        "ok": True,
        "domain": "movies",
        "synced_count": count,
        "message": f"Successfully synced {count} movies from Plex."
    }


class IngestRequest(BaseModel):
    reference_id: Optional[str] = None
    title: Optional[str] = None
    domain: str = "movies"
    year: Optional[int] = None
    imdb_id: Optional[str] = None
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
    movie_eligibility = None

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

        if db_domain == "movies":
            movie_eligibility = await _evaluate_movie_request(
                title=req.title,
                year=req.year,
                imdb_id=req.imdb_id,
                tmdb_id=req.tmdb_id,
            )
            if not movie_eligibility.get("eligible"):
                return _movie_quality_gate_response(
                    movie_eligibility,
                    title=req.title,
                    domain=db_domain,
                    year=req.year,
                )

        search_res = await search_sources_tool(
            query=req.title,
            domain=db_domain,
            year=req.year,
            season=req.season,
            imdb_id=req.imdb_id,
            tmdb_id=req.tmdb_id,
            limit=25,
            check_cache=True,
            movie_eligibility=movie_eligibility,
        )
        if search_res.get("ok"):
            search_data = search_res.get("data", {})
            movie_eligibility = search_data.get("eligibility") or movie_eligibility
            if db_domain == "movies" and isinstance(movie_eligibility, dict) and not movie_eligibility.get("eligible"):
                return _movie_quality_gate_response(
                    movie_eligibility,
                    title=req.title,
                    domain=db_domain,
                    year=req.year,
                )

            results = search_data.get("results", [])
            if db_domain == "movies":
                results, _ = filter_movie_releases(results, movie_eligibility)
            ranked = score_and_rank_releases(
                results,
                preferred_quality=preferred_quality,
                prefer_cached=prefer_cached,
                target_title=req.title,
                target_year=req.year
            )
            # Filter out any candidates marked as mismatch or with non-positive score
            valid_ranked = [r for r in ranked if r.get("_score", 0) > 0 and not r.get("_mismatch")]
            if valid_ranked:
                ref_id = valid_ranked[0].get("reference_id")

    if not ref_id:
        return {
            "ok": False,
            "error_code": "UNRELEASED_OR_NO_SOURCES",
            "error": f"No confident exact match found for '{req.title}'{f' ({req.year})' if req.year else ''}. This title may be unreleased or only mismatched releases exist.",
            "title": req.title,
            "domain": db_domain,
            "year": req.year
        }

    res = await enqueue_download_tool(
        reference_id=ref_id,
        domain=db_domain,
        dry_run=req.dry_run,
        title=req.title,
        year=req.year,
        imdb_id=req.imdb_id,
        tmdb_id=req.tmdb_id,
        movie_eligibility=movie_eligibility,
    )

    if not res.get("ok"):
        err_obj = res.get("error", {})
        err_msg = err_obj.get("message", "Download enqueueing failed")
        response = {
            "ok": False,
            "error": err_msg,
            "title": req.title,
            "domain": db_domain,
            "details": res
        }
        if err_obj.get("code") == MOVIE_QUALITY_GATE_REJECTED:
            response["error_code"] = err_obj["code"]
            response["quality_gate"] = err_obj.get("quality_gate")
        return response

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


class DryRunRequest(BaseModel):
    title: str
    year: Optional[int] = None
    domain: str = "movies"
    preferred_quality: str = "1080p Web-DL"
    prefer_cached: bool = True
    season: Optional[int] = None


@router.post("/test/dry-run")
async def api_test_dry_run(req: DryRunRequest) -> Dict[str, Any]:
    """
    Dry-run simulation endpoint. Searches indexers, checks instant cache,
    runs precision scoring & mismatch guard, and returns comprehensive ranking telemetry.
    ZERO files downloaded, ZERO changes to database or IDM.
    """
    from moviebot.core.release_parser import score_and_rank_releases, compute_title_similarity, extract_year_from_title
    db_domain = "tv_classic" if req.domain in ("tv_classic", "classic_tv") else req.domain
    movie_eligibility = None
    if db_domain == "movies":
        movie_eligibility = await _evaluate_movie_request(
            title=req.title,
            year=req.year,
        )
        if not movie_eligibility.get("eligible"):
            return _movie_quality_gate_response(
                movie_eligibility,
                title=req.title,
                domain=db_domain,
                year=req.year,
            )

    search_res = await search_sources_tool(
        query=req.title,
        domain=db_domain,
        year=req.year,
        season=req.season,
        limit=30,
        check_cache=req.prefer_cached,
        movie_eligibility=movie_eligibility,
    )

    if not search_res.get("ok"):
        return {
            "ok": False,
            "error": search_res.get("error", {}).get("message", "Search failed"),
            "data": None
        }

    search_data = search_res.get("data", {})
    movie_eligibility = search_data.get("eligibility") or movie_eligibility
    if db_domain == "movies" and isinstance(movie_eligibility, dict) and not movie_eligibility.get("eligible"):
        return _movie_quality_gate_response(
            movie_eligibility,
            title=req.title,
            domain=db_domain,
            year=req.year,
        )

    raw_candidates = search_data.get("results", [])
    ranked = score_and_rank_releases(
        raw_candidates,
        preferred_quality=req.preferred_quality,
        prefer_cached=req.prefer_cached,
        target_title=req.title,
        target_year=req.year
    )

    # Attach detailed inspection logs to each candidate
    detailed_candidates = []
    for r in ranked:
        title = r.get("title") or ""
        sim = compute_title_similarity(req.title, title) if req.title else 1.0
        cand_year = extract_year_from_title(title)
        is_mismatch = bool(r.get("_mismatch"))
        score = r.get("_score", 0)

        breakdown = []
        if req.title:
            if sim >= 0.85:
                breakdown.append(f"+350 Exact Title Match ({int(sim*100)}%)")
            elif sim >= 0.60:
                breakdown.append(f"+150 Partial Title Match ({int(sim*100)}%)")
            else:
                breakdown.append(f"-5000 Low Title Similarity ({int(sim*100)}%)")

        if req.year:
            if cand_year == req.year:
                breakdown.append(f"+250 Exact Year Match ({cand_year})")
            elif cand_year and abs(cand_year - req.year) == 1:
                breakdown.append(f"+100 Release Year Drift ({cand_year})")
            elif cand_year:
                breakdown.append(f"-3000 Year Mismatch (found {cand_year} vs {req.year})")

        if r.get("cached"):
            breakdown.append("+1000 AllDebrid Instant Cache")

        res = r.get("_parsed", {}).get("resolution")
        if res == "1080p":
            breakdown.append("+500 1080p Resolution")
        elif res == "2160p":
            breakdown.append("+300 2160p Resolution")

        detailed_candidates.append({
            "title": title,
            "reference_id": r.get("reference_id"),
            "score": score,
            "cached": bool(r.get("cached")),
            "seeders": r.get("seeders", 0),
            "size": r.get("formatted_size") or format_size_bytes(r.get("size_bytes")),
            "resolution": res,
            "codec": r.get("_parsed", {}).get("codec"),
            "audio": r.get("_parsed", {}).get("audio"),
            "source_type": r.get("_parsed", {}).get("source_type"),
            "quality_label": r.get("_parsed", {}).get("quality_label"),
            "similarity_pct": int(sim * 100),
            "parsed_year": cand_year,
            "is_mismatch": is_mismatch,
            "status": "REJECTED" if is_mismatch or score <= 0 else "VALID",
            "score_breakdown": breakdown,
            "quality_gate": r.get("quality_gate") or movie_eligibility,
        })

    valid_candidates = [c for c in detailed_candidates if c["status"] == "VALID"]
    winner = valid_candidates[0] if valid_candidates else None

    return {
        "ok": True,
        "query": req.title,
        "target_year": req.year,
        "domain": db_domain,
        "total_raw_found": len(raw_candidates),
        "total_valid": len(valid_candidates),
        "winner": winner,
        "rejected_results": search_data.get("rejected_results", []),
        "rejected_count": search_data.get("rejected_count", 0),
        "quality_gate": movie_eligibility,
        "candidates": detailed_candidates,
        "simulation_log": [
            f"[1. Search] Querying Prowlarr indexers for '{req.title}'{f' ({req.year})' if req.year else ''} -> Found {len(raw_candidates)} releases",
            f"[2. Cache] Cross-referencing AllDebrid instant cache -> {sum(1 for c in detailed_candidates if c['cached'])} instant cached releases found",
            f"[3. Precision Guard] Validated title similarity & release year -> {len(valid_candidates)} passed, {len(detailed_candidates) - len(valid_candidates)} rejected as mismatches",
            f"[4. Scoring] Selected top candidate -> '{winner['title'] if winner else 'None'}' (Score: {winner['score'] if winner else 0})",
            f"[5. [SIMULATION]] Dry-Run mode active. No unrestrict request or IDM download queued."
        ]
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


@router.get("/tv/season-cache")
async def api_tv_season_cache(
    title: str = Query(..., description="TV Show title"),
    season: int = Query(1, description="Season number (0 for Complete Series)"),
    domain: str = Query(default="tv", description="Domain: tv or tv_classic"),
) -> Dict[str, Any]:
    """
    Checks Prowlarr indexers and AllDebrid instant cache for a specific TV show season or Complete Series run (season=0).
    Returns whether complete season packs or individual episodes are cached in AllDebrid RAM.
    """
    from moviebot.tools.search_sources_tool import search_sources_tool
    from moviebot.core.release_parser import extract_tv_spec, score_and_rank_releases
    from moviebot.db.cache_prewarm_repo import CachePrewarmRepository

    db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain

    # Check pre-warmed database cache first for instant sub-5ms return
    prewarmed = CachePrewarmRepository.get(db_domain, title, season=season, max_age_hours=12)
    if prewarmed:
        pack_data = {
            "reference_id": prewarmed["reference_id"],
            "title": prewarmed["release_title"],
            "resolution": prewarmed["resolution"] or "1080p",
            "size_formatted": prewarmed["formatted_size"] or "",
            "seeders": prewarmed["seeders"],
            "cached": prewarmed["cached"],
            "score": prewarmed["score"],
        }
        return {
            "ok": True,
            "title": title,
            "season": season,
            "domain": db_domain,
            "season_pack": pack_data,
            "cached_pack_count": 1 if prewarmed["cached"] else 0,
            "uncached_pack_count": 0 if prewarmed["cached"] else 1,
            "episode_cache_map": {},
            "total_releases_scanned": 1,
            "prewarmed": True
        }

    raw_candidates = []
    seen_refs = set()

    if season == 0:
        # Complete Series Run search
        queries = [f"{title} Complete Series", f"{title} Complete", f"{title} S01-"]
        for q in queries:
            res = await search_sources_tool(query=q, domain=db_domain, limit=20, check_cache=True)
            for r in res.get("data", {}).get("results", []):
                ref = r.get("reference_id")
                if ref and ref not in seen_refs:
                    seen_refs.add(ref)
                    raw_candidates.append(r)
    else:
        # Specific Season search
        query = f"{title} S{season:02d}"
        res = await search_sources_tool(query=query, domain=db_domain, limit=30, check_cache=True)
        for r in res.get("data", {}).get("results", []):
            ref = r.get("reference_id")
            if ref and ref not in seen_refs:
                seen_refs.add(ref)
                raw_candidates.append(r)

        if len(raw_candidates) < 5:
            res2 = await search_sources_tool(query=f"{title} Season {season}", domain=db_domain, limit=20, check_cache=True)
            for r in res2.get("data", {}).get("results", []):
                ref = r.get("reference_id")
                if ref and ref not in seen_refs:
                    seen_refs.add(ref)
                    raw_candidates.append(r)

    target_s = None if season == 0 else season
    ranked = score_and_rank_releases(raw_candidates, target_title=title, target_season=target_s)

    cached_packs = []
    uncached_packs = []
    episode_cache_map = {}

    for r in ranked:
        if r.get("_mismatch"):
            continue
        spec = extract_tv_spec(r.get("title", ""))
        is_cached = bool(r.get("cached"))
        ref_id = r.get("reference_id")

        if season == 0:
            if spec.get("is_complete_series") or "complete" in r.get("title", "").lower() or "s01-s" in r.get("title", "").lower() or "s01-" in r.get("title", "").lower():
                pack_info = {
                    "reference_id": ref_id,
                    "title": r.get("title"),
                    "resolution": r.get("resolution") or spec.get("resolution") or "1080p",
                    "size_formatted": r.get("formatted_size") or "",
                    "seeders": r.get("seeders", 0),
                    "cached": is_cached,
                    "score": r.get("_score", 0),
                }
                if is_cached:
                    cached_packs.append(pack_info)
                else:
                    uncached_packs.append(pack_info)
        else:
            if spec.get("is_season_pack") or spec.get("is_complete_series"):
                pack_info = {
                    "reference_id": ref_id,
                    "title": r.get("title"),
                    "resolution": r.get("resolution") or spec.get("resolution") or "1080p",
                    "size_formatted": r.get("formatted_size") or "",
                    "seeders": r.get("seeders", 0),
                    "cached": is_cached,
                    "score": r.get("_score", 0),
                }
                if is_cached:
                    cached_packs.append(pack_info)
                else:
                    uncached_packs.append(pack_info)
            elif spec.get("episode"):
                ep_num = spec.get("episode")
                if ep_num not in episode_cache_map or (is_cached and not episode_cache_map[ep_num].get("cached")):
                    episode_cache_map[ep_num] = {
                        "reference_id": ref_id,
                        "title": r.get("title"),
                        "resolution": r.get("resolution") or spec.get("resolution") or "1080p",
                        "size_formatted": r.get("formatted_size") or "",
                        "seeders": r.get("seeders", 0),
                        "cached": is_cached,
                    }

    best_pack = None
    if cached_packs:
        best_pack = cached_packs[0]
    elif uncached_packs:
        best_pack = uncached_packs[0]

    return {
        "ok": True,
        "title": title,
        "season": season,
        "domain": db_domain,
        "season_pack": best_pack,
        "cached_pack_count": len(cached_packs),
        "uncached_pack_count": len(uncached_packs),
        "episode_cache_map": episode_cache_map,
        "total_releases_scanned": len(ranked),
    }


class TVIngestEpisodesRequest(BaseModel):
    reference_id: Optional[str] = None
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
    Ingests TV episodes, season packs, or complete series runs by querying Prowlarr and queueing into IDM.
    """
    db_domain = "tv_classic" if req.domain in ("tv_classic", "classic_tv") else req.domain
    search_query = req.title

    # 1. If explicit reference_id provided (e.g. from Cache Inspector button), enqueue directly
    if req.reference_id:
        res = await enqueue_download_tool(
            reference_id=req.reference_id,
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
        label = "Complete Series Run" if req.season == 0 else f"Season {req.season} Pack"
        return {
            "ok": True,
            "job_id": job_data.get("job_id"),
            "title": req.title,
            "season": req.season,
            "domain": db_domain,
            "status": "queued",
            "message": f"⚡ Queued {req.title} ({label}) into IDM",
            "data": job_data
        }

    # 2. Complete Series Mode (season == 0)
    if req.season == 0:
        from moviebot.core.release_parser import extract_tv_spec, score_and_rank_releases

        # Check for single complete series boxset
        queries = [f"{req.title} Complete Series", f"{req.title} Complete", f"{req.title} S01-"]
        boxset_candidates = []
        for q in queries:
            s_res = await search_sources_tool(query=q, domain=db_domain, limit=15, check_cache=True)
            for r in s_res.get("data", {}).get("results", []):
                boxset_candidates.append(r)

        ranked_boxsets = score_and_rank_releases(boxset_candidates, target_title=req.title)
        valid_boxsets = [
            r for r in ranked_boxsets
            if not r.get("_mismatch") and (
                extract_tv_spec(r.get("title", "")).get("is_complete_series")
                or "complete" in r.get("title", "").lower()
                or "s01-s" in r.get("title", "").lower()
            )
        ]

        if valid_boxsets:
            best_boxset = valid_boxsets[0]
            res = await enqueue_download_tool(reference_id=best_boxset["reference_id"], domain=db_domain, dry_run=req.dry_run)
            job_data = res.get("data", {}) if res.get("ok") else {}
            return {
                "ok": True,
                "job_id": job_data.get("job_id"),
                "title": req.title,
                "season": 0,
                "domain": db_domain,
                "message": f"⚡ Queued Complete Series Boxset: {best_boxset.get('title')}",
                "data": job_data
            }

        # Fallback: Find and enqueue individual season packs
        queued_packs = []
        for s_idx in range(1, 15):
            s_search = await search_sources_tool(query=f"{req.title} S{s_idx:02d}", domain=db_domain, limit=5, check_cache=True)
            s_results = s_search.get("data", {}).get("results", [])
            if not s_results:
                s_search2 = await search_sources_tool(query=f"{req.title} Season {s_idx}", domain=db_domain, limit=5, check_cache=True)
                s_results = s_search2.get("data", {}).get("results", [])

            if s_results:
                ranked_s = score_and_rank_releases(s_results, target_title=req.title, target_season=s_idx)
                valid_s = [r for r in ranked_s if not r.get("_mismatch")]
                if valid_s:
                    best_s = valid_s[0]
                    enq = await enqueue_download_tool(reference_id=best_s["reference_id"], domain=db_domain, dry_run=req.dry_run)
                    if enq.get("ok"):
                        queued_packs.append(f"Season {s_idx}")

        if queued_packs:
            return {
                "ok": True,
                "title": req.title,
                "season": 0,
                "domain": db_domain,
                "message": f"⚡ Queued {len(queued_packs)} Season Packs ({', '.join(queued_packs)}) into IDM"
            }

        return {
            "ok": False,
            "error": f"No complete series boxset or season packs found for '{req.title}'",
            "title": req.title,
            "domain": db_domain
        }

    # 3. Specific Season Search & Download
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


# =========================================================================
# BLOCK 5.4: INSTANT CLOUD STREAMING & CLOUD PRE-CACHING ENDPOINTS
# =========================================================================

class StreamUnlockRequest(BaseModel):
    reference_id: Optional[str] = None
    magnet_url: Optional[str] = None
    domain: str = "movies"
    title: str = "Unknown Title"
    year: Optional[int] = None
    season: int = 0
    episode: int = 0
    file_id: Optional[int] = None
    poster_url: Optional[str] = None
    player_type: str = "web"


class VlcLaunchRequest(BaseModel):
    stream_url: str


class StreamProgressRequest(BaseModel):
    id: str
    progress_seconds: float
    duration_seconds: Optional[float] = None
    completed: Optional[bool] = None


class CloudPreCacheRequest(BaseModel):
    magnet_url: Optional[str] = None
    reference_id: Optional[str] = None
    domain: str = "movies"
    title: str = "Unknown Title"
    year: Optional[int] = None
    season: int = 0
    dry_run: bool = False


class BrowserStreamPrepareRequest(BaseModel):
    domain: str = "movies"
    title: str
    year: Optional[int] = None
    season: int = 0
    episode: int = 0
    dry_run: bool = False


_MEDIAFLOW_PILOT_FIXTURES = {
    "compatible": {
        "filename": "compatible.mp4",
        "label": "Compatible H.264/AAC",
        "expected_decision": "direct_play",
    },
    "surround": {
        "filename": "surround.mkv",
        "label": "H.264 with surround audio",
        "expected_decision": "audio_transcode",
    },
    "hevc": {
        "filename": "hevc10.mkv",
        "label": "HEVC 10-bit with EAC3",
        "expected_decision": "full_transcode",
    },
    "text-subtitle": {
        "filename": "text-subtitle.mkv",
        "label": "H.264/AAC with text subtitle",
        "expected_decision": "subtitle_webvtt",
    },
}


class MediaFlowPilotPlaybackRequest(BaseModel):
    fixture: str = "compatible"
    mode: str = "transcode_hls"
    start_seconds: Optional[float] = None


class MediaFlowProductionPlaybackRequest(BaseModel):
    release_variant_id: str
    domain: str = "movies"
    title: str
    year: Optional[int] = None
    season: int = 0
    episode: int = 0
    scope_type: Optional[str] = None
    file_id: Optional[int] = None
    start_seconds: Optional[float] = None
    audio_index: Optional[int] = None
    subtitle_index: Optional[int] = None
    supports_hls: bool = False
    supports_segmented_hls: bool = False
    dry_run: bool = False


class MediaFlowSessionEventRequest(BaseModel):
    event: str
    metrics: Dict[str, Any] = Field(default_factory=dict)


class MediaFlowSessionSeekRequest(BaseModel):
    start_seconds: float


def _mediaflow_pilot_gate(request: Request) -> Optional[Dict[str, Any]]:
    if not _is_local_request(request):
        return {
            "ok": False,
            "code": "MEDIAFLOW_PILOT_LOCAL_ONLY",
            "error": "The MediaFlow pilot is available only from the local host.",
        }
    if not settings.mediaflow_pilot_enabled:
        return {
            "ok": False,
            "code": "MEDIAFLOW_PILOT_DISABLED",
            "error": "The MediaFlow pilot is disabled. Set MEDIAFLOW_PILOT_ENABLED=true for local testing.",
        }
    if not settings.mediaflow_api_password:
        return {
            "ok": False,
            "code": "MEDIAFLOW_PASSWORD_MISSING",
            "error": "The MediaFlow pilot password is not configured.",
        }
    return None


def _mediaflow_pilot_source_url(filename: str) -> str:
    base_url = settings.mediaflow_pilot_fixture_base_url.rstrip("/")
    parsed = urlsplit(base_url)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or parsed.hostname not in {"host.docker.internal", "127.0.0.1", "localhost"}
        or parsed.username
        or parsed.password
    ):
        raise MediaFlowError(
            "MEDIAFLOW_FIXTURE_BASE_INVALID",
            "The MediaFlow fixture server must use a credential-free local HTTP(S) URL.",
        )
    return f"{base_url}/{quote(filename)}"


@router.get("/mediaflow/pilot")
async def api_mediaflow_pilot_info(request: Request) -> Dict[str, Any]:
    """Return safe pilot metadata without exposing fixture or provider URLs."""
    blocked = _mediaflow_pilot_gate(request)
    if blocked:
        return blocked
    try:
        health = await MediaFlowClient().health()
    except MediaFlowError:
        health = {
            "ok": False,
            "code": "MEDIAFLOW_HEALTH_FAILED",
            "message": "MediaFlow health check failed.",
        }
    return {
        "ok": True,
        "service": "mediaflow-proxy",
        "health": health,
        "fixtures": [
            {
                "id": fixture_id,
                "label": fixture["label"],
                "expected_decision": fixture["expected_decision"],
            }
            for fixture_id, fixture in _MEDIAFLOW_PILOT_FIXTURES.items()
        ],
        "modes": ["transcode_hls", "transcode_stream", "direct_stream"],
    }


@router.post("/mediaflow/pilot/playback")
async def api_mediaflow_pilot_playback(
    req: MediaFlowPilotPlaybackRequest,
    request: Request,
) -> Dict[str, Any]:
    """Generate a playback URL for one fixed local fixture, never a user URL."""
    blocked = _mediaflow_pilot_gate(request)
    if blocked:
        return blocked
    fixture = _MEDIAFLOW_PILOT_FIXTURES.get(req.fixture)
    if not fixture:
        return {
            "ok": False,
            "code": "MEDIAFLOW_FIXTURE_INVALID",
            "error": "The requested pilot fixture is not available.",
        }
    try:
        playback = await MediaFlowClient().generate_signed_playback_url(
            _mediaflow_pilot_source_url(fixture["filename"]),
            mode=req.mode,
            start_seconds=req.start_seconds,
            filename=fixture["filename"],
            expiration_seconds=300,
        )
    except MediaFlowError as exc:
        return {
            "ok": False,
            "code": exc.code,
            "error": exc.message,
        }
    except Exception as exc:
        logger.warning("[MediaFlow Pilot] playback request failed: %s", type(exc).__name__)
        return {
            "ok": False,
            "code": "MEDIAFLOW_PILOT_FAILED",
            "error": "The MediaFlow pilot playback request failed.",
        }

    safe_playback = {
        key: playback[key]
        for key in ("url", "endpoint", "mode", "expires_in_seconds", "requested_mode", "fallback_reason")
        if key in playback
    }
    return {
        "ok": True,
        "fixture": req.fixture,
        "label": fixture["label"],
        "expected_decision": fixture["expected_decision"],
        "playback": safe_playback,
    }


@router.get("/mediaflow/pilot/subtitle", response_class=PlainTextResponse)
async def api_mediaflow_pilot_subtitle(request: Request) -> PlainTextResponse:
    """Serve the fixed SRT fixture converted to WebVTT for the pilot page."""
    blocked = _mediaflow_pilot_gate(request)
    if blocked:
        return PlainTextResponse(blocked["error"], status_code=404)
    subtitle_path = Path(__file__).resolve().parents[3] / "scratch" / "mediaflow-fixtures" / "caption.srt"
    try:
        subtitle_text = subtitle_path.read_text(encoding="utf-8")
        from moviebot.core.mediaflow_pilot import text_subtitle_to_webvtt

        webvtt = text_subtitle_to_webvtt(subtitle_text, codec="subrip", language="eng")
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="Pilot subtitle fixture unavailable.")
    return PlainTextResponse(webvtt, media_type="text/vtt")


def _mediaflow_error(exc: MediaFlowAdapterError) -> Dict[str, Any]:
    diagnostics = exc.public_diagnostics()
    return {
        "ok": False,
        "code": exc.code,
        "error": exc.message,
        "retryable": exc.retryable,
        "severity": "error",
        "stage": diagnostics.get("stage", "unknown"),
        "diagnostics": diagnostics,
    }


def _record_mediaflow_event(
    *,
    event_type: str,
    variant_id: str,
    title: str,
    status: str,
    severity: str = "info",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    EventRepository.insert(
        event_type=event_type,
        source="mediaflow",
        title=title,
        summary="MediaFlow production playback state changed.",
        entity_type="release_variant",
        entity_id=variant_id,
        status=status,
        severity=severity,
        data_json=json.dumps(data or {}, sort_keys=True),
    )


def _recent_mediaflow_diagnostics(*, limit: int, failures_only: bool = False) -> List[Dict[str, Any]]:
    events = EventRepository.get_recent(max(50, min(250, int(limit) * 12)))
    if failures_only:
        events = [event for event in events if event.get("event_type") == "mediaflow_playback_failed"]
    return recent_diagnostics(events, limit=limit, mode=diagnostics_mode())


def _matching_catalog_variant(
    req: MediaFlowProductionPlaybackRequest,
) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
    variant = ReleaseVariantRepository.get_variant(req.release_variant_id)
    if variant is None:
        return None, None, {
            "ok": False,
            "code": "MEDIAFLOW_VARIANT_NOT_FOUND",
            "error": "The selected release variant does not exist.",
            "retryable": False,
        }
    try:
        requested_identity = ReleaseVariantRepository.media_identity(
            domain=req.domain,
            title=req.title,
            year=req.year,
            season=req.season,
            episode=req.episode,
            scope_type=req.scope_type,
        )
    except ValueError:
        return None, None, {
            "ok": False,
            "code": "MEDIAFLOW_SCOPE_INVALID",
            "error": "The requested media scope is invalid.",
            "retryable": False,
        }
    if variant.get("media_key") != requested_identity["media_key"]:
        return None, None, {
            "ok": False,
            "code": "MEDIAFLOW_VARIANT_SCOPE_MISMATCH",
            "error": "The selected release variant does not belong to the requested media scope.",
            "retryable": False,
        }
    projection = AvailabilityService.project(
        domain=variant["domain"],
        title=variant["title"],
        year=variant.get("year"),
        tmdb_id=variant.get("tmdb_id"),
        season=int(variant.get("season") or 0),
        episode=int(variant.get("episode") or 0),
        scope_type=variant.get("scope_type"),
    )
    public_variant = next(
        (
            item
            for item in projection.get("variants", [])
            if item.get("variant_id") == variant["variant_id"]
        ),
        None,
    )
    if not public_variant or public_variant.get("availability_state") not in {
        "ad_cached",
        "direct_play_ready",
    }:
        return None, None, {
            "ok": False,
            "code": "MEDIAFLOW_VARIANT_NOT_FRESHLY_CACHED",
            "error": "The selected release variant lacks fresh cached-provider evidence.",
            "retryable": True,
        }
    return variant, public_variant, None


@router.get("/mediaflow/status")
async def api_mediaflow_production_status(request: Request) -> Dict[str, Any]:
    """Return safe operator state for the disabled-by-default adapter."""
    if not _is_local_request(request):
        return {
            "ok": False,
            "code": "MEDIAFLOW_PRODUCTION_LOCAL_ONLY",
            "error": "MediaFlow production status is available only from the local host.",
        }
    config = production_configuration()
    result: Dict[str, Any] = {
        "ok": True,
        "adapter": "mediaflow-production",
        **config,
        **mediaflow_playback_registry.status(),
        "health": {"ok": False, "code": "MEDIAFLOW_PRODUCTION_DISABLED"},
        "diagnostics": {
            "mode": diagnostics_mode(),
            "schema_version": MEDIAFLOW_DIAGNOSTICS_SCHEMA_VERSION,
            "decision_version": MEDIAFLOW_DECISION_VERSION,
            "latest_failure": next(iter(_recent_mediaflow_diagnostics(limit=1, failures_only=True)), None),
        },
    }
    if config["enabled"] and config["configured"]:
        try:
            health = await MediaFlowProductionAdapter().health()
            result["health"] = health["health"]
            result["active_session_count"] = health["active_session_count"]
            result["capacity_profile_source"] = health.get("capacity_profile_source")
            result["capacity"] = health.get("capacity")
        except MediaFlowAdapterError as exc:
            result["health"] = {
                "ok": False,
                "code": exc.code,
                "retryable": exc.retryable,
                "message": exc.message,
            }
    return result


@router.get("/mediaflow/diagnostics")
async def api_mediaflow_diagnostics(
    request: Request,
    limit: int = Query(10, ge=1, le=25),
) -> Dict[str, Any]:
    """Return bounded, sanitized MediaFlow attempt diagnostics for local operators."""
    if not _is_local_request(request):
        return {
            "ok": False,
            "code": "MEDIAFLOW_DIAGNOSTICS_LOCAL_ONLY",
            "error": "MediaFlow diagnostics are available only from the local host.",
        }
    bounded_limit = max(1, min(int(limit), 25))
    return {
        "ok": True,
        "mode": diagnostics_mode(),
        "schema_version": MEDIAFLOW_DIAGNOSTICS_SCHEMA_VERSION,
        "decision_version": MEDIAFLOW_DECISION_VERSION,
        "attempts": _recent_mediaflow_diagnostics(limit=bounded_limit),
    }


@router.post("/mediaflow/playback")
async def api_mediaflow_production_playback(
    req: MediaFlowProductionPlaybackRequest,
    request: Request,
) -> Dict[str, Any]:
    """Prepare one exact cached catalog variant without exposing its source."""
    if not _is_local_request(request):
        return {
            "ok": False,
            "code": "MEDIAFLOW_PRODUCTION_LOCAL_ONLY",
            "error": "MediaFlow production playback is available only from the local host.",
            "retryable": False,
        }
    variant, public_variant, validation_error = _matching_catalog_variant(req)
    if validation_error:
        return validation_error
    assert variant is not None and public_variant is not None

    if variant["domain"] == "movies":
        eligibility = await _evaluate_movie_request(
            title=variant["title"],
            year=variant.get("year"),
            tmdb_id=variant.get("tmdb_id"),
        )
        if not eligibility.get("eligible"):
            return _movie_quality_gate_response(
                eligibility,
                title=variant["title"],
                domain=variant["domain"],
                year=variant.get("year"),
            )

    try:
        config = require_production_configuration()
    except MediaFlowAdapterError as exc:
        return _mediaflow_error(exc)
    if req.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "status": "would_prepare",
            "release_variant_id": variant["variant_id"],
            "availability_state": public_variant["availability_state"],
            "browser_stream_ready": public_variant["browser_stream_ready"],
            "adapter": {
                key: config[key]
                for key in (
                    "enabled",
                    "configured",
                    "localhost_only",
                    "expected_version",
                    "pin_valid",
                )
            },
        }

    checked_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        prepared = await MediaFlowProductionAdapter().prepare(
            variant,
            file_id=req.file_id,
            start_seconds=req.start_seconds,
            audio_index=req.audio_index,
            subtitle_index=req.subtitle_index,
            supports_hls=req.supports_hls,
            supports_segmented_hls=req.supports_segmented_hls,
        )
    except MediaFlowAdapterError as exc:
        ReleaseVariantRepository.update_mediaflow_outcome(
            variant["variant_id"],
            status="failed",
            checked_at=checked_at,
            error_code=exc.code,
            error_message=exc.message,
        )
        _record_mediaflow_event(
            event_type="mediaflow_playback_failed",
            variant_id=variant["variant_id"],
            title=variant["title"],
            status="failed",
            severity="error",
            data={
                "error_code": exc.code,
                "retryable": exc.retryable,
                "diagnostics": exc.public_diagnostics(),
            },
        )
        return _mediaflow_error(exc)

    ReleaseVariantRepository.update_mediaflow_outcome(
        variant["variant_id"],
        status="candidate",
        checked_at=checked_at,
    )
    _record_mediaflow_event(
        event_type="mediaflow_playback_prepared",
        variant_id=variant["variant_id"],
        title=variant["title"],
        status="prepared",
        data={
            "session_id": prepared["session_id"],
            "decision": prepared["decision"].get("decision"),
            "mode": prepared["mode"],
            "fallback_reason": prepared.get("fallback_reason"),
            "capacity_profile_source": (prepared.get("capacity") or {}).get("profile_source"),
        },
    )
    return {
        "ok": True,
        "adapter": "mediaflow-production",
        "release_variant_id": variant["variant_id"],
        "session_id": prepared["session_id"],
        "stream_id": prepared["session_id"],
        "stream_url": f"/api/mediaflow/sessions/{prepared['session_id']}/stream",
        "mediaflow_playback_ready": True,
        "browser_stream_ready": public_variant["browser_stream_ready"],
        "availability_state": public_variant["availability_state"],
        "decision": prepared["decision"],
        "mode": prepared["mode"],
        "fallback_reason": prepared.get("fallback_reason"),
        "filename": prepared["filename"],
        "filesize": prepared["filesize"],
        "duration_seconds": prepared.get("duration_seconds"),
        "mime_type": prepared["mime_type"],
        "capacity": prepared.get("capacity"),
        "title": variant["title"],
        "year": variant.get("year"),
        "season": int(variant.get("season") or 0),
        "episode": int(variant.get("episode") or 0),
        "domain": variant["domain"],
        "initial_progress": 0.0,
        "expires_at": prepared["expires_at"],
        "runtime_metrics": prepared["runtime_metrics"],
    }


@router.get("/mediaflow/sessions/{session_id}/stream")
async def api_mediaflow_session_stream(
    session_id: str,
    request: Request,
) -> Response:
    if not _is_local_request(request):
        raise HTTPException(status_code=404, detail="MediaFlow session unavailable.")
    session = mediaflow_playback_registry.get(session_id)
    if session and session.mode == "transcode_hls":
        manifest = mediaflow_playback_registry.resolve_manifest(session_id)
        if not manifest:
            raise HTTPException(status_code=404, detail="MediaFlow segmented playlist unavailable.")
        return PlainTextResponse(
            manifest,
            media_type="application/vnd.apple.mpegurl",
            headers={
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Content-Type-Options": "nosniff",
            },
        )
    playback_url = mediaflow_playback_registry.resolve(session_id)
    if not playback_url:
        raise HTTPException(status_code=404, detail="MediaFlow session expired or unavailable.")
    return RedirectResponse(
        playback_url,
        status_code=307,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


@router.get("/mediaflow/sessions/{session_id}/segments/{segment_key}")
async def api_mediaflow_session_segment(
    session_id: str,
    segment_key: str,
    request: Request,
) -> Response:
    """Proxy one private MediaFlow segment through an opaque bounded route."""
    if not _is_local_request(request):
        raise HTTPException(status_code=404, detail="MediaFlow segment unavailable.")
    session = mediaflow_playback_registry.get(session_id)
    target = mediaflow_playback_registry.resolve_segment(session_id, segment_key)
    if session is None or target is None:
        raise HTTPException(status_code=404, detail="MediaFlow segment unavailable.")

    producer_had_output = mediaflow_playback_registry.producer_has_output(session_id)
    timeout_code = (
        "MEDIAFLOW_PRODUCER_IDLE_TIMEOUT"
        if producer_had_output
        else "MEDIAFLOW_PRODUCER_STARTUP_TIMEOUT"
    )
    timeout_seconds = (
        settings.mediaflow_segment_idle_timeout_seconds
        if producer_had_output
        else settings.mediaflow_segment_startup_timeout_seconds
    )
    try:
        segment_bytes, media_type = await fetch_segment_bytes(
            target,
            timeout_seconds=timeout_seconds,
            max_bytes=settings.mediaflow_segment_max_bytes,
            timeout_code=timeout_code,
        )
    except MediaFlowSegmentedError as exc:
        stage = (
            "producer_startup"
            if exc.code == "MEDIAFLOW_PRODUCER_STARTUP_TIMEOUT"
            else ("producer_idle" if exc.code == "MEDIAFLOW_PRODUCER_IDLE_TIMEOUT" else "producer")
        )
        diagnostics = project_diagnostics(
            build_diagnostics(
                stage=stage,
                code=exc.code,
                retryable=exc.retryable,
                variant_id=session.variant_id,
                delivery_decision=session.decision.get("decision"),
                workload=session.workload,
            ),
            mode=diagnostics_mode(),
        )
        mediaflow_playback_registry.mark_producer_failed(session_id, exc.code)
        variant = ReleaseVariantRepository.get_variant(session.variant_id) or {}
        _record_mediaflow_event(
            event_type="mediaflow_playback_failed",
            variant_id=session.variant_id,
            title=str(variant.get("title") or "MediaFlow playback"),
            status="failed",
            severity="error",
            data={
                "session_id": session_id,
                "error_code": exc.code,
                "diagnostics": diagnostics,
            },
        )
        mediaflow_playback_registry.close(session_id, reason=exc.code.lower())
        return PlainTextResponse(
            exc.message,
            status_code=504 if "TIMEOUT" in exc.code else 502,
            headers={
                "Cache-Control": "no-store",
                "X-MediaFlow-Code": exc.code,
            },
        )

    was_first_media_output = segment_key != "init" and not producer_had_output
    snapshot = mediaflow_playback_registry.record_segment_output(
        session_id,
        segment_key,
        len(segment_bytes),
    )
    if was_first_media_output and snapshot:
        variant = ReleaseVariantRepository.get_variant(session.variant_id) or {}
        _record_mediaflow_event(
            event_type="mediaflow_segmented_started",
            variant_id=session.variant_id,
            title=str(variant.get("title") or "MediaFlow playback"),
            status="playing",
            data={
                "session_id": session_id,
                "producer": snapshot.get("producer"),
            },
        )
    return Response(
        content=segment_bytes,
        media_type=media_type if media_type in {"video/mp4", "application/octet-stream"} else "video/mp4",
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/mediaflow/sessions/{session_id}/seek")
async def api_mediaflow_session_seek(
    session_id: str,
    req: MediaFlowSessionSeekRequest,
    request: Request,
) -> Dict[str, Any]:
    """Rotate one active transcoding session to a requested timeline position."""
    if not _is_local_request(request):
        return {"ok": False, "code": "MEDIAFLOW_PRODUCTION_LOCAL_ONLY", "retryable": False}
    if not math.isfinite(req.start_seconds) or req.start_seconds < 0:
        return {
            "ok": False,
            "code": "MEDIAFLOW_SEEK_INVALID",
            "error": "The requested seek position is invalid.",
            "retryable": False,
        }
    try:
        result = await MediaFlowProductionAdapter().seek(session_id, req.start_seconds)
    except MediaFlowAdapterError as exc:
        return _mediaflow_error(exc)

    _record_mediaflow_event(
        event_type="mediaflow_playback_seek_requested",
        variant_id=result["variant_id"],
        title=(ReleaseVariantRepository.get_variant(result["variant_id"]) or {}).get(
            "title", "MediaFlow playback"
        ),
        status="seeking",
        data={
            "session_id": session_id,
            "start_seconds": result["start_seconds"],
        },
    )
    return {
        "ok": True,
        "session_id": session_id,
        "stream_url": f"/api/mediaflow/sessions/{session_id}/stream",
        "start_seconds": result["start_seconds"],
        "duration_seconds": result["duration_seconds"],
        "mode": result["mode"],
        "session": result,
    }


@router.post("/mediaflow/sessions/{session_id}/events")
async def api_mediaflow_session_event(
    session_id: str,
    req: MediaFlowSessionEventRequest,
    request: Request,
) -> Dict[str, Any]:
    if not _is_local_request(request):
        return {"ok": False, "code": "MEDIAFLOW_PRODUCTION_LOCAL_ONLY"}
    session = mediaflow_playback_registry.get(session_id)
    if session is None:
        return {"ok": False, "code": "MEDIAFLOW_SESSION_NOT_FOUND", "retryable": False}
    event_name = req.event.strip().lower()
    if event_name not in {"playing", "failed", "seeking", "ended"}:
        return {"ok": False, "code": "MEDIAFLOW_EVENT_INVALID", "retryable": False}
    metrics = sanitize_runtime_metrics(req.metrics)
    browser_diagnostics = None
    if event_name == "playing":
        metrics["first_frame_latency_ms"] = max(
            0,
            int((datetime.datetime.now(datetime.timezone.utc) - session.created_at).total_seconds() * 1000),
        )
        ReleaseVariantRepository.update_mediaflow_outcome(
            session.variant_id,
            status="verified",
            checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        )
    elif event_name == "failed":
        ReleaseVariantRepository.update_mediaflow_outcome(
            session.variant_id,
            status="failed",
            checked_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            error_code="MEDIAFLOW_BROWSER_PLAYBACK_FAILED",
            error_message="The browser reported a MediaFlow playback failure.",
        )
        failure_stage = "seek" if metrics.get("exit_reason") == "seek_failed" else "browser_playback"
        browser_diagnostics = project_diagnostics(
            build_diagnostics(
                stage=failure_stage,
                code=(
                    "MEDIAFLOW_SEEK_FAILED"
                    if failure_stage == "seek"
                    else "MEDIAFLOW_BROWSER_PLAYBACK_FAILED"
                ),
                retryable=True,
                variant_id=session.variant_id,
                delivery_decision=session.decision.get("decision"),
                workload=session.workload,
            )
        )
    snapshot = mediaflow_playback_registry.mark(session_id, event_name)
    variant = ReleaseVariantRepository.get_variant(session.variant_id) or {}
    _record_mediaflow_event(
        event_type=f"mediaflow_playback_{event_name}",
        variant_id=session.variant_id,
        title=str(variant.get("title") or "MediaFlow playback"),
        status=event_name,
        severity="error" if event_name == "failed" else "info",
        data={
            "session_id": session_id,
            "decision": session.decision.get("decision"),
            "metrics": metrics,
            **({"diagnostics": browser_diagnostics} if browser_diagnostics else {}),
        },
    )
    return {"ok": True, "session": snapshot, "runtime_metrics": metrics}


@router.delete("/mediaflow/sessions/{session_id}")
async def api_mediaflow_session_close(
    session_id: str,
    request: Request,
) -> Dict[str, Any]:
    if not _is_local_request(request):
        return {"ok": False, "code": "MEDIAFLOW_PRODUCTION_LOCAL_ONLY"}
    requested_reason = request.headers.get("x-mediaflow-exit-reason", "client_closed")
    reason = (
        requested_reason
        if requested_reason in {"client_closed", "source_replaced", "completed"}
        else "client_closed"
    )
    result = mediaflow_playback_registry.close(session_id, reason=reason)
    return {"ok": True, **result}


def _find_vlc_executable() -> Optional[str]:
    """Resolve a local VLC executable without exposing or scanning arbitrary paths."""
    configured = [
        getattr(settings, "vlc_path", None),
        os.environ.get("VLC_PATH"),
        shutil.which("vlc.exe"),
        shutil.which("vlc"),
    ]
    if os.name == "nt":
        configured.extend([
            r"C:\Program Files\VideoLAN\VLC\vlc.exe",
            r"C:\Program Files (x86)\VideoLAN\VLC\vlc.exe",
        ])

    for candidate in configured:
        if not candidate:
            continue
        try:
            path = Path(os.path.expandvars(os.path.expanduser(str(candidate))))
        except (TypeError, ValueError):
            continue
        if path.is_file() and path.name.lower() in {"vlc", "vlc.exe"}:
            return str(path)
    return None


def _validate_vlc_stream_url(stream_url: str) -> bool:
    """Allow only direct HTTPS media URLs to reach the local VLC process."""
    if not isinstance(stream_url, str) or not stream_url or any(
        control in stream_url for control in ("\x00", "\r", "\n")
    ):
        return False
    try:
        parsed = urlsplit(stream_url)
        hostname = parsed.hostname
    except ValueError:
        return False
    return parsed.scheme.lower() == "https" and bool(hostname) and not parsed.username and not parsed.password


def _is_local_request(request: Request) -> bool:
    """Keep desktop process launching limited to a browser on this host."""
    return bool(request.client and request.client.host in {"127.0.0.1", "::1", "localhost"})


@router.post("/player/vlc")
async def api_open_vlc(req: VlcLaunchRequest, request: Request) -> Dict[str, Any]:
    """Open the current fresh stream URL in the local VLC desktop application."""
    if not _is_local_request(request):
        return {
            "ok": False,
            "code": "LOCAL_PLAYER_ONLY",
            "retryable": False,
            "error": "VLC can only be launched from the local Media Bot host.",
        }

    if not _validate_vlc_stream_url(req.stream_url):
        return {
            "ok": False,
            "code": "INVALID_STREAM_URL",
            "retryable": False,
            "error": "VLC requires a valid HTTPS stream URL.",
        }

    vlc_executable = _find_vlc_executable()
    if not vlc_executable:
        return {
            "ok": False,
            "code": "VLC_NOT_FOUND",
            "retryable": False,
            "error": "VLC was not found on the Media Bot host. Use Copy Stream URL and open it in VLC manually.",
        }

    popen_kwargs: Dict[str, Any] = {"shell": False, "close_fds": True}
    if os.name == "nt":
        popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        process = subprocess.Popen([vlc_executable, req.stream_url], **popen_kwargs)
    except OSError:
        logger.warning("[VLC Launch] VLC process could not be started")
        return {
            "ok": False,
            "code": "VLC_START_FAILED",
            "retryable": True,
            "error": "VLC could not be started. Use Copy Stream URL and open it in VLC manually.",
        }

    return {"ok": True, "player": "vlc", "status": "started", "pid": process.pid}


def _is_exact_browser_candidate(
    release_title: str,
    requested_title: str,
    db_domain: str,
    year: Optional[int] = None,
    season: int = 0,
    episode: int = 0,
) -> bool:
    if not is_exact_media_identity(requested_title, release_title):
        return False
    if db_domain == "movies" and year:
        return extract_year_from_title(release_title) == year
    if db_domain in ("tv", "tv_classic") and season > 0:
        parsed = parse_release_details(release_title)
        if parsed.get("season") != season:
            return False
        if episode > 0 and parsed.get("episode") != episode:
            return False
    return True


@router.post("/stream/unlock")
async def api_stream_unlock(req: StreamUnlockRequest) -> Dict[str, Any]:
    """
    Resolves a direct high-speed HTTPS streaming URL for a cached AllDebrid
    release without downloading to local disk, and reports whether the
    resulting file is browser-streamable.
    """
    from moviebot.adapters.alldebrid_client import AllDebridClient
    from moviebot.db.stream_history_repo import StreamHistoryRepository
    from moviebot.core.background_prewarmer import resolve_magnet_uri

    db_domain = "tv_classic" if req.domain in ("tv_classic", "classic_tv") else req.domain
    movie_eligibility = None
    if db_domain == "movies":
        movie_eligibility = await _evaluate_movie_request(
            title=req.title,
            year=req.year,
        )
        if not movie_eligibility.get("eligible"):
            return _movie_quality_gate_response(
                movie_eligibility,
                title=req.title,
                domain=db_domain,
                year=req.year,
            )
        if req.reference_id:
            referenced = SearchResultRepository.get_by_id(req.reference_id, domain=db_domain)
            if referenced:
                referenced_decision = assess_movie_release(
                    {"title": referenced.get("title") or ""},
                    movie_eligibility,
                )
                if not referenced_decision.get("eligible"):
                    return _movie_quality_gate_response(
                        referenced_decision,
                        title=req.title,
                        domain=db_domain,
                        year=req.year,
                    )
    dynamic_cached_candidates: List[Dict[str, Any]] = []

    # Resolve magnet link
    target_mag = req.magnet_url or ""
    selected_reference_id = req.reference_id
    if not target_mag and req.reference_id:
        target_mag = resolve_magnet_uri(req.reference_id, domain=db_domain)

    if not target_mag or not target_mag.startswith("magnet:"):
        # 1. Check prewarmed cache for verified cached release
        cached_entry = CachePrewarmRepository.get(
            db_domain,
            normalize_title(req.title),
            season=req.season,
            year=req.year if db_domain == "movies" else None,
            max_age_hours=12,
        )
        if cached_entry and cached_entry.get("browser_stream_ready") and cached_entry.get("stream_reference_id"):
            selected_reference_id = cached_entry["stream_reference_id"]
            target_mag = resolve_magnet_uri(selected_reference_id, domain=db_domain)

    if not target_mag or not target_mag.startswith("magnet:"):
        # 2. Dynamic lookup via search_sources_tool with fast batch instant cache checking across top 12 releases
        query = req.title
        if req.year and db_domain == "movies" and str(req.year) not in query:
            query = f"{query} {req.year}"
        if db_domain in ("tv", "tv_classic") and req.season > 0:
            query = f"{query} S{req.season:02d}"
        search_res = await search_sources_tool(
            query=query,
            domain=db_domain,
            limit=12,
            check_cache=False,
            movie_eligibility=movie_eligibility,
        )
        results = search_res.get("data", {}).get("results", [])
        if db_domain == "movies":
            results, _ = filter_movie_releases(results, movie_eligibility)
        if results:
            mags_to_check = [resolve_magnet_uri(r.get("reference_id", "")) for r in results if r.get("reference_id")]
            valid_mags = [m for m in mags_to_check if m.startswith("magnet:")]
            ad_client = AllDebridClient()
            avail_res = await ad_client.instant_check(valid_mags)
            avail_magnets = avail_res.get("magnets", [])
            cached_mags = set(item.get("magnet") for item in avail_magnets if item.get("instant"))

            cached_results = [r for r in results if resolve_magnet_uri(r.get("reference_id", "")) in cached_mags]

            if cached_results:
                exact_cached_results = [
                    r for r in cached_results
                    if _is_exact_browser_candidate(
                        r.get("title", ""),
                        req.title,
                        db_domain,
                        year=req.year,
                        season=req.season,
                        episode=req.episode,
                    )
                ]
                if not exact_cached_results:
                    return {
                        "ok": False,
                        "cached": False,
                        "title": req.title,
                        "domain": db_domain,
                        "code": "NO_EXACT_CACHED_RELEASE",
                        "retryable": False,
                        "severity": "info",
                        "error": f"No exact cached release was found for '{req.title}'.",
                    }
                cached_results = exact_cached_results
            if cached_results:
                # Prioritize H.264 / x264 MP4 releases for universal in-browser HTML5 decoding compatibility
                browser_cached_results = [
                    r for r in cached_results
                    if classify_browser_stream_candidate(r.get("title", "")) != "explicitly_incompatible"
                ]
                ranked_results = browser_cached_results or cached_results

                def _browser_score(r):
                    t = (r.get("title") or "").lower()
                    score = 0
                    if is_browser_stream_compatible(t):
                        score += 200
                    if "1080p" in t:
                        score += 50
                    elif "720p" in t:
                        score += 30
                    if "x265" in t or "hevc" in t or "h265" in t or "10bit" in t:
                        score -= 100
                    return score

                sorted_cached = sorted(ranked_results, key=_browser_score, reverse=True)
                dynamic_cached_candidates = sorted_cached[:3]
                best = dynamic_cached_candidates[0]
                if best.get("reference_id"):
                    selected_reference_id = best["reference_id"]
                    target_mag = resolve_magnet_uri(selected_reference_id, domain=db_domain)
            elif cached_entry and cached_entry.get("cached") and cached_entry.get("reference_id"):
                # Fall back to prewarmed cache if dynamic check found no cached alternatives
                selected_reference_id = cached_entry.get("download_reference_id") or cached_entry["reference_id"]
                target_mag = resolve_magnet_uri(selected_reference_id, domain=db_domain)
            else:
                # No instant-cached releases exist on indexers
                best_uncached = results[0]
                uncached_mag = resolve_magnet_uri(best_uncached.get("reference_id", ""))
                return {
                    "ok": False,
                    "cached": False,
                    "title": req.title,
                    "domain": db_domain,
                    "season": req.season,
                    "magnet_url": uncached_mag,
                    "error": f"'{req.title}' is not instant-cached on AllDebrid yet. Click 'Cache to AD' to download it to cloud first."
                }
        elif cached_entry and cached_entry.get("cached") and cached_entry.get("reference_id"):
            selected_reference_id = cached_entry.get("download_reference_id") or cached_entry["reference_id"]
            target_mag = resolve_magnet_uri(selected_reference_id, domain=db_domain)

    if not target_mag or not target_mag.startswith("magnet:"):
        return {
            "ok": False,
            "cached": False,
            "title": req.title,
            "error": f"No valid streaming releases found for '{req.title}'."
        }

    try:
        ad_client = AllDebridClient()
        stream_payload: Optional[Dict[str, Any]] = None
        verification: Optional[Dict[str, Any]] = None
        last_error: Optional[Exception] = None
        candidates_to_try = dynamic_cached_candidates or [{"reference_id": selected_reference_id, "magnet_url": target_mag}]
        for candidate in candidates_to_try[:3]:
            candidate_reference_id = candidate.get("reference_id") or selected_reference_id
            candidate_mag = candidate.get("magnet_url") or target_mag
            if candidate_reference_id and not candidate.get("magnet_url"):
                candidate_mag = resolve_magnet_uri(candidate_reference_id, domain=db_domain)
            if not candidate_mag.startswith("magnet:"):
                continue
            try:
                payload = await ad_client.unlock_magnet_stream(
                    magnet_link=candidate_mag,
                    file_id=req.file_id,
                    season=req.season if req.season > 0 else None,
                    episode=req.episode if req.episode > 0 else None
                )
                candidate_verification = await verify_stream_payload(payload)
            except Exception as exc:
                last_error = exc
                continue
            if stream_payload is None:
                stream_payload = payload
                verification = candidate_verification
                selected_reference_id = candidate_reference_id or selected_reference_id
                target_mag = candidate_mag
            if candidate_verification.get("verified"):
                stream_payload = payload
                verification = candidate_verification
                selected_reference_id = candidate_reference_id or selected_reference_id
                target_mag = candidate_mag
                break

        if stream_payload is None:
            if last_error:
                raise last_error
            raise RuntimeError("No candidate could be unlocked for streaming.")

        browser_stream_ready = bool(verification and verification.get("verified"))

        if browser_stream_ready and selected_reference_id:
            CachePrewarmRepository.update_browser_stream_candidate(
                domain=db_domain,
                title=req.title,
                season=req.season,
                year=req.year if db_domain == "movies" else None,
                reference_id=selected_reference_id,
                release_title=stream_payload.get("filename") or "",
                size_bytes=int(stream_payload.get("filesize") or 0),
                browser_verification=verification,
            )

        # Movies with the same normalized title can represent different
        # releases/remakes. Keep the year in the session identity so a
        # Matrix (1999) preview cannot reuse Matrix Resurrections history.
        stream_id = f"{db_domain}:{normalize_title(req.title)}:{req.year or 0}:{req.season}:{req.episode}"
        
        # Check existing history to retrieve resume point
        existing = StreamHistoryRepository.get_by_id(stream_id)
        initial_progress = existing.get("progress_seconds", 0.0) if existing else 0.0

        # Upsert stream session record
        StreamHistoryRepository.upsert(
            id=stream_id,
            domain=db_domain,
            title=req.title,
            year=req.year if db_domain == "movies" else None,
            season=req.season,
            episode=req.episode,
            release_title=stream_payload.get("filename"),
            stream_url=stream_payload.get("stream_url"),
            duration_seconds=existing.get("duration_seconds", 0.0) if existing else 0.0,
            progress_seconds=initial_progress,
            player_type=req.player_type,
            poster_url=req.poster_url
        )

        return {
            "ok": True,
            "cached": True,
            "cloud_cached": True,
            "instant_download_ready": True,
            "instant_cached": browser_stream_ready,
            "browser_stream_ready": browser_stream_ready,
            "stream_id": stream_id,
            "stream_url": stream_payload.get("stream_url"),
            "filename": stream_payload.get("filename"),
            "filesize": stream_payload.get("filesize"),
            "mime_type": stream_payload.get("mime_type"),
            "file_id": stream_payload.get("file_id"),
            "subtitles": stream_payload.get("subtitles", []),
            "all_files": stream_payload.get("all_files", []),
            "initial_progress": initial_progress,
            "title": req.title,
            "year": req.year,
            "season": req.season,
            "episode": req.episode,
            "domain": db_domain,
            "browser_verification": verification,
        }
    except Exception as e:
        logger.error("[Stream Unlock] Failed to unlock stream for '%s': %s", req.title, e)
        error_code = getattr(e, "code", "STREAM_UNLOCK_FAILED")
        retryable = bool(getattr(e, "retryable", False))
        return {
            "ok": False,
            "cached": False,
            "title": req.title,
            "domain": db_domain,
            "season": req.season,
            "magnet_url": target_mag,
            "code": error_code,
            "retryable": retryable,
            "severity": "error",
            "error": str(e)
        }


@router.post("/stream/progress")
async def api_stream_progress(req: StreamProgressRequest) -> Dict[str, Any]:
    """
    Heartbeat endpoint called by video player to persist real-time playback position,
    duration, and completion state.
    """
    from moviebot.db.stream_history_repo import StreamHistoryRepository

    updated = StreamHistoryRepository.update_progress(
        id=req.id,
        progress_seconds=req.progress_seconds,
        duration_seconds=req.duration_seconds,
        completed=req.completed
    )

    if not updated:
        return {"ok": False, "error": "Stream session not found."}

    return {"ok": True, "session": updated}


@router.get("/stream/history")
async def api_stream_history(
    limit: int = Query(default=50),
    domain: str = Query(default="all")
) -> Dict[str, Any]:
    """
    Retrieves recent cloud-streamed titles with playback progress and resume points.
    """
    from moviebot.db.stream_history_repo import StreamHistoryRepository

    streams = StreamHistoryRepository.get_recent(limit=limit, domain=domain)
    return {
        "ok": True,
        "streams": streams,
        "count": len(streams)
    }


@router.delete("/stream/history/{stream_id}")
async def api_delete_stream_history(stream_id: str) -> Dict[str, Any]:
    """
    Deletes a streaming session from history.
    """
    from moviebot.db.stream_history_repo import StreamHistoryRepository

    deleted = StreamHistoryRepository.delete(stream_id)
    return {"ok": deleted}


def _browser_prepare_candidates(
    results: List[Dict[str, Any]],
    req: BrowserStreamPrepareRequest,
    db_domain: str,
) -> List[Dict[str, Any]]:
    """Return exact-identity candidates; provider-file proof follows selection."""
    compatible: List[Dict[str, Any]] = []
    for result in results:
        release_title = result.get("title") or ""
        if classify_browser_stream_candidate(release_title) == "explicitly_incompatible":
            continue
        if compute_title_similarity(req.title, release_title) < 0.85:
            continue
        if not _is_exact_browser_candidate(
            release_title,
            req.title,
            db_domain,
            year=req.year,
            season=req.season,
            episode=req.episode,
        ):
            continue
        if db_domain == "movies" and req.year:
            if extract_year_from_title(release_title) != req.year:
                continue
        if db_domain in ("tv", "tv_classic") and req.season > 0:
            parsed = parse_release_details(release_title)
            if parsed.get("season") not in (req.season, None):
                continue
            if req.episode > 0 and parsed.get("episode") not in (req.episode, None):
                continue
        compatible.append(result)

    return score_and_rank_releases(
        compatible,
        preferred_quality="1080p Web-DL",
        prefer_cached=True,
        target_title=req.title,
        target_year=req.year if db_domain == "movies" else None,
        target_season=req.season if req.season > 0 else None,
        target_episode=req.episode if req.episode > 0 else None,
    )


def _record_cloud_event(
    event_type: str,
    title: str,
    status: str,
    summary: str,
    data: Dict[str, Any],
) -> None:
    EventRepository.insert(
        event_type=event_type,
        source="web",
        title=title,
        summary=summary,
        entity_type=data.get("domain") or "media",
        entity_id=str(data.get("transfer_id") or data.get("reference_id") or ""),
        status=status,
        data_json=json.dumps(data),
    )


def _persist_verified_browser_candidate(
    intent: Dict[str, Any],
    actual_filename: str,
    size_bytes: int = 0,
    verification: Optional[Dict[str, Any]] = None,
) -> None:
    evidence = dict(verification or {})
    evidence.update({
        "status": "verified_browser_ready",
        "reference_id": intent["reference_id"],
        "actual_filename": actual_filename,
        "filesize": size_bytes,
    })
    CachePrewarmRepository.upsert(
        domain=intent["domain"],
        title=intent["title"],
        season=int(intent.get("season") or 0),
        year=intent.get("year") if intent["domain"] == "movies" else None,
        reference_id=intent["reference_id"],
        release_title=actual_filename,
        resolution=parse_release_details(actual_filename).get("resolution") or "1080p",
        size_bytes=size_bytes,
        cached=True,
        vector_origin="manual_browser_prepare",
        data={
            "purpose": "browser_stream",
            "transfer_id": intent.get("transfer_id"),
            "verified_filename": actual_filename,
            "browser_verification": evidence,
        },
        browser_stream_reference_id=intent["reference_id"],
        browser_stream_release_title=actual_filename,
        browser_verification=evidence,
    )


def _persist_generic_cached_intent(intent: Dict[str, Any], size_bytes: int = 0) -> None:
    existing = CachePrewarmRepository.get(
        intent["domain"],
        intent["title"],
        season=int(intent.get("season") or 0),
        year=intent.get("year") if intent["domain"] == "movies" else None,
    )
    CachePrewarmRepository.upsert(
        domain=intent["domain"],
        title=intent["title"],
        season=int(intent.get("season") or 0),
        year=intent.get("year") if intent["domain"] == "movies" else None,
        reference_id=intent["reference_id"],
        release_title=intent["release_title"],
        resolution=parse_release_details(intent["release_title"]).get("resolution") or "1080p",
        size_bytes=size_bytes,
        cached=True,
        vector_origin="cloud_precache",
        data={"purpose": intent["purpose"], "transfer_id": intent["transfer_id"]},
        browser_stream_reference_id=(existing or {}).get("browser_stream_reference_id"),
        browser_stream_release_title=(existing or {}).get("browser_stream_release_title"),
    )


async def _verify_browser_transfer(
    intent: Dict[str, Any],
    ad_client: Any,
    size_bytes: int = 0,
) -> Dict[str, Any]:
    from moviebot.core.background_prewarmer import resolve_magnet_uri

    target_mag = resolve_magnet_uri(intent["reference_id"], domain=intent["domain"])
    if not target_mag.startswith("magnet:"):
        CloudTransferIntentRepository.update_status(
            intent["transfer_id"],
            "failed",
            error_message="The selected browser release can no longer be resolved.",
        )
        return CloudTransferIntentRepository.get(intent["transfer_id"]) or intent

    try:
        stream_payload = await ad_client.unlock_magnet_stream(
            magnet_link=target_mag,
            season=int(intent.get("season") or 0) or None,
        )
    except Exception as exc:
        CloudTransferIntentRepository.update_status(
            intent["transfer_id"],
            "verifying",
            error_message=f"Browser verification will retry: {exc}",
        )
        return CloudTransferIntentRepository.get(intent["transfer_id"]) or intent

    verification = await verify_stream_payload(stream_payload)
    actual_filename = verification.get("actual_filename") or ""
    if not verification.get("verified"):
        verification_message = verification.get("message") or "The selected file failed browser verification."
        CloudTransferIntentRepository.update_status(
            intent["transfer_id"],
            "verifying" if verification.get("retryable") else "failed",
            release_title=actual_filename or None,
            error_message=verification_message,
        )
        _record_cloud_event(
            "browser_stream_prepare_failed",
            intent["title"],
            "failed",
            "The completed AllDebrid release was not browser compatible.",
            {**intent, "verified_filename": actual_filename, "verification": verification},
        )
        return CloudTransferIntentRepository.get(intent["transfer_id"]) or intent

    _persist_verified_browser_candidate(
        intent,
        actual_filename,
        size_bytes=stream_payload.get("filesize") or size_bytes,
        verification=verification,
    )
    CloudTransferIntentRepository.update_status(
        intent["transfer_id"],
        "ready",
        ready=True,
        browser_stream_ready=True,
        release_title=actual_filename,
        error_message=None,
    )
    _record_cloud_event(
        "browser_stream_ready",
        intent["title"],
        "ready",
        "A manually requested browser stream is verified and ready.",
        {**intent, "verified_filename": actual_filename, "verification": verification},
    )
    return CloudTransferIntentRepository.get(intent["transfer_id"]) or intent


async def _sync_manual_cloud_transfers() -> List[Dict[str, Any]]:
    """Merge account-wide provider state with only locally owned manual intents."""
    from moviebot.adapters.alldebrid_client import AllDebridClient

    intents = CloudTransferIntentRepository.list_all(limit=200)
    if not intents:
        return []

    ad_client = AllDebridClient()
    provider_transfers = await ad_client.get_cloud_transfers()
    provider_by_id = {str(item.get("id")): item for item in provider_transfers}
    merged: List[Dict[str, Any]] = []

    for stored_intent in intents:
        provider = provider_by_id.get(str(stored_intent["transfer_id"]))
        intent = stored_intent
        if provider:
            provider_ready = bool(provider.get("ready"))
            if provider_ready and not intent.get("ready") and intent.get("status") != "failed":
                if intent.get("purpose") == "browser_stream":
                    intent = await _verify_browser_transfer(
                        intent,
                        ad_client,
                        size_bytes=int(provider.get("size") or 0),
                    )
                else:
                    _persist_generic_cached_intent(intent, size_bytes=int(provider.get("size") or 0))
                    CloudTransferIntentRepository.update_status(
                        intent["transfer_id"], "ready", ready=True
                    )
                    _record_cloud_event(
                        "cloud_transfer_ready",
                        intent["title"],
                        "ready",
                        "A manually requested AllDebrid cloud transfer completed.",
                        intent,
                    )
                    intent = CloudTransferIntentRepository.get(intent["transfer_id"]) or intent
            elif not provider_ready and intent.get("status") not in ("failed", "ready"):
                CloudTransferIntentRepository.update_status(
                    intent["transfer_id"],
                    (provider.get("status") or "downloading").lower(),
                )
                intent = CloudTransferIntentRepository.get(intent["transfer_id"]) or intent

        merged_item = {
            **(provider or {}),
            **intent,
            "id": intent["transfer_id"],
            "name": intent.get("release_title") or intent["title"],
            "ready": bool(intent.get("ready")),
            "intent_purpose": intent.get("purpose"),
        }
        if not provider:
            merged_item.setdefault("progress_percent", 100.0 if intent.get("ready") else 0.0)
            merged_item.setdefault("speed_formatted", "0 KB/s")
            merged_item.setdefault("eta_formatted", "Ready" if intent.get("ready") else "Waiting for provider status")
            merged_item.setdefault("size_formatted", "Unknown size")
        merged.append(merged_item)

    return merged


@router.post("/stream/prepare")
async def api_prepare_browser_stream(req: BrowserStreamPrepareRequest) -> Dict[str, Any]:
    """Find and, if necessary, cache an exact browser-compatible release."""
    from moviebot.adapters.alldebrid_client import AllDebridClient
    from moviebot.core.background_prewarmer import resolve_magnet_uri

    db_domain = "tv_classic" if req.domain in ("tv_classic", "classic_tv") else req.domain
    if db_domain == "movies":
        movie_eligibility = await _evaluate_movie_request(
            title=req.title,
            year=req.year,
        )
        if not movie_eligibility.get("eligible"):
            return _movie_quality_gate_response(
                movie_eligibility,
                title=req.title,
                domain=db_domain,
                year=req.year,
            )
    fresh_verified = CachePrewarmRepository.get(
        db_domain,
        req.title,
        season=req.season,
        year=req.year if db_domain == "movies" else None,
        max_age_hours=168,
    )
    release_label_verified = CachePrewarmRepository.get_verified_browser_candidate(
        db_domain,
        req.title,
        season=req.season,
        year=req.year if db_domain == "movies" else None,
        max_age_hours=168,
    )
    if release_label_verified:
        fresh_verified = release_label_verified
    if fresh_verified and fresh_verified.get("browser_stream_ready"):
        return {
            "ok": True,
            "dry_run": bool(req.dry_run),
            "status": "already_verified",
            "cached": True,
            "browser_stream_ready": True,
            "reused_evidence": True,
            "reference_id": fresh_verified.get("browser_stream_reference_id"),
            "release_title": fresh_verified.get("browser_stream_release_title"),
            "browser_stream_candidate": _stream_candidate_summary(fresh_verified, "browser"),
            "download_candidate": _stream_candidate_summary(fresh_verified, "download"),
        }
    search_res = await search_sources_tool(
        query=req.title,
        domain=db_domain,
        year=req.year if db_domain == "movies" else None,
        season=req.season or None,
        episode=req.episode or None,
        limit=50,
        check_cache=True,
        movie_eligibility=movie_eligibility if db_domain == "movies" else None,
    )
    if not search_res.get("ok"):
        return {
            "ok": False,
            "code": "BROWSER_STREAM_SEARCH_FAILED",
            "error": search_res.get("error", {}).get("message", "Browser stream search failed."),
        }

    search_candidates = search_res.get("data", {}).get("results", [])
    if db_domain == "movies":
        search_candidates, _ = filter_movie_releases(search_candidates, movie_eligibility)
    candidates = _browser_prepare_candidates(search_candidates, req, db_domain)
    if not candidates:
        return {
            "ok": False,
            "code": "NO_BROWSER_SAFE_RELEASE",
            "error": "No exact MP4 + H.264 + AAC/MP3 release was found. Use Search for unrestricted IDM/Plex acquisition.",
        }

    ad_client = AllDebridClient()
    cached_candidates = [item for item in candidates if item.get("cached")]
    verification_failures: List[Dict[str, Any]] = []
    for candidate in cached_candidates[:3]:
        target_mag = resolve_magnet_uri(candidate.get("reference_id", ""), domain=db_domain)
        if not target_mag.startswith("magnet:"):
            continue
        if req.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "status": "already_cached",
                "release_title": candidate.get("title"),
                "reference_id": candidate.get("reference_id"),
            }
        try:
            payload = await ad_client.unlock_magnet_stream(
                magnet_link=target_mag,
                season=req.season or None,
                episode=req.episode or None,
            )
        except Exception as exc:
            if getattr(exc, "code", None) == "PROBE_CLEANUP_FAILED":
                return {
                    "ok": False,
                    "code": "PROBE_CLEANUP_FAILED",
                    "retryable": True,
                    "severity": "error",
                    "error": str(exc),
                }
            continue
        verification = await verify_stream_payload(payload)
        actual_filename = verification.get("actual_filename") or ""
        if not verification.get("verified"):
            verification_failures.append({
                "reference_id": candidate.get("reference_id"),
                "code": verification.get("verification_code"),
            })
            continue
        intent = {
            "transfer_id": None,
            "purpose": "browser_stream",
            "domain": db_domain,
            "title": req.title,
            "year": req.year if db_domain == "movies" else None,
            "season": req.season,
            "reference_id": candidate["reference_id"],
            "release_title": candidate.get("title") or actual_filename,
        }
        _persist_verified_browser_candidate(
            intent,
            actual_filename,
            size_bytes=int(payload.get("filesize") or candidate.get("size_bytes") or 0),
            verification=verification,
        )
        _record_cloud_event(
            "browser_stream_ready",
            req.title,
            "ready",
            "An existing cached release was verified for browser streaming.",
            {**intent, "verified_filename": actual_filename, "verification": verification},
        )
        return {
            "ok": True,
            "status": "ready",
            "cached": True,
            "browser_stream_ready": True,
            "reference_id": candidate["reference_id"],
            "release_title": actual_filename,
        }

    # Do not enqueue an unknown-format release merely because it may be
    # probeable after caching. Manual preparation is allowed to create a
    # provider transfer only for an explicitly advertised safe release.
    uncached_candidates = [
        item for item in candidates
        if not item.get("cached") and is_browser_stream_compatible(item.get("title") or "")
    ]
    if not uncached_candidates:
        return {
            "ok": False,
            "code": "BROWSER_VERIFICATION_FAILED",
            "error": "The best three cached candidates failed actual-file browser verification.",
            "verification_failures": verification_failures,
        }

    selected = uncached_candidates[0]
    target_mag = resolve_magnet_uri(selected.get("reference_id", ""), domain=db_domain)
    if not target_mag.startswith("magnet:"):
        return {
            "ok": False,
            "code": "BROWSER_RELEASE_UNRESOLVABLE",
            "error": "The selected browser-compatible release could not be resolved.",
        }
    if req.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "status": "would_cache",
            "release_title": selected.get("title"),
            "reference_id": selected.get("reference_id"),
        }

    transfer = await ad_client.cache_to_cloud(target_mag)
    transfer_id = transfer.get("id")
    if transfer_id is None:
        return {"ok": False, "code": "TRANSFER_ID_MISSING", "error": "AllDebrid did not return a transfer ID."}

    initial_status = "verifying" if transfer.get("ready") else "queued"
    CloudTransferIntentRepository.upsert(
        transfer_id=str(transfer_id),
        purpose="browser_stream",
        domain=db_domain,
        title=req.title,
        year=req.year if db_domain == "movies" else None,
        season=req.season,
        reference_id=selected["reference_id"],
        release_title=selected.get("title") or req.title,
        status=initial_status,
    )
    intent = CloudTransferIntentRepository.get(str(transfer_id))
    _record_cloud_event(
        "browser_stream_prepare_requested",
        req.title,
        initial_status,
        "A browser-compatible release was manually requested in AllDebrid.",
        intent or {"transfer_id": str(transfer_id), "domain": db_domain},
    )

    if transfer.get("ready") and intent:
        intent = await _verify_browser_transfer(
            intent, ad_client, size_bytes=int(transfer.get("size") or 0)
        )

    verified_candidate = CachePrewarmRepository.get_verified_browser_candidate(
        db_domain,
        req.title,
        season=req.season,
        year=req.year if db_domain == "movies" else None,
        max_age_hours=168,
    )
    return {
        "ok": True,
        "status": (intent or {}).get("status", initial_status),
        "cached": bool((intent or {}).get("ready")),
        "browser_stream_ready": bool((intent or {}).get("browser_stream_ready")),
        "transfer_id": str(transfer_id),
        "reference_id": selected["reference_id"],
        "release_title": (intent or {}).get("release_title") or selected.get("title"),
        "browser_stream_candidate": _stream_candidate_summary(verified_candidate, "browser"),
    }


@router.post("/cloud/pre-cache")
async def api_cloud_precache(req: CloudPreCacheRequest) -> Dict[str, Any]:
    """
    Enqueues an uncached P2P release to AllDebrid cloud downloader.
    Once finished, the release is ready for instant AllDebrid downloading;
    browser playback is a separate, verified capability.
    """
    from moviebot.adapters.alldebrid_client import AllDebridClient
    from moviebot.core.background_prewarmer import resolve_magnet_uri
    from moviebot.db.cache_prewarm_repo import CachePrewarmRepository

    db_domain = "tv_classic" if req.domain in ("tv_classic", "classic_tv") else req.domain
    if db_domain == "movies":
        movie_eligibility = await _evaluate_movie_request(
            title=req.title,
            year=req.year,
        )
        if not movie_eligibility.get("eligible"):
            return _movie_quality_gate_response(
                movie_eligibility,
                title=req.title,
                domain=db_domain,
                year=req.year,
            )
        if req.reference_id:
            referenced = SearchResultRepository.get_by_id(req.reference_id, domain=db_domain)
            if referenced:
                referenced_decision = assess_movie_release(
                    {"title": referenced.get("title") or req.title},
                    movie_eligibility,
                )
                if not referenced_decision.get("eligible"):
                    return _movie_quality_gate_response(
                        referenced_decision,
                        title=req.title,
                        domain=db_domain,
                        year=req.year,
                    )

    target_mag = req.magnet_url or ""
    if not target_mag and req.reference_id:
        target_mag = resolve_magnet_uri(req.reference_id, domain=db_domain)

    if not target_mag or not target_mag.startswith("magnet:"):
        return {"ok": False, "error": "No valid magnet URI found to send to cloud."}

    if req.dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "message": f"Would enqueue '{req.title}' to AllDebrid Cloud Downloader",
        }

    try:
        ad_client = AllDebridClient()
        transfer = await ad_client.cache_to_cloud(target_mag)
        transfer_id = transfer.get("id")
        if transfer_id is None:
            return {"ok": False, "error": "AllDebrid did not return a transfer ID."}
        CloudTransferIntentRepository.upsert(
            transfer_id=str(transfer_id),
            purpose="generic_cloud_cache",
            domain=db_domain,
            title=req.title,
            season=req.season,
            year=req.year if db_domain == "movies" else None,
            reference_id=req.reference_id or target_mag,
            release_title=transfer.get("name") or req.title,
            status="ready" if transfer.get("ready") else "queued",
            ready=bool(transfer.get("ready")),
        )
        intent = CloudTransferIntentRepository.get(str(transfer_id))
        if transfer.get("ready") and intent:
            _persist_generic_cached_intent(intent, size_bytes=int(transfer.get("size") or 0))
        _record_cloud_event(
            "cloud_transfer_requested",
            req.title,
            (intent or {}).get("status", "queued"),
            "A generic AllDebrid cloud transfer was manually requested.",
            intent or {"transfer_id": str(transfer_id), "domain": db_domain},
        )

        return {
            "ok": True,
            "message": f"☁️ Enqueued '{req.title}' to AllDebrid Cloud Downloader",
            "transfer": transfer
        }
    except Exception as e:
        logger.error("[Cloud Pre-Cache] Failed to send magnet to cloud: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


@router.get("/cloud/transfers")
async def api_get_cloud_transfers() -> Dict[str, Any]:
    """
    Retrieves manually requested Media Bot cloud downloads, merged with their
    AllDebrid progress, speed, and ETA.
    """
    try:
        transfers = await _sync_manual_cloud_transfers()
        active_transfers = [t for t in transfers if not t.get("ready")]
        ready_transfers = [t for t in transfers if t.get("ready")]
        return {
            "ok": True,
            "transfers": transfers,
            "active_count": len(active_transfers),
            "ready_count": len(ready_transfers)
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "transfers": [], "active_count": 0, "ready_count": 0}


@router.delete("/cloud/transfers/{transfer_id}")
async def api_delete_cloud_transfer(transfer_id: str) -> Dict[str, Any]:
    """
    Cancels and deletes an active or completed cloud download from AllDebrid queue.
    """
    from moviebot.adapters.alldebrid_client import AllDebridClient

    try:
        intent = CloudTransferIntentRepository.get(transfer_id)
        if not intent:
            return {"ok": False, "error": "Manual cloud transfer not found."}
        ad_client = AllDebridClient()
        deleted = await ad_client.delete_cloud_transfer(transfer_id)
        if deleted:
            CloudTransferIntentRepository.delete(transfer_id)
        return {"ok": deleted}
    except Exception as e:
        logger.error("[Cloud Transfer Delete] Failed to delete transfer %s: %s", transfer_id, e)
        return {"ok": False, "error": str(e)}


@router.get("/cloud/notifications")
async def api_get_cloud_notifications() -> Dict[str, Any]:
    """
    Retrieves completed manually requested cloud operations. Each item states
    independently whether browser streaming was verified.
    """
    try:
        transfers = await _sync_manual_cloud_transfers()
        ready_items = [t for t in transfers if t.get("ready")]
        return {
            "ok": True,
            "notifications": ready_items,
            "unread_count": len(ready_items)
        }
    except Exception as e:
        return {"ok": False, "error": str(e), "notifications": [], "unread_count": 0}




