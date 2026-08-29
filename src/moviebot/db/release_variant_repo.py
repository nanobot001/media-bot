import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from moviebot.core.dedupe import normalize_title
from moviebot.core.release_parser import (
    extract_year_from_title,
    format_size_bytes,
    is_exact_media_identity,
    parse_release_details,
)
from moviebot.db.connection import get_db_connection


CATALOG_DOMAINS = {"movies", "tv", "tv_classic"}
SCOPE_TYPES = {"movie", "series", "season_pack", "episode", "complete_series"}
AD_CACHE_STATUSES = {"unknown", "cached", "not_cached", "provider_error", "unresolvable"}
DIRECT_PLAY_STATUSES = {"unknown", "verified", "failed"}
MEDIAFLOW_STATUSES = {"untested", "candidate", "verified", "failed"}
CHECK_STATUSES = {"complete", "partial", "provider_error"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_domain(domain: str) -> str:
    value = (domain or "movies").strip().lower()
    if value == "classic_tv":
        value = "tv_classic"
    if value not in CATALOG_DOMAINS:
        raise ValueError(f"Unsupported release catalog domain: {domain!r}")
    return value


def _container_from_title(release_title: str) -> Optional[str]:
    match = re.search(
        r"\.(mp4|m4v|mkv|webm|avi|mov|ts|flv|wmv)(?:$|[?#])",
        release_title or "",
        re.IGNORECASE,
    )
    return match.group(1).lower() if match else None


def _safe_evidence(evidence: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(evidence, dict):
        return None
    allowed = {
        "status",
        "verified",
        "verification_code",
        "evidence_source",
        "actual_filename",
        "container",
        "video_codec",
        "audio_codec",
        "audio_track_present",
        "duration_seconds",
    }
    sanitized = {key: evidence[key] for key in allowed if key in evidence}
    probe = evidence.get("probe")
    if isinstance(probe, dict):
        format_info = probe.get("format")
        streams = probe.get("streams")
        safe_probe: Dict[str, Any] = {}
        if isinstance(format_info, dict):
            safe_probe["format"] = {
                key: format_info.get(key)
                for key in ("format_name", "duration", "size")
                if format_info.get(key) is not None
            }
        if isinstance(streams, list):
            safe_probe["streams"] = [
                {
                    key: stream.get(key)
                    for key in ("codec_type", "codec_name", "profile", "pix_fmt", "channels")
                    if stream.get(key) is not None
                }
                for stream in streams
                if isinstance(stream, dict)
            ]
        if safe_probe:
            sanitized["probe"] = safe_probe
    return sanitized or None


class ReleaseVariantRepository:
    """Durable exact-release catalog stored in the primary Movies database."""

    @staticmethod
    def media_identity(
        *,
        domain: str,
        title: str,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        imdb_id: Optional[str] = None,
        tvdb_id: Optional[str] = None,
        season: int = 0,
        episode: int = 0,
        scope_type: Optional[str] = None,
        release_title: str = "",
    ) -> Dict[str, Any]:
        canonical_domain = _canonical_domain(domain)
        normalized = normalize_title(title)
        if not normalized:
            raise ValueError("An exact media title is required")
        if canonical_domain == "movies":
            if year is None:
                raise ValueError("Movie catalog identity requires an exact year")
            selected_scope = "movie"
            season = 0
            episode = 0
        else:
            if episode and not season:
                raise ValueError("TV episode identity requires a season")
            parsed = parse_release_details(release_title or "")
            selected_scope = scope_type
            if not selected_scope:
                if episode:
                    selected_scope = "episode"
                elif parsed.get("is_complete_series"):
                    selected_scope = "complete_series"
                elif season:
                    selected_scope = "season_pack"
                else:
                    selected_scope = "series"
        if selected_scope not in SCOPE_TYPES:
            raise ValueError(f"Unsupported release catalog scope: {selected_scope!r}")
        if canonical_domain == "movies" and selected_scope != "movie":
            raise ValueError("Movie catalog entries must use movie scope")
        if canonical_domain != "movies" and selected_scope == "movie":
            raise ValueError("TV catalog entries cannot use movie scope")

        identity_text = "|".join(
            [
                canonical_domain,
                normalized,
                str(year or 0),
                selected_scope,
                str(int(season or 0)),
                str(int(episode or 0)),
            ]
        )
        media_key = hashlib.sha256(identity_text.encode("utf-8")).hexdigest()
        return {
            "media_key": media_key,
            "domain": canonical_domain,
            "title": title.strip(),
            "normalized_title": normalized,
            "year": int(year) if year is not None else None,
            "tmdb_id": int(tmdb_id) if tmdb_id is not None else None,
            "imdb_id": imdb_id,
            "tvdb_id": tvdb_id,
            "season": int(season or 0),
            "episode": int(episode or 0),
            "scope_type": selected_scope,
        }

    @staticmethod
    def _release_identity(
        *,
        domain: str,
        reference_id: Optional[str],
        release_title: str,
        size_bytes: Optional[int],
        indexer: Optional[str],
    ) -> str:
        reference = (reference_id or "").strip()
        btih = re.search(r"btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})", reference, re.IGNORECASE)
        if btih:
            return hashlib.sha256(f"btih:{btih.group(1).lower()}".encode("utf-8")).hexdigest()

        if reference:
            try:
                with get_db_connection(_canonical_domain(domain)) as conn:
                    row = conn.execute(
                        "SELECT magnet_uri_hash, raw_json_payload FROM search_results WHERE id = ?",
                        (reference,),
                    ).fetchone()
                if row and row["magnet_uri_hash"]:
                    return str(row["magnet_uri_hash"])
                if row and row["raw_json_payload"]:
                    payload = json.loads(row["raw_json_payload"])
                    info_hash = str(payload.get("infoHash") or "").strip().lower()
                    if info_hash:
                        return hashlib.sha256(f"btih:{info_hash}".encode("utf-8")).hexdigest()
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                pass

        fallback = "|".join(
            [
                normalize_title(release_title),
                str(int(size_bytes or 0)),
                (indexer or "").strip().lower(),
            ]
        )
        return hashlib.sha256(fallback.encode("utf-8")).hexdigest()

    @staticmethod
    def upsert_variant(
        *,
        domain: str,
        title: str,
        release_title: str,
        reference_id: Optional[str] = None,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        imdb_id: Optional[str] = None,
        tvdb_id: Optional[str] = None,
        season: int = 0,
        episode: int = 0,
        scope_type: Optional[str] = None,
        resolution: Optional[str] = None,
        source_type: Optional[str] = None,
        container: Optional[str] = None,
        video_codec: Optional[str] = None,
        audio_codec: Optional[str] = None,
        hdr: Optional[str] = None,
        channels: Optional[str] = None,
        subtitle_summary: Optional[str] = None,
        size_bytes: Optional[int] = None,
        formatted_size: Optional[str] = None,
        seeders: Optional[int] = None,
        indexer: Optional[str] = None,
        source_vector: Optional[str] = None,
        ad_cache_status: Optional[str] = None,
        ad_checked_at: Optional[str] = None,
        ad_error_code: Optional[str] = None,
        ad_error_message: Optional[str] = None,
        direct_play_status: Optional[str] = None,
        direct_play_verified_at: Optional[str] = None,
        direct_play_error_code: Optional[str] = None,
        direct_play_error_message: Optional[str] = None,
        direct_play_evidence: Optional[Dict[str, Any]] = None,
        mediaflow_status: Optional[str] = None,
        mediaflow_checked_at: Optional[str] = None,
        mediaflow_error_code: Optional[str] = None,
        mediaflow_error_message: Optional[str] = None,
        first_seen_at: Optional[str] = None,
        observed_at: Optional[str] = None,
        last_cache_checked_at: Optional[str] = None,
        last_observed_cycle_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        if not release_title or not release_title.strip():
            raise ValueError("A release title is required")
        if ad_cache_status is not None and ad_cache_status not in AD_CACHE_STATUSES:
            raise ValueError(f"Unsupported AD cache status: {ad_cache_status!r}")
        if direct_play_status is not None and direct_play_status not in DIRECT_PLAY_STATUSES:
            raise ValueError(f"Unsupported direct-play status: {direct_play_status!r}")
        if mediaflow_status is not None and mediaflow_status not in MEDIAFLOW_STATUSES:
            raise ValueError(f"Unsupported MediaFlow status: {mediaflow_status!r}")

        identity = ReleaseVariantRepository.media_identity(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
            release_title=release_title,
        )
        parsed = parse_release_details(release_title)
        metadata = data if isinstance(data, dict) else {}
        selected_indexer = indexer or metadata.get("indexer")
        release_identity = ReleaseVariantRepository._release_identity(
            domain=identity["domain"],
            reference_id=reference_id,
            release_title=release_title,
            size_bytes=size_bytes,
            indexer=selected_indexer,
        )
        variant_id = hashlib.sha256(
            f"{identity['media_key']}|{release_identity}".encode("utf-8")
        ).hexdigest()
        now = _utc_now()
        last_seen = observed_at or now
        first_seen = first_seen_at or last_seen
        safe_direct_evidence = _safe_evidence(direct_play_evidence)
        if direct_play_status == "verified":
            verified_marker = bool(
                safe_direct_evidence
                and (
                    safe_direct_evidence.get("status") == "verified_browser_ready"
                    or (
                        safe_direct_evidence.get("verified") is True
                        and safe_direct_evidence.get("verification_code")
                        in {"BROWSER_FILENAME_VERIFIED", "BROWSER_CODEC_VERIFIED"}
                    )
                )
            )
            if not direct_play_verified_at or not verified_marker:
                raise ValueError(
                    "Verified direct play requires a timestamp and authoritative browser evidence"
                )
        subtitle_value = subtitle_summary or metadata.get("subtitle_summary")
        if subtitle_value is not None and not isinstance(subtitle_value, str):
            subtitle_value = json.dumps(subtitle_value, sort_keys=True)
        ad_value = ad_cache_status or "unknown"
        direct_value = direct_play_status or "unknown"
        mediaflow_value = mediaflow_status or "untested"
        ad_provided = int(ad_cache_status is not None)
        direct_provided = int(direct_play_status is not None)
        mediaflow_provided = int(mediaflow_status is not None)
        effective_cache_checked = last_cache_checked_at or ad_checked_at

        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO release_variants (
                    variant_id, media_key, domain, title, normalized_title, year,
                    tmdb_id, imdb_id, tvdb_id, season, episode, scope_type,
                    release_identity, reference_id, release_title, resolution,
                    source_type, container, video_codec, audio_codec, hdr, channels,
                    subtitle_summary, size_bytes, formatted_size, seeders, indexer,
                    source_vector, ad_cache_status, ad_checked_at, ad_error_code,
                    ad_error_message, direct_play_status, direct_play_verified_at,
                    direct_play_error_code, direct_play_error_message,
                    direct_play_evidence_json, mediaflow_status, mediaflow_checked_at,
                    mediaflow_error_code, mediaflow_error_message, first_seen_at,
                    last_seen_at, last_cache_checked_at, last_observed_cycle_id,
                    created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(variant_id) DO UPDATE SET
                    title=excluded.title,
                    tmdb_id=COALESCE(release_variants.tmdb_id, excluded.tmdb_id),
                    imdb_id=COALESCE(release_variants.imdb_id, excluded.imdb_id),
                    tvdb_id=COALESCE(release_variants.tvdb_id, excluded.tvdb_id),
                    reference_id=COALESCE(excluded.reference_id, release_variants.reference_id),
                    release_title=excluded.release_title,
                    resolution=COALESCE(excluded.resolution, release_variants.resolution),
                    source_type=COALESCE(excluded.source_type, release_variants.source_type),
                    container=COALESCE(excluded.container, release_variants.container),
                    video_codec=COALESCE(excluded.video_codec, release_variants.video_codec),
                    audio_codec=COALESCE(excluded.audio_codec, release_variants.audio_codec),
                    hdr=COALESCE(excluded.hdr, release_variants.hdr),
                    channels=COALESCE(excluded.channels, release_variants.channels),
                    subtitle_summary=COALESCE(excluded.subtitle_summary, release_variants.subtitle_summary),
                    size_bytes=COALESCE(excluded.size_bytes, release_variants.size_bytes),
                    formatted_size=COALESCE(excluded.formatted_size, release_variants.formatted_size),
                    seeders=COALESCE(excluded.seeders, release_variants.seeders),
                    indexer=COALESCE(excluded.indexer, release_variants.indexer),
                    source_vector=COALESCE(excluded.source_vector, release_variants.source_vector),
                    ad_cache_status=CASE WHEN ? = 1 THEN excluded.ad_cache_status ELSE release_variants.ad_cache_status END,
                    ad_checked_at=CASE WHEN ? = 1 THEN excluded.ad_checked_at ELSE release_variants.ad_checked_at END,
                    ad_error_code=CASE WHEN ? = 1 THEN excluded.ad_error_code ELSE release_variants.ad_error_code END,
                    ad_error_message=CASE WHEN ? = 1 THEN excluded.ad_error_message ELSE release_variants.ad_error_message END,
                    direct_play_status=CASE WHEN ? = 1 THEN excluded.direct_play_status ELSE release_variants.direct_play_status END,
                    direct_play_verified_at=CASE WHEN ? = 1 THEN excluded.direct_play_verified_at ELSE release_variants.direct_play_verified_at END,
                    direct_play_error_code=CASE WHEN ? = 1 THEN excluded.direct_play_error_code ELSE release_variants.direct_play_error_code END,
                    direct_play_error_message=CASE WHEN ? = 1 THEN excluded.direct_play_error_message ELSE release_variants.direct_play_error_message END,
                    direct_play_evidence_json=CASE WHEN ? = 1 THEN excluded.direct_play_evidence_json ELSE release_variants.direct_play_evidence_json END,
                    mediaflow_status=CASE WHEN ? = 1 THEN excluded.mediaflow_status ELSE release_variants.mediaflow_status END,
                    mediaflow_checked_at=CASE WHEN ? = 1 THEN excluded.mediaflow_checked_at ELSE release_variants.mediaflow_checked_at END,
                    mediaflow_error_code=CASE WHEN ? = 1 THEN excluded.mediaflow_error_code ELSE release_variants.mediaflow_error_code END,
                    mediaflow_error_message=CASE WHEN ? = 1 THEN excluded.mediaflow_error_message ELSE release_variants.mediaflow_error_message END,
                    last_seen_at=CASE
                        WHEN excluded.last_seen_at > release_variants.last_seen_at
                        THEN excluded.last_seen_at
                        ELSE release_variants.last_seen_at
                    END,
                    last_cache_checked_at=COALESCE(excluded.last_cache_checked_at, release_variants.last_cache_checked_at),
                    last_observed_cycle_id=COALESCE(excluded.last_observed_cycle_id, release_variants.last_observed_cycle_id),
                    updated_at=excluded.updated_at
                """,
                (
                    variant_id,
                    identity["media_key"],
                    identity["domain"],
                    identity["title"],
                    identity["normalized_title"],
                    identity["year"],
                    identity["tmdb_id"],
                    identity["imdb_id"],
                    identity["tvdb_id"],
                    identity["season"],
                    identity["episode"],
                    identity["scope_type"],
                    release_identity,
                    reference_id,
                    release_title.strip(),
                    resolution or parsed.get("resolution"),
                    source_type or parsed.get("source_type"),
                    container or _container_from_title(release_title),
                    video_codec or parsed.get("codec"),
                    audio_codec or parsed.get("audio"),
                    hdr or parsed.get("hdr"),
                    channels or parsed.get("channels"),
                    subtitle_value,
                    size_bytes,
                    formatted_size or (format_size_bytes(size_bytes) if size_bytes else None),
                    seeders,
                    selected_indexer,
                    source_vector or metadata.get("vector_origin"),
                    ad_value,
                    ad_checked_at,
                    ad_error_code,
                    ad_error_message,
                    direct_value,
                    direct_play_verified_at,
                    direct_play_error_code,
                    direct_play_error_message,
                    json.dumps(safe_direct_evidence, sort_keys=True) if safe_direct_evidence else None,
                    mediaflow_value,
                    mediaflow_checked_at,
                    mediaflow_error_code,
                    mediaflow_error_message,
                    first_seen,
                    last_seen,
                    effective_cache_checked,
                    last_observed_cycle_id,
                    now,
                    now,
                    ad_provided,
                    ad_provided,
                    ad_provided,
                    ad_provided,
                    direct_provided,
                    direct_provided,
                    direct_provided,
                    direct_provided,
                    direct_provided,
                    mediaflow_provided,
                    mediaflow_provided,
                    mediaflow_provided,
                    mediaflow_provided,
                ),
            )
            row = conn.execute(
                "SELECT * FROM release_variants WHERE variant_id = ?",
                (variant_id,),
            ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def list_variants(
        *,
        domain: str,
        title: str,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        season: int = 0,
        episode: int = 0,
        scope_type: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        identity = ReleaseVariantRepository.media_identity(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        bounded_limit = max(1, min(int(limit), 100))
        conditions = ["media_key = ?"]
        params: List[Any] = [identity["media_key"]]
        if tmdb_id is not None:
            conditions.append("(tmdb_id IS NULL OR tmdb_id = ?)")
            params.append(int(tmdb_id))
        params.append(bounded_limit)
        with get_db_connection() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM release_variants
                WHERE {' AND '.join(conditions)}
                ORDER BY last_seen_at DESC, variant_id
                LIMIT ?
                """,
                tuple(params),
            ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def record_scope_check(
        *,
        domain: str,
        title: str,
        status: str,
        candidate_count: int,
        checked_count: int,
        cached_count: int,
        unknown_count: int = 0,
        checked_at: Optional[str] = None,
        check_id: Optional[str] = None,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        season: int = 0,
        episode: int = 0,
        scope_type: Optional[str] = None,
        cycle_id: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> Dict[str, Any]:
        if status not in CHECK_STATUSES:
            raise ValueError(f"Unsupported catalog check status: {status!r}")
        counts = [candidate_count, checked_count, cached_count, unknown_count]
        if any(int(value) < 0 for value in counts):
            raise ValueError("Catalog check counts cannot be negative")
        if checked_count > candidate_count or cached_count > checked_count:
            raise ValueError("Catalog check coverage counts are inconsistent")
        if status == "complete" and (checked_count != candidate_count or unknown_count != 0):
            raise ValueError("A complete catalog check requires full coverage and zero unknown results")

        identity = ReleaseVariantRepository.media_identity(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        now = _utc_now()
        selected_check_id = check_id or uuid.uuid4().hex
        selected_checked_at = checked_at or now
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO release_catalog_checks (
                    check_id, media_key, domain, title, normalized_title, year,
                    tmdb_id, season, episode, scope_type, status, candidate_count,
                    checked_count, cached_count, unknown_count, checked_at, cycle_id,
                    error_code, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selected_check_id,
                    identity["media_key"],
                    identity["domain"],
                    identity["title"],
                    identity["normalized_title"],
                    identity["year"],
                    identity["tmdb_id"],
                    identity["season"],
                    identity["episode"],
                    identity["scope_type"],
                    status,
                    int(candidate_count),
                    int(checked_count),
                    int(cached_count),
                    int(unknown_count),
                    selected_checked_at,
                    cycle_id,
                    error_code,
                    error_message,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM release_catalog_checks WHERE check_id = ?",
                (selected_check_id,),
            ).fetchone()
        return dict(row) if row else {}

    @staticmethod
    def latest_scope_check(
        *,
        domain: str,
        title: str,
        year: Optional[int] = None,
        tmdb_id: Optional[int] = None,
        season: int = 0,
        episode: int = 0,
        scope_type: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        identity = ReleaseVariantRepository.media_identity(
            domain=domain,
            title=title,
            year=year,
            tmdb_id=tmdb_id,
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        with get_db_connection() as conn:
            row = conn.execute(
                """
                SELECT * FROM release_catalog_checks
                WHERE media_key = ?
                ORDER BY checked_at DESC, created_at DESC
                LIMIT 1
                """,
                (identity["media_key"],),
            ).fetchone()
        return dict(row) if row else None

    @staticmethod
    def _legacy_rows() -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'prewarmed_cache'"
            ).fetchone()
            if not exists:
                return []
            rows = conn.execute("SELECT * FROM prewarmed_cache ORDER BY id").fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _legacy_specs(row: Dict[str, Any]) -> List[Dict[str, Any]]:
        data: Dict[str, Any] = {}
        try:
            parsed_data = json.loads(row.get("data_json") or "{}")
            if isinstance(parsed_data, dict):
                data = parsed_data
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        domain = _canonical_domain(row.get("domain") or "movies")
        release_title = row.get("release_title") or row.get("title") or "Unknown release"
        parsed = parse_release_details(release_title)
        year = row.get("year")
        if domain == "movies" and year is None:
            year = extract_year_from_title(release_title)
        if domain == "movies" and year is None:
            return []
        episode = int(data.get("episode") or parsed.get("episode") or 0)
        scope_type = "movie" if domain == "movies" else (
            "episode" if episode else (
                "complete_series" if parsed.get("is_complete_series") else (
                    "season_pack" if int(row.get("season") or 0) else "series"
                )
            )
        )
        observed_at = str(row.get("updated_at") or _utc_now())
        cached_status = "cached" if bool(row.get("cached")) else "unknown"
        cache_checked_at = observed_at if cached_status == "cached" else None
        common = {
            "domain": domain,
            "title": row.get("title") or release_title,
            "year": year,
            "tmdb_id": data.get("tmdb_id"),
            "imdb_id": data.get("imdb_id"),
            "tvdb_id": data.get("tvdb_id"),
            "season": int(row.get("season") or 0),
            "episode": episode,
            "scope_type": scope_type,
            "size_bytes": row.get("size_bytes"),
            "formatted_size": row.get("formatted_size"),
            "seeders": row.get("seeders"),
            "indexer": data.get("indexer"),
            "source_vector": row.get("vector_origin") or data.get("vector_origin"),
            "observed_at": observed_at,
            "first_seen_at": observed_at,
            "last_observed_cycle_id": data.get("cycle_id") or data.get("last_observed_cycle_id"),
            "data": data,
        }
        primary = {
            **common,
            "reference_id": row.get("reference_id"),
            "release_title": release_title,
            "resolution": row.get("resolution"),
            "ad_cache_status": cached_status,
            "ad_checked_at": cache_checked_at,
            "last_cache_checked_at": cache_checked_at,
        }

        browser_reference = row.get("browser_stream_reference_id")
        browser_title = row.get("browser_stream_release_title") or release_title
        evidence = data.get("browser_verification") if isinstance(data, dict) else None
        direct_verified = False
        if browser_reference and row.get("browser_stream_verified_at"):
            try:
                from moviebot.db.cache_prewarm_repo import CachePrewarmRepository

                direct_verified = CachePrewarmRepository._has_fresh_browser_evidence(
                    {
                        "cached": True,
                        "browser_stream_reference_id": browser_reference,
                        "browser_stream_release_title": browser_title,
                        "browser_stream_verified_at": row.get("browser_stream_verified_at"),
                        "data": data,
                    }
                )
            except (ImportError, TypeError, ValueError):
                direct_verified = False

        if browser_reference and direct_verified:
            browser_spec = {
                **common,
                "reference_id": browser_reference,
                "release_title": browser_title,
                "resolution": row.get("resolution"),
                "ad_cache_status": "cached",
                "ad_checked_at": row.get("browser_stream_verified_at") or observed_at,
                "last_cache_checked_at": row.get("browser_stream_verified_at") or observed_at,
                "direct_play_status": "verified",
                "direct_play_verified_at": row.get("browser_stream_verified_at"),
                "direct_play_evidence": evidence,
                "source_vector": "verified_browser_stream",
            }
            primary_identity = ReleaseVariantRepository._release_identity(
                domain=domain,
                reference_id=primary.get("reference_id"),
                release_title=release_title,
                size_bytes=row.get("size_bytes"),
                indexer=data.get("indexer"),
            )
            browser_identity = ReleaseVariantRepository._release_identity(
                domain=domain,
                reference_id=browser_reference,
                release_title=browser_title,
                size_bytes=row.get("size_bytes"),
                indexer=data.get("indexer"),
            )
            if primary_identity == browser_identity:
                primary.update(
                    {
                        "direct_play_status": "verified",
                        "direct_play_verified_at": row.get("browser_stream_verified_at"),
                        "direct_play_evidence": evidence,
                    }
                )
                return [primary]
            return [primary, browser_spec]
        return [primary]

    @staticmethod
    def _legacy_spec_has_exact_identity(spec: Dict[str, Any]) -> bool:
        """Reject legacy release evidence that belongs to a related title."""
        return is_exact_media_identity(
            str(spec.get("title") or ""),
            str(spec.get("release_title") or ""),
        )

    @staticmethod
    def preview_legacy_migration() -> Dict[str, int]:
        rows = ReleaseVariantRepository._legacy_rows()
        projected_states: Dict[tuple[str, str], str] = {}
        projected_specs = 0
        skipped_ambiguous = 0
        skipped_identity_mismatch = 0
        for row in rows:
            specs = ReleaseVariantRepository._legacy_specs(row)
            if not specs:
                skipped_ambiguous += 1
            for spec in specs:
                if not ReleaseVariantRepository._legacy_spec_has_exact_identity(spec):
                    skipped_identity_mismatch += 1
                    continue
                projected_specs += 1
                identity = ReleaseVariantRepository.media_identity(
                    domain=spec["domain"],
                    title=spec["title"],
                    year=spec.get("year"),
                    season=spec.get("season", 0),
                    episode=spec.get("episode", 0),
                    scope_type=spec.get("scope_type"),
                    release_title=spec["release_title"],
                )
                release_identity = ReleaseVariantRepository._release_identity(
                    domain=spec["domain"],
                    reference_id=spec.get("reference_id"),
                    release_title=spec["release_title"],
                    size_bytes=spec.get("size_bytes"),
                    indexer=spec.get("indexer"),
                )
                variant_key = (identity["media_key"], release_identity)
                if spec.get("direct_play_status") == "verified":
                    state = "direct_play_ready"
                elif spec.get("ad_cache_status") == "cached":
                    state = "cached_only"
                else:
                    state = "unknown"
                precedence = {"unknown": 0, "cached_only": 1, "direct_play_ready": 2}
                previous = projected_states.get(variant_key)
                if previous is None or precedence[state] > precedence[previous]:
                    projected_states[variant_key] = state
        return {
            "legacy_rows": len(rows),
            "projected_specs": projected_specs,
            "projected_variants": len(projected_states),
            "collapsed_duplicates": projected_specs - len(projected_states),
            "direct_play_ready": sum(
                1 for state in projected_states.values() if state == "direct_play_ready"
            ),
            "cached_only": sum(
                1 for state in projected_states.values() if state == "cached_only"
            ),
            "unknown": sum(1 for state in projected_states.values() if state == "unknown"),
            "skipped_ambiguous": skipped_ambiguous,
            "skipped_identity_mismatch": skipped_identity_mismatch,
        }

    @staticmethod
    def migrate_legacy_prewarmed_cache() -> Dict[str, int]:
        rows = ReleaseVariantRepository._legacy_rows()
        migrated = 0
        skipped_ambiguous = 0
        skipped_identity_mismatch = 0
        for row in rows:
            specs = ReleaseVariantRepository._legacy_specs(row)
            if not specs:
                skipped_ambiguous += 1
            for spec in specs:
                if not ReleaseVariantRepository._legacy_spec_has_exact_identity(spec):
                    skipped_identity_mismatch += 1
                    continue
                ReleaseVariantRepository.upsert_variant(**spec)
                migrated += 1
        return {
            "legacy_rows": len(rows),
            "processed_variants": migrated,
            "skipped_ambiguous": skipped_ambiguous,
            "skipped_identity_mismatch": skipped_identity_mismatch,
        }
