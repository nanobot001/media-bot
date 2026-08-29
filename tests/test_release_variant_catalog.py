import json
from datetime import datetime, timedelta, timezone

import pytest
from starlette.testclient import TestClient

from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.core.availability_service import AvailabilityService
from moviebot.core.release_parser import is_exact_media_identity
from moviebot.db.connection import get_db_connection, init_db
from moviebot.db.release_variant_repo import ReleaseVariantRepository
from tests.availability_projection_matrix import seed_availability_projection_matrix


@pytest.fixture(autouse=True)
def catalog_databases(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "movies.sqlite3"))
    monkeypatch.setattr(settings, "tv_database_path", str(tmp_path / "tv.sqlite3"))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tmp_path / "classic.sqlite3"))
    init_db("movies")
    init_db("tv")
    init_db("tv_classic")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def test_shared_availability_projection_matrix():
    cases = seed_availability_projection_matrix()
    for case in cases:
        expected = case.pop("expected")
        projection = AvailabilityService.inspect(**case)
        assert projection["availability_state"] == expected
        assert projection["media"]["domain"] in {"movies", "tv", "tv_classic"}
        assert projection["browser_stream_ready"] is (expected == "direct_play_ready")
        assert projection["instant_cached"] is projection["browser_stream_ready"]
        assert projection["cloud_cached"] is (expected in {"ad_cached", "direct_play_ready"})

    classic = AvailabilityService.inspect(
        domain="classic_tv",
        title="Classic Matrix Show",
        scope_type="series",
    )
    assert classic["media"]["domain"] == "tv_classic"
    assert AvailabilityService.inspect(
        domain="tv",
        title="Scoped Show",
        scope_type="series",
    )["availability_state"] == "unknown"


def test_exact_identity_accepts_release_editions_but_rejects_related_titles():
    assert is_exact_media_identity(
        "Minions & Monsters",
        "Minions.and.Monsters.2026.1080p.WEBRip.x265.mkv",
    )
    assert is_exact_media_identity(
        "Scary Movie",
        "Scary.Movie.Extended.Cut.2026.1080p.WEB-DL.x265.mkv",
    )
    assert not is_exact_media_identity(
        "The Odyssey",
        "The.Odyssey.The.Making.of.an.Epic.2026.1080p.WEBRip.x264.mkv",
    )
    assert not is_exact_media_identity(
        "Friends",
        "Smiling.Friends.S01.1080p.WEBRip.x264.mkv",
    )


def test_multiple_variants_remain_independent_and_first_seen_is_stable():
    first_seen = "2026-08-01T12:00:00+00:00"
    later_seen = "2026-08-02T12:00:00+00:00"
    first = ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="The Matrix",
        year=1999,
        reference_id="matrix-remux-ref",
        release_title="The.Matrix.1999.2160p.BluRay.Remux.HEVC.TrueHD.mkv",
        size_bytes=70_000_000_000,
        indexer="Indexer A",
        observed_at=first_seen,
        first_seen_at=first_seen,
        ad_cache_status="cached",
        ad_checked_at=_now(),
    )
    second = ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="The Matrix",
        year=1999,
        reference_id="matrix-web-ref",
        release_title="The.Matrix.1999.1080p.WEB-DL.x264.AAC.mp4",
        size_bytes=8_000_000_000,
        indexer="Indexer B",
        observed_at=first_seen,
        first_seen_at=first_seen,
        ad_cache_status="not_cached",
        ad_checked_at=_now(),
    )

    assert first["variant_id"] != second["variant_id"]
    assert len(ReleaseVariantRepository.list_variants(
        domain="movies", title="The Matrix", year=1999
    )) == 2

    updated = ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="The Matrix",
        year=1999,
        reference_id="matrix-remux-ref-new-search-token",
        release_title="The.Matrix.1999.2160p.BluRay.Remux.HEVC.TrueHD.mkv",
        size_bytes=70_000_000_000,
        indexer="Indexer A",
        seeders=99,
        observed_at=later_seen,
    )
    assert updated["variant_id"] == first["variant_id"]
    assert updated["first_seen_at"] == first_seen
    assert updated["last_seen_at"] == later_seen
    assert updated["seeders"] == 99
    assert updated["last_cache_checked_at"] == first["last_cache_checked_at"]


def test_availability_states_and_mediaflow_independence():
    checked_at = _now()
    ReleaseVariantRepository.record_scope_check(
        domain="movies",
        title="Catalog State Movie",
        year=2020,
        status="complete",
        candidate_count=2,
        checked_count=2,
        cached_count=0,
        checked_at=checked_at,
    )
    assert AvailabilityService.inspect(
        domain="movies", title="Catalog State Movie", year=2020
    )["availability_state"] == "not_cached"

    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Catalog State Movie",
        year=2020,
        release_title="Catalog.State.Movie.2020.1080p.WEB-DL.HEVC.DDP.mkv",
        size_bytes=6_000_000_000,
        ad_cache_status="cached",
        ad_checked_at=checked_at,
        mediaflow_status="verified",
        mediaflow_checked_at=checked_at,
    )
    state_b = AvailabilityService.inspect(
        domain="movies", title="Catalog State Movie", year=2020
    )
    assert state_b["availability_state"] == "ad_cached"
    assert state_b["cloud_cached"] is True
    assert state_b["browser_stream_ready"] is False

    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Catalog State Movie",
        year=2020,
        release_title="Catalog.State.Movie.2020.1080p.WEB-DL.x264.AAC.mp4",
        size_bytes=5_000_000_000,
        ad_cache_status="cached",
        ad_checked_at=checked_at,
        direct_play_status="verified",
        direct_play_verified_at=checked_at,
        direct_play_evidence={"status": "verified_browser_ready", "verified": True},
    )
    state_c = AvailabilityService.inspect(
        domain="movies", title="Catalog State Movie", year=2020
    )
    assert state_c["availability_state"] == "direct_play_ready"
    assert state_c["browser_stream_ready"] is True
    assert state_c["cached_variant_count"] == 2
    assert state_c["direct_play_variant_count"] == 1

    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Catalog State Movie",
        year=2020,
        release_title="Catalog.State.Movie.2020.1080p.WEB-DL.HEVC.DDP.mkv",
        size_bytes=6_000_000_000,
        mediaflow_status="failed",
        mediaflow_checked_at=checked_at,
    )
    assert AvailabilityService.inspect(
        domain="movies", title="Catalog State Movie", year=2020
    )["availability_state"] == "direct_play_ready"


@pytest.mark.parametrize("status", ["partial", "provider_error"])
def test_incomplete_or_failed_checks_remain_unknown(status):
    ReleaseVariantRepository.record_scope_check(
        domain="movies",
        title=f"Unknown {status}",
        year=2021,
        status=status,
        candidate_count=3,
        checked_count=1 if status == "partial" else 0,
        cached_count=0,
        unknown_count=2 if status == "partial" else 3,
        checked_at=_now(),
        error_code="AD_CHECK_INCOMPLETE",
    )
    result = AvailabilityService.inspect(
        domain="movies", title=f"Unknown {status}", year=2021
    )
    assert result["availability_state"] == "unknown"
    assert result["cached"] is False


def test_stale_complete_check_remains_unknown():
    assert AvailabilityService.inspect(
        domain="movies", title="Never Checked", year=2022
    )["availability_state"] == "unknown"

    stale_at = (datetime.now(timezone.utc) - timedelta(days=8)).isoformat()
    ReleaseVariantRepository.record_scope_check(
        domain="movies",
        title="Stale Check",
        year=2022,
        status="complete",
        candidate_count=0,
        checked_count=0,
        cached_count=0,
        checked_at=stale_at,
    )
    result = AvailabilityService.inspect(
        domain="movies", title="Stale Check", year=2022
    )
    assert result["availability_state"] == "unknown"
    assert result["coverage"]["fresh"] is False


def test_movie_remakes_and_tv_scopes_do_not_share_variants():
    for year in (1982, 2011):
        ReleaseVariantRepository.upsert_variant(
            domain="movies",
            title="The Thing",
            year=year,
            release_title=f"The.Thing.{year}.1080p.BluRay.x264.mkv",
            ad_cache_status="cached",
            ad_checked_at=_now(),
        )
    assert AvailabilityService.inspect(
        domain="movies", title="The Thing", year=1982
    )["variant_count"] == 1
    assert AvailabilityService.inspect(
        domain="movies", title="The Thing", year=2011
    )["variant_count"] == 1

    scoped = [
        ("episode", 2, 3, "Example.Show.S02E03.1080p.WEB-DL.mkv"),
        ("season_pack", 2, 0, "Example.Show.S02.1080p.WEB-DL.mkv"),
        ("complete_series", 0, 0, "Example.Show.Complete.Series.1080p.WEB-DL.mkv"),
    ]
    for scope_type, season, episode, release_title in scoped:
        ReleaseVariantRepository.upsert_variant(
            domain="tv",
            title="Example Show",
            season=season,
            episode=episode,
            scope_type=scope_type,
            release_title=release_title,
            ad_cache_status="cached",
            ad_checked_at=_now(),
        )
    for scope_type, season, episode, _ in scoped:
        result = AvailabilityService.inspect(
            domain="tv",
            title="Example Show",
            season=season,
            episode=episode,
            scope_type=scope_type,
        )
        assert result["variant_count"] == 1
        assert result["media"]["scope_type"] == scope_type


def test_legacy_migration_is_additive_conservative_and_idempotent():
    now = _now()
    browser_evidence = json.dumps(
        {
            "browser_verification": {
                "status": "verified_browser_ready",
                "reference_id": "browser-ref",
                "actual_filename": "Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
                "verified": True,
            }
        }
    )
    with get_db_connection() as conn:
        conn.executemany(
            """
            INSERT INTO prewarmed_cache (
                id, domain, title, normalized_title, season, year, reference_id,
                release_title, browser_stream_reference_id,
                browser_stream_release_title, browser_stream_verified_at,
                cached, previously_cached, data_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    "movies:scarymovie:0:2026", "movies", "Scary Movie", "scarymovie",
                    0, 2026, "browser-ref",
                    "Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4", "browser-ref",
                    "Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4", now,
                    1, 1, browser_evidence, now,
                ),
                (
                    "movies:dune:0:2021", "movies", "Dune", "dune", 0, 2021,
                    "dune-2021-ref", "Dune.2021.1080p.WEB-DL.HEVC.DDP.mkv",
                    None, None, None, 1, 1, "{}", now,
                ),
                (
                    "movies:dune:0:1984", "movies", "Dune", "dune", 0, 1984,
                    "dune-1984-ref", "Dune.1984.1080p.BluRay.x264.mkv",
                    None, None, None, 1, 1, "{}", now,
                ),
                (
                    "movies:unknownlegacy:0:2023", "movies", "Unknown Legacy",
                    "unknownlegacy", 0, 2023, "unknown-ref",
                    "Unknown.Legacy.2023.1080p.WEB-DL.x264.mkv",
                    None, None, None, 0, 0, "{}", now,
                ),
                (
                    "tv:exampleshow:2:episode3", "tv", "Example Show", "exampleshow",
                    2, None, "episode-ref", "Example.Show.S02E03.1080p.WEB-DL.mkv",
                    None, None, None, 1, 1, json.dumps({"episode": 3}), now,
                ),
                (
                    "tv:exampleshow:2:pack", "tv", "Example Show", "exampleshow",
                    2, None, "season-pack-ref", "Example.Show.S02.1080p.WEB-DL.mkv",
                    None, None, None, 1, 1, "{}", now,
                ),
                (
                    "tv_classic:exampleshow:0", "tv_classic", "Example Show", "exampleshow",
                    0, None, "complete-ref", "Example.Show.Complete.Series.1080p.WEB-DL.mkv",
                    None, None, None, 1, 1, "{}", now,
                ),
                (
                    "movies:theodyssey:0:2026", "movies", "The Odyssey", "theodyssey",
                    0, 2026, "making-of-ref",
                    "The.Odyssey.The.Making.of.an.Epic.2026.1080p.WEBRip.x264.mkv",
                    None, None, None, 1, 1, "{}", now,
                ),
            ],
        )

    preview = ReleaseVariantRepository.preview_legacy_migration()
    assert preview == {
        "legacy_rows": 8,
        "projected_specs": 7,
        "projected_variants": 7,
        "collapsed_duplicates": 0,
        "direct_play_ready": 1,
        "cached_only": 5,
        "unknown": 1,
        "skipped_ambiguous": 0,
        "skipped_identity_mismatch": 1,
    }

    migration = ReleaseVariantRepository.migrate_legacy_prewarmed_cache()
    assert migration == {
        "legacy_rows": 8,
        "processed_variants": 7,
        "skipped_ambiguous": 0,
        "skipped_identity_mismatch": 1,
    }
    assert AvailabilityService.inspect(
        domain="movies", title="Scary Movie", year=2026
    )["availability_state"] == "direct_play_ready"
    assert AvailabilityService.inspect(
        domain="movies", title="Dune", year=2021
    )["availability_state"] == "ad_cached"
    assert AvailabilityService.inspect(
        domain="movies", title="Dune", year=1984
    )["availability_state"] == "ad_cached"
    unknown = AvailabilityService.inspect(
        domain="movies", title="Unknown Legacy", year=2023
    )
    assert unknown["availability_state"] == "unknown"
    assert AvailabilityService.inspect(
        domain="tv",
        title="Example Show",
        season=2,
        episode=3,
        scope_type="episode",
    )["variant_count"] == 1
    assert AvailabilityService.inspect(
        domain="tv",
        title="Example Show",
        season=2,
        scope_type="season_pack",
    )["variant_count"] == 1
    assert AvailabilityService.inspect(
        domain="tv_classic",
        title="Example Show",
        scope_type="complete_series",
    )["variant_count"] == 1
    assert AvailabilityService.inspect(
        domain="movies", title="The Odyssey", year=2026
    )["variant_count"] == 0

    first_seen = unknown["variants"][0]["first_seen_at"]
    ReleaseVariantRepository.migrate_legacy_prewarmed_cache()
    rerun = AvailabilityService.inspect(
        domain="movies", title="Unknown Legacy", year=2023
    )
    assert rerun["variant_count"] == 1
    assert rerun["variants"][0]["first_seen_at"] == first_seen
    with get_db_connection() as conn:
        assert conn.execute("SELECT COUNT(*) FROM prewarmed_cache").fetchone()[0] == 8


def test_catalog_api_is_bounded_and_does_not_expose_provider_references():
    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Safe Inspector",
        year=2024,
        reference_id="magnet:?xt=urn:btih:" + ("a" * 40) + "&dn=secret",
        release_title="Safe.Inspector.2024.1080p.WEB-DL.x264.AAC.mp4",
        ad_cache_status="cached",
        ad_checked_at=_now(),
        direct_play_status="verified",
        direct_play_verified_at=_now(),
        direct_play_evidence={
            "status": "verified_browser_ready",
            "verified": True,
            "stream_url": "https://provider.invalid/private",
            "private_path": "C:/private/movie.mp4",
        },
    )

    response = TestClient(app).get(
        "/api/prewarm/catalog",
        params={"title": "Safe Inspector", "domain": "movies", "year": 2024},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["availability_state"] == "direct_play_ready"
    serialized = json.dumps(payload).lower()
    assert "magnet:" not in serialized
    assert "provider.invalid" not in serialized
    assert "c:/private" not in serialized
    assert "reference_id" not in serialized

    missing_year = TestClient(app).get(
        "/api/prewarm/catalog",
        params={"title": "Safe Inspector", "domain": "movies"},
    )
    assert missing_year.status_code == 400
