import pytest
import respx
from starlette.testclient import TestClient
from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.core.release_parser import parse_release_details, format_size_bytes


@pytest.fixture
def search_test_env(monkeypatch, tmp_path):
    """Sets up temporary databases and client for search endpoints testing."""
    movies_db = tmp_path / "search_movies.sqlite3"
    tv_db = tmp_path / "search_tv.sqlite3"
    tv_classic_db = tmp_path / "search_tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))
    monkeypatch.setattr(settings, "prowlarr_url", "https://prowlarr.test")
    monkeypatch.setattr(settings, "prowlarr_api_key", "fake_prowlarr_key")
    monkeypatch.setattr(settings, "alldebrid_api_key", "fake_alldebrid_key")

    init_db("movies")
    init_db("tv")
    init_db("tv_classic")

    client = TestClient(app)
    return client


def test_release_parser_metadata_extraction():
    """Verify release title parser extracts resolution, HDR, audio, codec, and release groups."""
    # 1. 4K UHD Remux with DV and Atmos
    title1 = "The.Batman.2022.2160p.UHD.Remux.HEVC.DV.TrueHD.7.1.Atmos-FraMeSToR"
    p1 = parse_release_details(title1)
    assert p1["resolution"] == "2160p"
    assert p1["source_type"] == "Remux"
    assert p1["quality_label"] == "2160p Remux"
    assert p1["hdr"] == "Dolby Vision"
    assert p1["codec"] == "HEVC (x265)"
    assert p1["audio"] == "Dolby Atmos"
    assert p1["channels"] == "7.1"
    assert p1["release_group"] == "FraMeSToR"

    # 2. 1080p Web-DL with DDP5.1
    title2 = "Reacher.S02E01.1080p.AMZN.WEB-DL.DDP5.1.H.264-FLUX"
    p2 = parse_release_details(title2)
    assert p2["resolution"] == "1080p"
    assert p2["source_type"] == "Web-DL"
    assert p2["quality_label"] == "1080p Web-DL"
    assert p2["codec"] == "x264"
    assert p2["audio"] == "DDP 5.1"
    assert p2["channels"] == "5.1"
    assert p2["release_group"] == "FLUX"

    # 3. 720p HDTV
    title3 = "Cheers.S01.720p.HDTV.x264-MockGroup"
    p3 = parse_release_details(title3)
    assert p3["resolution"] == "720p"
    assert p3["source_type"] == "HDTV"
    assert p3["quality_label"] == "720p HDTV"
    assert p3["codec"] == "x264"
    assert p3["release_group"] == "MockGroup"

    # 4. Format size bytes
    assert format_size_bytes(15000000000) == "13.97 GB"
    assert format_size_bytes(500000000) == "476.8 MB"
    assert format_size_bytes(0) == "0 MB"


def test_api_search_movies_with_lightning_cache(search_test_env):
    """Verify /api/search returns movies with AllDebrid lightning cache badging and pinned sorting."""
    prowlarr_releases = [
        {
            "title": "Dune.Part.Two.2024.1080p.WEB-DL.DDP5.1.x264-FLUX",
            "indexer": "TrackerA",
            "size": 5000000000,
            "seeders": 150,
            "downloadUrl": "magnet:?xt=urn:btih:dunehash1111111111111111111111111111111111&dn=Dune.Part.Two.1080p",
            "guid": "guid-dune-1",
        },
        {
            "title": "Dune.Part.Two.2024.2160p.WEB-DL.DV.HDR.HEVC.Atmos-FLUX",
            "indexer": "TrackerB",
            "size": 18000000000,
            "seeders": 80,
            "downloadUrl": "magnet:?xt=urn:btih:dunehash2222222222222222222222222222222222&dn=Dune.Part.Two.2160p",
            "guid": "guid-dune-2",
        },
        {
            "title": "Dune.Part.Two.2024.720p.HDTV.x264-Mock",
            "indexer": "TrackerC",
            "size": 2000000000,
            "seeders": 20,
            "downloadUrl": "magnet:?xt=urn:btih:dunehash3333333333333333333333333333333333&dn=Dune.Part.Two.720p",
            "guid": "guid-dune-3",
        }
    ]

    with respx.mock:
        respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_releases)
        # Mock AllDebrid: 2160p is instant cached (ready=True), 1080p is not (ready=False), 720p is instant cached (ready=True)
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(
            200,
            json={
                "status": "success",
                "data": {
                    "magnets": [
                        {
                            "magnet": "magnet:?xt=urn:btih:dunehash1111111111111111111111111111111111&dn=Dune.Part.Two.1080p",
                            "hash": "dunehash1111111111111111111111111111111111",
                            "ready": False,
                        },
                        {
                            "magnet": "magnet:?xt=urn:btih:dunehash2222222222222222222222222222222222&dn=Dune.Part.Two.2160p",
                            "hash": "dunehash2222222222222222222222222222222222",
                            "ready": True,
                        },
                        {
                            "magnet": "magnet:?xt=urn:btih:dunehash3333333333333333333333333333333333&dn=Dune.Part.Two.720p",
                            "hash": "dunehash3333333333333333333333333333333333",
                            "ready": True,
                        }
                    ]
                }
            }
        )

        response = search_test_env.get("/api/search?query=Dune%20Part%20Two&domain=movies")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["domain"] == "movies"
        assert data["count"] == 3
        assert data["cached_count"] == 2

        results = data["results"]
        # Cached items should be pinned to top!
        # Both 2160p (80 seeds) and 720p (20 seeds) are cached; 2160p has more seeds so it is first
        assert results[0]["cached"] is True
        assert results[0]["cache_badge"] == "lightning"
        assert results[0]["resolution"] == "2160p"
        assert results[0]["quality_label"] == "2160p Web-DL"
        assert results[0]["hdr"] == "DV / HDR"
        assert results[0]["audio"] == "Dolby Atmos"
        assert results[0]["codec"] == "HEVC (x265)"

        assert results[1]["cached"] is True
        assert results[1]["cache_badge"] == "lightning"
        assert results[1]["resolution"] == "720p"

        # Uncached item is ranked after cached items
        assert results[2]["cached"] is False
        assert results[2]["cache_badge"] == "uncached"
        assert results[2]["resolution"] == "1080p"


def test_api_search_tv_and_classic_tv(search_test_env):
    """Verify /api/search handles TV and Classic TV queries with season/episode filtering."""
    prowlarr_tv_results = [
        {
            "title": "Reacher.S02E01.1080p.WEB-DL.DDP5.1.Atmos-FLUX",
            "indexer": "TrackerA",
            "size": 3000000000,
            "seeders": 140,
            "downloadUrl": "magnet:?xt=urn:btih:reacherhash1111111111111111111111111111111111&dn=Reacher.S02E01",
            "guid": "guid-reacher-1",
        }
    ]

    with respx.mock:
        route = respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_tv_results)
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(
            200,
            json={
                "status": "success",
                "data": {
                    "magnets": [
                        {
                            "magnet": "magnet:?xt=urn:btih:reacherhash1111111111111111111111111111111111&dn=Reacher.S02E01",
                            "hash": "reacherhash1111111111111111111111111111111111",
                            "ready": True,
                        }
                    ]
                }
            }
        )

        response = search_test_env.get("/api/search?query=Reacher&domain=tv&season=2&episode=1")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["domain"] == "tv"
        assert data["season"] == 2
        assert data["episode"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["cached"] is True
        assert data["results"][0]["audio"] == "Dolby Atmos"
        assert "5000" in route.calls.last.request.url.params["categories"]


def test_api_search_graceful_degradation_when_alldebrid_fails(search_test_env):
    """Verify /api/search returns results cleanly even if AllDebrid API fails or times out."""
    prowlarr_releases = [
        {
            "title": "Gladiator.II.2024.1080p.WEB-DL",
            "indexer": "PublicTracker",
            "size": 4000000000,
            "seeders": 95,
            "downloadUrl": "magnet:?xt=urn:btih:gladhash111111111111111111111111111111111111&dn=Gladiator.II",
            "guid": "guid-glad-1",
        }
    ]

    with respx.mock:
        respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_releases)
        # AllDebrid returns 500 error
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(500)

        response = search_test_env.get("/api/search?query=Gladiator%20II&domain=movies")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["results"]) == 1
        # Should gracefully treat as uncached rather than failing the search request
        assert data["results"][0]["cached"] is False
        assert data["results"][0]["cache_badge"] == "uncached"
