import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from starlette.testclient import TestClient
from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.db.repositories import DownloadJobRepository, LibraryItemRepository, TVLibraryRepository


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
    assert "MediaBot Cockpit" in response.text
    assert "btn-domain-movies" in response.text
    assert "btn-domain-tv" in response.text
    assert "btn-domain-tv_classic" in response.text


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

    with patch("moviebot.api.web_routes.discover_media_tool", new=mock_tool):
        response = test_client.get("/api/discover?domain=movies&feed=trending")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["data"]["results"]) == 2
        assert data["data"]["results"][0]["in_library"] is True
        assert data["data"]["results"][1]["in_library"] is False


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

