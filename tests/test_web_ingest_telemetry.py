import pytest
import respx
import json
from starlette.testclient import TestClient
from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.db.repositories import (
    SearchResultRepository,
    TVLibraryRepository,
    DownloadJobRepository
)


@pytest.fixture
def ingest_test_env(monkeypatch, tmp_path):
    movies_db = tmp_path / "test_ingest_movies.sqlite3"
    tv_db = tmp_path / "test_ingest_tv.sqlite3"
    tv_classic_db = tmp_path / "test_ingest_tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))
    monkeypatch.setattr(settings, "prowlarr_url", "https://prowlarr.test")
    monkeypatch.setattr(settings, "prowlarr_api_key", "fake_prowlarr_key")
    monkeypatch.setattr(settings, "alldebrid_api_key", "fake_alldebrid_key")
    monkeypatch.setattr(settings, "tmdb_api_key", "fake_tmdb_key")

    init_db("movies")
    init_db("tv")
    init_db("tv_classic")

    client = TestClient(app)
    return client


def test_api_ingest_movie_with_reference_id(ingest_test_env):
    SearchResultRepository.insert(
        id="ref-movie-123",
        query_string="Gladiator II",
        indexer="PublicTracker",
        title="Gladiator.II.2024.1080p.WEB-DL",
        size_bytes=4000000000,
        seeders=100,
        magnet_uri_hash="gladhash123",
        raw_json_payload=json.dumps({
            "title": "Gladiator.II.2024.1080p.WEB-DL",
            "downloadUrl": "magnet:?xt=urn:btih:gladhash123"
        }),
        domain="movies"
    )

    response = ingest_test_env.post("/api/ingest", json={
        "reference_id": "ref-movie-123",
        "title": "Gladiator II",
        "domain": "movies",
        "dry_run": True
    })

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["status"] == "queued"
    assert "job_id" in data
    assert "Gladiator" in data["message"]


def test_api_ingest_movie_by_title_resolution(ingest_test_env):
    prowlarr_results = [
        {
            "title": "Dune.Part.Two.2024.1080p.WEB-DL",
            "indexer": "TorrentTracker",
            "size": 3500000000,
            "seeders": 150,
            "downloadUrl": "magnet:?xt=urn:btih:dune2hash123",
            "guid": "guid-dune-2"
        }
    ]

    with respx.mock:
        respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_results)
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(200, json={
            "status": "success",
            "data": {
                "magnets": [
                    {"hash": "dune2hash123", "ready": True}
                ]
            }
        })

        response = ingest_test_env.post("/api/ingest", json={
            "title": "Dune: Part Two",
            "domain": "movies",
            "dry_run": True
        })

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["status"] == "queued"


def test_api_tv_series_manifest_with_plex_inventory(ingest_test_env):
    tmdb_show_details = {
        "id": 99999,
        "name": "Severance",
        "first_air_date": "2022-02-18",
        "poster_path": "/severance_poster.jpg",
        "backdrop_path": "/severance_backdrop.jpg",
        "overview": "Mark leads a team of office workers...",
        "seasons": [
            {"season_number": 1, "name": "Season 1", "episode_count": 2}
        ]
    }

    tmdb_s1_facts = {
        "season_number": 1,
        "episodes": [
            {"episode_number": 1, "name": "Good News About Hell", "air_date": "2022-02-18", "runtime": 57},
            {"episode_number": 2, "name": "Half Loop", "air_date": "2022-02-18", "runtime": 53}
        ]
    }

    TVLibraryRepository.upsert_show(
        id="tmdb-tv-99999",
        title="Severance",
        normalized_title="severance",
        year=2022,
        tmdb_id=99999,
        domain="tv"
    )
    TVLibraryRepository.upsert_episode(
        id="ep-sev-s01e01",
        show_id="tmdb-tv-99999",
        season_number=1,
        episode_number=1,
        title="Good News About Hell",
        domain="tv"
    )

    with respx.mock:
        # Register season detail route first (more specific)
        respx.get(url__regex=r"https://api\.themoviedb\.org/3/tv/99999/season/1.*").respond(200, json=tmdb_s1_facts)
        # Register general show detail route second
        respx.get(url__regex=r"https://api\.themoviedb\.org/3/tv/99999(\?.*)?$").respond(200, json=tmdb_show_details)

        response = ingest_test_env.get("/api/tv/series-manifest?tmdb_id=99999&domain=tv")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["title"] == "Severance"
        assert data["total_episodes"] == 2
        assert data["total_owned_episodes"] == 1
        assert data["total_missing_episodes"] == 1

        s1 = data["seasons"][0]
        assert s1["season_number"] == 1
        assert s1["owned_count"] == 1
        assert s1["missing_count"] == 1
        assert s1["episodes"][0]["owned"] is True
        assert s1["episodes"][1]["owned"] is False


def test_api_tv_ingest_episodes_endpoint(ingest_test_env):
    prowlarr_tv_results = [
        {
            "title": "Severance.S01.1080p.ATVP.WEB-DL",
            "indexer": "TVTracker",
            "size": 12000000000,
            "seeders": 80,
            "downloadUrl": "magnet:?xt=urn:btih:severancehash123",
            "guid": "guid-sev-s01"
        }
    ]

    with respx.mock:
        respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_tv_results)
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(200, json={
            "status": "success",
            "data": {"magnets": [{"hash": "severancehash123", "ready": True}]}
        })

        response = ingest_test_env.post("/api/tv/ingest-episodes", json={
            "tmdb_id": 99999,
            "title": "Severance",
            "domain": "tv",
            "season": 1,
            "episode_numbers": [2],
            "dry_run": True
        })

        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["status"] == "queued"
        assert data["title"] == "Severance"