import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from moviebot.db.release_variant_repo import ReleaseVariantRepository


DEFAULT_EVIDENCE_MAX_AGE_HOURS = 168

AVAILABILITY_TIERS = {
    "unknown": "unknown",
    "not_cached": "A",
    "ad_cached": "B",
    "direct_play_ready": "C",
}


def _canonical_domain(domain: str) -> str:
    value = (domain or "movies").strip().lower()
    if value in {"classic_tv", "classictv"}:
        return "tv_classic"
    return value


def _scope_type(
    domain: str,
    *,
    season: int = 0,
    episode: int = 0,
    scope_type: Optional[str] = None,
) -> str:
    if domain == "movies":
        return "movie"
    if scope_type:
        return scope_type
    if episode:
        return "episode"
    if season:
        return "season_pack"
    return "series"


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _is_fresh(value: Optional[str], max_age_hours: int) -> bool:
    if not value:
        return False
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age_hours = (datetime.now(timezone.utc) - timestamp).total_seconds() / 3600
    except (TypeError, ValueError):
        return False
    return 0 <= age_hours <= max_age_hours


def _public_variant(row: Dict[str, Any], max_age_hours: int) -> Dict[str, Any]:
    cache_checked_at = row.get("last_cache_checked_at") or row.get("ad_checked_at")
    cache_fresh = _is_fresh(cache_checked_at, max_age_hours)
    direct_evidence: Dict[str, Any] = {}
    try:
        parsed_evidence = json.loads(row.get("direct_play_evidence_json") or "{}")
        if isinstance(parsed_evidence, dict):
            direct_evidence = parsed_evidence
    except (TypeError, ValueError, json.JSONDecodeError):
        pass
    authoritative_direct_marker = bool(
        direct_evidence.get("status") == "verified_browser_ready"
        or (
            direct_evidence.get("verified") is True
            and direct_evidence.get("verification_code")
            in {"BROWSER_FILENAME_VERIFIED", "BROWSER_CODEC_VERIFIED"}
        )
    )
    direct_fresh = bool(
        authoritative_direct_marker
        and _is_fresh(row.get("direct_play_verified_at"), max_age_hours)
    )
    cache_status = row.get("ad_cache_status") or "unknown"
    direct_ready = bool(
        cache_status == "cached"
        and cache_fresh
        and row.get("direct_play_status") == "verified"
        and direct_fresh
    )
    if direct_ready:
        availability_state = "direct_play_ready"
    elif cache_status == "cached" and cache_fresh:
        availability_state = "ad_cached"
    elif cache_status == "not_cached" and cache_fresh:
        availability_state = "not_cached"
    else:
        availability_state = "unknown"
    cloud_cached = availability_state in {"ad_cached", "direct_play_ready"}
    return {
        "variant_id": row.get("variant_id"),
        "release_title": row.get("release_title"),
        "resolution": row.get("resolution"),
        "source_type": row.get("source_type"),
        "container": row.get("container"),
        "video_codec": row.get("video_codec"),
        "audio_codec": row.get("audio_codec"),
        "hdr": row.get("hdr"),
        "channels": row.get("channels"),
        "subtitle_summary": row.get("subtitle_summary"),
        "size_bytes": row.get("size_bytes"),
        "formatted_size": row.get("formatted_size"),
        "seeders": row.get("seeders"),
        "indexer": row.get("indexer"),
        "source_vector": row.get("source_vector"),
        "availability_state": availability_state,
        "availability_tier": AVAILABILITY_TIERS[availability_state],
        "cached": cloud_cached,
        "cloud_cached": cloud_cached,
        "instant_download_ready": cloud_cached,
        "instant_cached": direct_ready,
        "browser_stream_ready": direct_ready,
        "external_stream_ready": cloud_cached and not direct_ready,
        "instant_stream_status": (
            "browser_ready"
            if direct_ready
            else (
                "external_ready"
                if cloud_cached
                else ("not_cached" if availability_state == "not_cached" else "unknown")
            )
        ),
        "ad_cache": {
            "status": cache_status,
            "checked_at": row.get("ad_checked_at"),
            "last_cache_checked_at": row.get("last_cache_checked_at"),
            "fresh": cache_fresh,
            "error_code": row.get("ad_error_code"),
        },
        "direct_play": {
            "status": row.get("direct_play_status") or "unknown",
            "verified_at": row.get("direct_play_verified_at"),
            "fresh": direct_fresh,
            "error_code": row.get("direct_play_error_code"),
        },
        "mediaflow": {
            "status": row.get("mediaflow_status") or "untested",
            "checked_at": row.get("mediaflow_checked_at"),
            "error_code": row.get("mediaflow_error_code"),
        },
        "first_seen_at": row.get("first_seen_at"),
        "last_seen_at": row.get("last_seen_at"),
        "last_observed_cycle_id": row.get("last_observed_cycle_id"),
    }


class AvailabilityService:
    @staticmethod
    def unknown_projection(
        *,
        domain: str,
        title: str,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        season: int = 0,
        episode: int = 0,
        scope_type: Optional[str] = None,
        error_code: Optional[str] = None,
        max_age_hours: int = DEFAULT_EVIDENCE_MAX_AGE_HOURS,
    ) -> Dict[str, Any]:
        canonical_domain = _canonical_domain(domain)
        selected_scope = _scope_type(
            canonical_domain,
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        coverage = {
            "status": "not_checked",
            "candidate_count": 0,
            "checked_count": 0,
            "cached_count": 0,
            "unknown_count": 0,
            "checked_at": None,
            "fresh": False,
            "cycle_id": None,
            "error_code": error_code,
        }
        return {
            "projection_version": 1,
            "media": {
                "media_key": None,
                "domain": canonical_domain,
                "title": (title or "").strip(),
                "year": _safe_int(year),
                "tmdb_id": _safe_int(tmdb_id),
                "season": int(season or 0),
                "episode": int(episode or 0),
                "scope_type": selected_scope,
            },
            "availability_state": "unknown",
            "availability_tier": "unknown",
            "coverage": coverage,
            "freshness": {
                "max_age_hours": max_age_hours,
                "coverage_fresh": False,
                "checked_at": None,
            },
            "variant_count": 0,
            "cached_variant_count": 0,
            "direct_play_variant_count": 0,
            "recommended_variant": None,
            "cached_variants": [],
            "variants": [],
            "cached": False,
            "cloud_cached": False,
            "instant_download_ready": False,
            "instant_cached": False,
            "browser_stream_ready": False,
            "external_stream_ready": False,
            "instant_stream_status": "unknown",
        }

    @staticmethod
    def project(
        *,
        domain: str,
        title: str,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        season: int = 0,
        episode: int = 0,
        scope_type: Optional[str] = None,
        limit: int = 25,
        max_age_hours: int = DEFAULT_EVIDENCE_MAX_AGE_HOURS,
    ) -> Dict[str, Any]:
        """Return a fail-closed public projection for feed and tool consumers."""
        safe_tmdb_id = _safe_int(tmdb_id)
        try:
            return AvailabilityService.inspect(
                domain=domain,
                title=title,
                year=year,
                tmdb_id=safe_tmdb_id,
                season=season,
                episode=episode,
                scope_type=scope_type,
                limit=limit,
                max_age_hours=max_age_hours,
            )
        except (TypeError, ValueError):
            return AvailabilityService.unknown_projection(
                domain=domain,
                title=title,
                year=year,
                tmdb_id=safe_tmdb_id,
                season=season,
                episode=episode,
                scope_type=scope_type,
                error_code="CATALOG_IDENTITY_UNAVAILABLE",
                max_age_hours=max_age_hours,
            )

    @staticmethod
    def inspect(
        *,
        domain: str,
        title: str,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        season: int = 0,
        episode: int = 0,
        scope_type: Optional[str] = None,
        limit: int = 100,
        max_age_hours: int = DEFAULT_EVIDENCE_MAX_AGE_HOURS,
    ) -> Dict[str, Any]:
        identity = ReleaseVariantRepository.media_identity(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        rows = ReleaseVariantRepository.list_variants(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
            limit=limit,
        )
        latest_check = ReleaseVariantRepository.latest_scope_check(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        variants = [_public_variant(row, max_age_hours) for row in rows]

        cached_variants: List[Dict[str, Any]] = []
        direct_variants: List[Dict[str, Any]] = []
        for variant in variants:
            cache = variant["ad_cache"]
            direct = variant["direct_play"]
            if cache["status"] == "cached" and cache["fresh"]:
                cached_variants.append(variant)
                if direct["status"] == "verified" and direct["fresh"]:
                    direct_variants.append(variant)

        check_fresh = bool(
            latest_check
            and _is_fresh(latest_check.get("checked_at"), max_age_hours)
        )
        complete_zero_cached = bool(
            latest_check
            and check_fresh
            and latest_check.get("status") == "complete"
            and int(latest_check.get("checked_count") or 0)
            == int(latest_check.get("candidate_count") or 0)
            and int(latest_check.get("cached_count") or 0) == 0
            and int(latest_check.get("unknown_count") or 0) == 0
        )

        if direct_variants:
            availability_state = "direct_play_ready"
        elif cached_variants:
            availability_state = "ad_cached"
        elif complete_zero_cached:
            availability_state = "not_cached"
        else:
            availability_state = "unknown"

        browser_ready = availability_state == "direct_play_ready"
        cloud_cached = availability_state in {"ad_cached", "direct_play_ready"}
        coverage = {
            "status": latest_check.get("status") if latest_check else "not_checked",
            "candidate_count": int(latest_check.get("candidate_count") or 0) if latest_check else 0,
            "checked_count": int(latest_check.get("checked_count") or 0) if latest_check else 0,
            "cached_count": int(latest_check.get("cached_count") or 0) if latest_check else 0,
            "unknown_count": int(latest_check.get("unknown_count") or 0) if latest_check else 0,
            "checked_at": latest_check.get("checked_at") if latest_check else None,
            "fresh": check_fresh,
            "cycle_id": latest_check.get("cycle_id") if latest_check else None,
            "error_code": latest_check.get("error_code") if latest_check else None,
        }
        recommended = direct_variants[0] if direct_variants else (
            cached_variants[0] if cached_variants else (variants[0] if variants else None)
        )
        return {
            "projection_version": 1,
            "media": {
                "media_key": identity["media_key"],
                "domain": identity["domain"],
                "title": identity["title"],
                "year": identity["year"],
                "tmdb_id": identity["tmdb_id"],
                "season": identity["season"],
                "episode": identity["episode"],
                "scope_type": identity["scope_type"],
            },
            "availability_state": availability_state,
            "availability_tier": AVAILABILITY_TIERS[availability_state],
            "coverage": coverage,
            "freshness": {
                "max_age_hours": max_age_hours,
                "coverage_fresh": check_fresh,
                "checked_at": coverage["checked_at"],
            },
            "variant_count": len(variants),
            "cached_variant_count": len(cached_variants),
            "direct_play_variant_count": len(direct_variants),
            "recommended_variant": recommended,
            "cached_variants": cached_variants,
            "variants": variants,
            # Additive compatibility projection. MediaFlow status never changes
            # these aliases and direct-play C remains the only browser-ready state.
            "cached": cloud_cached,
            "cloud_cached": cloud_cached,
            "instant_download_ready": cloud_cached,
            "instant_cached": browser_ready,
            "browser_stream_ready": browser_ready,
            "external_stream_ready": cloud_cached and not browser_ready,
            "instant_stream_status": (
                "browser_ready"
                if browser_ready
                else (
                    "external_ready"
                    if cloud_cached
                    else ("not_cached" if availability_state == "not_cached" else "unknown")
                )
            ),
        }
