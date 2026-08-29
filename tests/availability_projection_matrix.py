from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from moviebot.db.release_variant_repo import ReleaseVariantRepository


def seed_availability_projection_matrix() -> List[Dict[str, Any]]:
    """Seed reusable unknown/A/B/C, freshness, remake, and TV-scope evidence."""
    now = datetime.now(timezone.utc).isoformat()
    stale = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()

    ReleaseVariantRepository.record_scope_check(
        domain="movies",
        title="Matrix State A",
        year=2020,
        status="complete",
        candidate_count=1,
        checked_count=1,
        cached_count=0,
        checked_at=now,
    )
    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Matrix State B",
        year=2021,
        release_title="Matrix.State.B.2021.1080p.WEB-DL.HEVC.DDP.mkv",
        ad_cache_status="cached",
        ad_checked_at=now,
    )
    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Matrix State C",
        year=2022,
        release_title="Matrix.State.C.2022.1080p.WEB-DL.x264.AAC.mp4",
        ad_cache_status="cached",
        ad_checked_at=now,
        direct_play_status="verified",
        direct_play_verified_at=now,
        direct_play_evidence={"status": "verified_browser_ready", "verified": True},
    )
    ReleaseVariantRepository.record_scope_check(
        domain="movies",
        title="Matrix Stale",
        year=2023,
        status="complete",
        candidate_count=0,
        checked_count=0,
        cached_count=0,
        checked_at=stale,
    )
    ReleaseVariantRepository.record_scope_check(
        domain="movies",
        title="Matrix Provider Error",
        year=2024,
        status="provider_error",
        candidate_count=1,
        checked_count=0,
        cached_count=0,
        unknown_count=1,
        checked_at=now,
        error_code="AD_PROVIDER_ERROR",
    )
    for year in (1982, 2011):
        ReleaseVariantRepository.upsert_variant(
            domain="movies",
            title="The Thing",
            year=year,
            release_title=f"The.Thing.{year}.1080p.BluRay.x264.mkv",
            ad_cache_status="cached",
            ad_checked_at=now,
        )
    ReleaseVariantRepository.upsert_variant(
        domain="tv",
        title="Scoped Show",
        season=2,
        episode=3,
        scope_type="episode",
        release_title="Scoped.Show.S02E03.1080p.WEB-DL.x264.mkv",
        ad_cache_status="cached",
        ad_checked_at=now,
    )
    ReleaseVariantRepository.upsert_variant(
        domain="tv",
        title="Scoped Show",
        season=2,
        scope_type="season_pack",
        release_title="Scoped.Show.S02.1080p.WEB-DL.x264.mkv",
        ad_cache_status="cached",
        ad_checked_at=now,
    )
    ReleaseVariantRepository.upsert_variant(
        domain="tv_classic",
        title="Classic Matrix Show",
        scope_type="series",
        release_title="Classic.Matrix.Show.1080p.WEB-DL.x264.mkv",
        ad_cache_status="cached",
        ad_checked_at=now,
    )

    return [
        {"domain": "movies", "title": "Matrix Unknown", "year": 2019, "expected": "unknown"},
        {"domain": "movies", "title": "Matrix State A", "year": 2020, "expected": "not_cached"},
        {"domain": "movies", "title": "Matrix State B", "year": 2021, "expected": "ad_cached"},
        {"domain": "movies", "title": "Matrix State C", "year": 2022, "expected": "direct_play_ready"},
        {"domain": "movies", "title": "Matrix Stale", "year": 2023, "expected": "unknown"},
        {"domain": "movies", "title": "Matrix Provider Error", "year": 2024, "expected": "unknown"},
        {"domain": "movies", "title": "The Thing", "year": 1982, "expected": "ad_cached"},
        {"domain": "movies", "title": "The Thing", "year": 2011, "expected": "ad_cached"},
        {
            "domain": "tv",
            "title": "Scoped Show",
            "season": 2,
            "episode": 3,
            "scope_type": "episode",
            "expected": "ad_cached",
        },
        {
            "domain": "tv",
            "title": "Scoped Show",
            "season": 2,
            "scope_type": "season_pack",
            "expected": "ad_cached",
        },
        {"domain": "tv", "title": "Scoped Show", "scope_type": "series", "expected": "unknown"},
        {
            "domain": "classic_tv",
            "title": "Classic Matrix Show",
            "scope_type": "series",
            "expected": "ad_cached",
        },
    ]
