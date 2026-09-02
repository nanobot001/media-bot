import json
import pytest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.db.repositories import DownloadJobRepository, LibraryItemRepository, TVLibraryRepository
from moviebot.db.release_variant_repo import ReleaseVariantRepository
from moviebot.db.cache_prewarm_repo import CachePrewarmRepository


@pytest.fixture
def test_client(monkeypatch, tmp_path):
    """Sets up isolated databases and test client for FastAPI web cockpit."""
    movies_db = tmp_path / "web_movies.sqlite3"
    tv_db = tmp_path / "web_tv.sqlite3"
    tv_classic_db = tmp_path / "web_tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))
    monkeypatch.setattr(settings, "output_dir", r"F:\_temp\movies")
    monkeypatch.setattr(settings, "tv_output_dir", r"F:\_temp\tv")
    monkeypatch.setattr(settings, "tv_classic_output_dir", r"F:\temp\Classic Tv")

    init_db("movies")
    init_db("tv")
    init_db("tv_classic")

    # Seed mock movie and TV show
    LibraryItemRepository.upsert(
        id="movie-dune",
        source="plex",
        rating_key="123",
        title="Dune: Part Two",
        normalized_title="duneparttwo",
        year=2024,
        imdb_id="tt15239678",
        file_path="/movies/dune.mkv",
        size_bytes=1000000
    )

    TVLibraryRepository.upsert_show(
        id="tv-reacher",
        title="Reacher",
        normalized_title="reacher",
        year=2022,
        tmdb_id=108978,
        domain="tv"
    )

    client = TestClient(app)
    return client


def test_web_cockpit_root_html_serving(test_client):
    """Verify that root / serves the Web Cockpit HTML SPA."""
    response = test_client.get("/")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, must-revalidate"
    assert "MediaBot Cockpit" in response.text
    assert "btn-domain-movies" in response.text
    assert "btn-domain-tv" in response.text
    assert "btn-domain-tv_classic" in response.text
    assert "modal-prepare-stream-btn" in response.text
    assert "Cache Browser Copy" in response.text
    assert "prewarm-cycle-history" in response.text
    assert "prewarm-next-run-label" in response.text

    app_js = test_client.get("/app.js")
    assert app_js.status_code == 200
    assert app_js.headers["cache-control"] == "no-cache, must-revalidate"
    assert "catalog_discovered_count" in app_js.text
    assert "catalog_retained_count" in app_js.text
    assert "catalog_provider_error_count" in app_js.text
    assert "availabilityStatePresentation" in app_js.text
    assert "availabilityStateLabel" in app_js.text
    assert "play-circle" in app_js.text
    assert "cloud-off" in app_js.text
    assert "Browser ready" in app_js.text
    assert "Provider cached" in app_js.text
    assert "openMediaFlowVariant" in app_js.text
    assert "browserSupportsSegmentedHls" in app_js.text
    assert "browserSupportsNativeHls" in app_js.text
    assert "supports_segmented_hls" in app_js.text
    assert "new window.Hls" in app_js.text
    assert "MANIFEST_PARSED" in app_js.text
    assert "/api/mediaflow/playback" in app_js.text
    assert "/api/mediaflow/sessions/" in app_js.text
    assert "scheduleMediaFlowSeek" in app_js.text
    assert "AbortController" in app_js.text
    assert "signal: seekController.signal" in app_js.text
    assert "seek_target_seconds" in app_js.text
    assert "mediaflow_duration_seconds" in app_js.text
    assert "telemetry-mediaflow-status" in response.text
    assert "telemetry-mediaflow-capacity" in response.text
    assert "telemetry-mediaflow-why" in response.text
    assert '>Diagnostics</button>' in response.text
    assert "mediaflow-diag-criteria" in response.text
    assert "configuration → source → probe → compatibility route" in response.text
    assert "mediaflow-diag-modal" in response.text
    assert "MediaFlow diagnostics" in response.text
    assert "/api/mediaflow/diagnostics?limit=10" in app_js.text
    assert "openMediaFlowDiagnostics" in app_js.text
    assert "Open MediaFlow diagnostic criteria and recent sanitized evidence" in app_js.text
    assert "stale evidence" in app_js.text
    assert "safe_next_action" in app_js.text
    assert "MEDIAFLOW_STATUS_UNAVAILABLE" in app_js.text
    assert "status could not be read" in app_js.text
    assert "MediaFlow On" in app_js.text
    assert "MEDIAFLOW_CAPACITY_BUSY" in app_js.text
    assert "all heavy transcode slots are in use" in app_js.text
    assert "setInterval(loadMediaFlowStatus, 30000)" in app_js.text
    assert "MediaFlow does not change A/B/C" in app_js.text
    assert "A ·" not in app_js.text
    assert "B ·" not in app_js.text
    assert "C ·" not in app_js.text

    hls_js = test_client.get("/vendor/hls-1.7.1.min.js")
    assert hls_js.status_code == 200
    assert len(hls_js.content) > 500_000
    assert "/vendor/hls-1.7.1.min.js" in response.text


def test_prewarm_status_endpoint_returns_sanitized_durable_history(test_client):
    import datetime as dt
    from moviebot.db.prewarm_run_repo import PrewarmRunRepository

    started = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.timezone.utc)
    reservation = PrewarmRunRepository.acquire(
        trigger_source="manual",
        runtime_id="private-runtime-id",
        process_id=4321,
        interval_hours=6,
        lease_seconds=300,
        now=started,
    )

    response = test_client.get("/api/prewarm/status?limit=10")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["is_prewarming"] is True
    assert data["active_cycle"]["cycle_id"] == reservation["cycle_id"]
    assert "runtime_id" not in data["active_cycle"]
    assert "process_id" not in data["active_cycle"]


def test_prewarm_items_use_catalog_projection(test_client):
    checked_at = datetime.now(timezone.utc).isoformat()
    release_title = "Projection.Row.2024.1080p.WEB-DL.HEVC.DDP.mkv"
    CachePrewarmRepository.upsert(
        domain="movies",
        title="Projection Row",
        season=0,
        year=2024,
        reference_id="opaque-search-token",
        release_title=release_title,
        cached=False,
    )
    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Projection Row",
        year=2024,
        reference_id="magnet:?xt=urn:btih:" + ("a" * 40),
        release_title=release_title,
        ad_cache_status="cached",
        ad_checked_at=checked_at,
    )

    response = test_client.get("/api/prewarm/items?domain=movies")
    assert response.status_code == 200
    data = response.json()
    assert data["items"][0]["availability_state"] == "ad_cached"
    assert data["items"][0]["variant_availability_state"] == "ad_cached"
    assert data["items"][0]["cloud_cached"] is True
    assert data["items"][0]["browser_stream_ready"] is False
    assert data["scoreboard"]["availability_breakdown"]["ad_cached"] == 1
    serialized = json.dumps(data).lower()
    assert "magnet:" not in serialized


def test_manual_prewarm_trigger_reports_busy_and_records_skip(test_client):
    import datetime as dt
    from moviebot.db.prewarm_run_repo import PrewarmRunRepository

    active = PrewarmRunRepository.acquire(
        trigger_source="scheduled",
        runtime_id="active-runtime",
        process_id=1234,
        interval_hours=6,
        lease_seconds=300,
        now=dt.datetime.now(dt.timezone.utc),
    )
    response = test_client.post("/api/prewarm/trigger")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["status"] == "skipped"
    assert data["error"]["code"] == "PREWARM_BUSY"
    assert data["active_cycle_id"] == active["cycle_id"]
    assert PrewarmRunRepository.get(data["cycle_id"])["status"] == "skipped"


def test_manual_prewarm_trigger_returns_reserved_cycle_id(test_client):
    with patch(
        "moviebot.core.background_prewarmer.run_cache_prewarm_cycle",
        new_callable=AsyncMock,
    ) as run_cycle:
        response = test_client.post("/api/prewarm/trigger")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["status"] == "running"
    assert len(data["cycle_id"]) == 32
    run_cycle.assert_awaited_once()
    assert run_cycle.await_args.kwargs["prepared"]["cycle_id"] == data["cycle_id"]


def test_api_domains_endpoint(test_client):
    """Verify /api/domains returns correct counts and directory paths."""
    response = test_client.get("/api/domains")
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert "domains" in data
    assert data["domains"]["movies"]["item_count"] == 1
    assert data["domains"]["tv"]["show_count"] == 1
    assert data["domains"]["movies"]["output_dir"] == r"F:\_temp\movies"
    assert data["domains"]["tv"]["output_dir"] == r"F:\_temp\tv"
    assert data["domains"]["tv_classic"]["output_dir"] == r"F:\temp\Classic Tv"


def test_api_discover_movies(test_client):
    """Verify /api/discover returns movies with Plex ownership badges."""
    mock_discover = {
        "ok": True,
        "data": {
            "domain": "movies",
            "feed_type": "trending",
            "results": [
                {
                    "id": "tmdb-693134",
                    "title": "Dune: Part Two",
                    "year": 2024,
                    "in_library": True,
                    "poster_url": "https://image.tmdb.org/poster1.jpg"
                },
                {
                    "id": "tmdb-12345",
                    "title": "Alien: Romulus",
                    "year": 2024,
                    "in_library": False,
                    "poster_url": "https://image.tmdb.org/poster2.jpg"
                }
            ]
        }
    }

    async def mock_tool(*args, **kwargs):
        return mock_discover

    checked_at = datetime.now(timezone.utc).isoformat()
    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Alien: Romulus",
        year=2024,
        release_title="Alien.Romulus.2024.1080p.WEB-DL.H.264.AAC.mp4",
        ad_cache_status="cached",
        ad_checked_at=checked_at,
        direct_play_status="verified",
        direct_play_verified_at=checked_at,
        direct_play_evidence={"status": "verified_browser_ready", "verified": True},
    )

    def mock_prewarm_get(domain, title, **kwargs):
        if title == "Alien: Romulus":
            return {
                "cached": True,
                "reference_id": "cached-alien-download-ref",
                "release_title": "Alien.Romulus.2024.2160p.WEB-DL.HEVC.DDP.mkv",
                "browser_stream_reference_id": "cached-alien-browser-ref",
                "browser_stream_release_title": "Alien.Romulus.2024.1080p.WEB-DL.H.264.AAC.mp4",
                "browser_stream_verified_at": "2026-08-26T12:00:00",
                "data": {
                    "browser_verification": {
                        "status": "verified_browser_ready",
                        "reference_id": "cached-alien-browser-ref",
                        "actual_filename": "Alien.Romulus.2024.1080p.WEB-DL.H.264.AAC.mp4",
                        "evidence_source": "actual_filename",
                    }
                },
            }
        return None

    with patch("moviebot.api.web_routes.discover_media_tool", new=mock_tool), \
         patch("moviebot.api.web_routes.CachePrewarmRepository.get", side_effect=mock_prewarm_get):
        response = test_client.get("/api/discover?domain=movies&feed=trending")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["data"]["results"]) == 2
        assert data["data"]["results"][0]["in_library"] is True
        assert data["data"]["results"][1]["in_library"] is False
        assert data["data"]["results"][0]["browser_stream_ready"] is False
        assert data["data"]["results"][0]["availability_state"] == "unknown"
        assert data["data"]["results"][1]["browser_stream_ready"] is True
        assert data["data"]["results"][1]["availability_state"] == "direct_play_ready"
        assert data["data"]["results"][1]["instant_stream_status"] == "browser_ready"
        assert data["data"]["results"][1]["stream_reference_id"] == "cached-alien-browser-ref"
        assert data["data"]["results"][1]["download_reference_id"] == "cached-alien-download-ref"


def test_api_discover_tv_and_classic(test_client):
    """Verify /api/discover handles TV and Classic TV requests."""
    mock_tv_discover = {
        "ok": True,
        "data": {
            "domain": "tv",
            "feed_type": "popular",
            "results": [
                {"id": "tv-1", "title": "Shogun", "year": 2024, "in_library": False}
            ]
        }
    }

    async def mock_tool(*args, **kwargs):
        return mock_tv_discover

    with patch("moviebot.api.web_routes.discover_media_tool", new=mock_tool):
        response = test_client.get("/api/discover?domain=tv&feed=popular")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["data"]["domain"] == "tv"
        assert data["data"]["results"][0]["title"] == "Shogun"
        assert data["data"]["results"][0]["availability_scope"]["scope_type"] == "series"




def test_api_history_endpoint_with_media_watcher_synthesis(test_client):
    """Verify /api/history returns download jobs enriched with media-watcher state."""
    # Seed download jobs
    DownloadJobRepository.create_job(
        id="job-downloading",
        alldebrid_magnet_id="mag1",
        selected_file_name="Movie.Active.1080p.mkv",
        target_dir=r"F:\_temp\movies",
        status="downloading",
        domain="movies"
    )
    DownloadJobRepository.create_job(
        id="job-stabilizing",
        alldebrid_magnet_id="mag2",
        selected_file_name="Show.S01E01.mkv",
        target_dir=r"F:\_temp\tv",
        status="downloading",
        domain="tv"
    )

    # Mock media watcher client
    with patch("moviebot.api.web_routes.MediaWatcherClient") as mock_watcher_cls:
        mock_watcher = MagicMock()
        def mock_file_status(filename):
            if "Show.S01E01" in filename:
                return "tracking", None  # Actively stabilizing in media-watcher
            return "unknown", None
        mock_watcher.get_file_status.side_effect = mock_file_status
        mock_watcher_cls.return_value = mock_watcher

        response = test_client.get("/api/history?domain=all")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["jobs"]) == 2

        # Verify synthesized display statuses
        tv_job = next(j for j in data["jobs"] if j["id"] == "job-stabilizing")
        movie_job = next(j for j in data["jobs"] if j["id"] == "job-downloading")

        assert tv_job["display_status"] == "processing"
        assert tv_job["status_label"] == "Media-Watcher Processing"
        assert tv_job["badge_color"] == "amber"

        assert movie_job["display_status"] == "downloading"
        assert movie_job["status_label"] == "IDM Downloading"
        assert movie_job["badge_color"] == "blue"


def test_web_details_endpoint_movie(test_client):
    """Verify /api/details returns rich movie metadata, cast, director, runtime, trailer."""
    mock_details = {
        "tmdb_id": 533535,
        "title": "Deadpool & Wolverine",
        "tagline": "Come together.",
        "runtime_formatted": "2h 8m",
        "status": "Released",
        "directors": ["Shawn Levy"],
        "cast": [{"name": "Ryan Reynolds", "character": "Deadpool"}],
        "trailer_url": "https://www.youtube.com/watch?v=Idh8n5XuYIA"
    }

    with patch("moviebot.api.web_routes.TMDbFactProvider") as mock_prov_cls:
        mock_prov = MagicMock()
        mock_prov.get_movie_details.return_value = mock_details
        mock_prov_cls.return_value = mock_prov

        response = test_client.get("/api/details?domain=movies&tmdb_id=533535")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        d = data["details"]
        assert d["title"] == "Deadpool & Wolverine"
        assert d["runtime_formatted"] == "2h 8m"
        assert d["directors"] == ["Shawn Levy"]
        assert len(d["cast"]) == 1
        assert "youtube" in d["trailer_url"]


def test_api_get_and_save_settings(test_client):
    """Verify /api/settings GET and POST lifecycle with SQLite kv_store persistence."""
    # 1. Initial GET settings returns per-domain defaults + system_info
    get_res = test_client.get("/api/settings")
    assert get_res.status_code == 200
    data = get_res.json()
    assert data["ok"] is True
    assert data["data"]["settings"]["default_domain"] == "movies"
    assert data["data"]["settings"]["movies_default_language"] == "en_us"
    assert data["data"]["settings"]["tv_default_tier"] == "major"
    assert data["data"]["settings"]["classic_tv_quality_preset"] == "1080p Remaster"
    assert data["data"]["system_info"]["output_dirs"]["movies"] == r"F:\_temp\movies"

    # 2. POST updated per-domain settings
    payload = {
        "default_domain": "tv",
        "movies_default_language": "en_us",
        "movies_quality_preset": "2160p Remux",
        "tv_default_language": "en_gb",
        "tv_default_time_range": "60d",
        "tv_default_tier": "streamers",
        "classic_tv_default_time_range": "1990s",
        "classic_tv_quality_preset": "1080p Remaster",
        "min_seeders": 5,
        "prefer_instant_cache": True,
        "movies_hide_owned": True
    }
    save_res = test_client.post("/api/settings", json=payload)
    assert save_res.status_code == 200
    save_data = save_res.json()
    assert save_data["ok"] is True
    assert save_data["data"]["default_domain"] == "tv"
    assert save_data["data"]["tv_default_language"] == "en_gb"
    assert save_data["data"]["movies_quality_preset"] == "2160p Remux"
    assert save_data["data"]["tv_default_tier"] == "streamers"
    assert save_data["data"]["classic_tv_default_time_range"] == "1990s"
    assert save_data["data"]["min_seeders"] == 5
    assert save_data["data"]["movies_hide_owned"] is True

    # 3. Subsequent GET returns persisted updated values
    get_after = test_client.get("/api/settings")
    assert get_after.status_code == 200
    persisted = get_after.json()["data"]["settings"]
    assert persisted["default_domain"] == "tv"
    assert persisted["tv_default_language"] == "en_gb"
    assert persisted["tv_default_tier"] == "streamers"
    assert persisted["classic_tv_default_time_range"] == "1990s"
    assert persisted["min_seeders"] == 5
    assert persisted["movies_hide_owned"] is True



