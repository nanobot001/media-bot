import pytest
from starlette.testclient import TestClient

from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.cache_prewarm_repo import CachePrewarmRepository
from moviebot.db.connection import init_db


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "movies.sqlite3"))
    monkeypatch.setattr(settings, "tv_database_path", str(tmp_path / "tv.sqlite3"))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tmp_path / "classic.sqlite3"))
    monkeypatch.setattr(settings, "alldebrid_api_key", "test-key")
    init_db("movies")
    init_db("tv")
    init_db("tv_classic")
    return TestClient(app)


def _search_response(results):
    return {"ok": True, "data": {"results": results}}


def test_prepare_uses_exact_cached_browser_release_without_creating_transfer(client, monkeypatch):
    async def fake_search(**kwargs):
        assert kwargs["query"] == "The Matrix"
        assert kwargs["year"] == 1999
        assert kwargs["check_cache"] is True
        return _search_response([
            {
                "title": "The.Matrix.Resurrections.2021.1080p.WEB-DL.H264.AAC.mp4",
                "reference_id": "magnet:?xt=urn:btih:wrongyear",
                "cached": True,
                "seeders": 999,
            },
            {
                "title": "The.Matrix.1999.1080p.WEB-DL.x265.DDP.mkv",
                "reference_id": "magnet:?xt=urn:btih:wrongcodec",
                "cached": True,
                "seeders": 500,
            },
            {
                "title": "The.Matrix.1999.1080p.WEB-DL.H264.AAC.mp4",
                "reference_id": "magnet:?xt=urn:btih:exactbrowser",
                "cached": True,
                "seeders": 20,
            },
        ])

    class FakeAllDebrid:
        cache_calls = []

        async def unlock_magnet_stream(self, **kwargs):
            assert "exactbrowser" in kwargs["magnet_link"]
            return {
                "filename": "The.Matrix.1999.1080p.WEB-DL.H264.AAC.mp4",
                "filesize": 1234,
            }

        async def cache_to_cloud(self, magnet_link):
            self.cache_calls.append(magnet_link)
            raise AssertionError("an already cached candidate must not be queued")

    monkeypatch.setattr("moviebot.api.web_routes.search_sources_tool", fake_search)
    monkeypatch.setattr("moviebot.adapters.alldebrid_client.AllDebridClient", FakeAllDebrid)

    response = client.post(
        "/api/stream/prepare",
        json={"domain": "movies", "title": "The Matrix", "year": 1999},
    )
    data = response.json()
    assert response.status_code == 200
    assert data["ok"] is True
    assert data["browser_stream_ready"] is True
    assert data["reference_id"].endswith("exactbrowser")
    assert FakeAllDebrid.cache_calls == []

    stored = CachePrewarmRepository.get("movies", "The Matrix", year=1999)
    assert stored["browser_stream_ready"] is True
    assert stored["stream_reference_id"].endswith("exactbrowser")
    assert client.get("/api/cloud/transfers").json()["transfers"] == []
    assert client.get("/api/cloud/notifications").json()["notifications"] == []


def test_prepare_tracks_only_manual_transfer_then_verifies_browser_file(client, monkeypatch):
    provider_state = {"ready": False}

    async def fake_search(**kwargs):
        return _search_response([
            {
                "title": "Mutiny.2026.2160p.WEB-DL.H264.AAC.mp4",
                "reference_id": "magnet:?xt=urn:btih:browsercopy",
                "cached": False,
                "seeders": 25,
            },
            {
                "title": "Mutiny.2026.1080p.WEB-DL.x265.DDP.mkv",
                "reference_id": "magnet:?xt=urn:btih:downloadcopy",
                "cached": True,
                "seeders": 500,
            },
        ])

    class FakeAllDebrid:
        async def cache_to_cloud(self, magnet_link):
            assert "browsercopy" in magnet_link
            return {"id": "manual-browser-1", "name": "Mutiny browser copy", "ready": False}

        async def get_cloud_transfers(self):
            return [
                {
                    "id": "unrelated-account-item",
                    "name": "Unrelated.Movie.mkv",
                    "ready": True,
                    "status": "Ready",
                    "progress_percent": 100,
                },
                {
                    "id": "manual-browser-1",
                    "name": "Mutiny.2026.2160p.WEB-DL.H264.AAC.mp4",
                    "ready": provider_state["ready"],
                    "status": "Ready" if provider_state["ready"] else "Downloading",
                    "progress_percent": 100 if provider_state["ready"] else 40,
                    "size": 5678,
                },
            ]

        async def unlock_magnet_stream(self, **kwargs):
            assert "browsercopy" in kwargs["magnet_link"]
            return {
                "filename": "Mutiny.2026.2160p.WEB-DL.H264.AAC.mp4",
                "filesize": 5678,
            }

    monkeypatch.setattr("moviebot.api.web_routes.search_sources_tool", fake_search)
    monkeypatch.setattr("moviebot.adapters.alldebrid_client.AllDebridClient", FakeAllDebrid)

    queued = client.post(
        "/api/stream/prepare",
        json={"domain": "movies", "title": "Mutiny", "year": 2026},
    ).json()
    assert queued["ok"] is True
    assert queued["status"] == "queued"
    assert queued["browser_stream_ready"] is False

    active = client.get("/api/cloud/transfers").json()
    assert [item["id"] for item in active["transfers"]] == ["manual-browser-1"]
    assert active["transfers"][0]["intent_purpose"] == "browser_stream"
    assert active["transfers"][0]["ready"] is False

    provider_state["ready"] = True
    notifications = client.get("/api/cloud/notifications").json()["notifications"]
    assert [item["id"] for item in notifications] == ["manual-browser-1"]
    assert notifications[0]["browser_stream_ready"] is True

    stored = CachePrewarmRepository.get("movies", "Mutiny", year=2026)
    assert stored["browser_stream_ready"] is True
    assert stored["stream_reference_id"].endswith("browsercopy")


def test_prepare_refuses_to_cache_non_browser_release(client, monkeypatch):
    async def fake_search(**kwargs):
        return _search_response([
            {
                "title": "Mutiny.2026.1080p.WEB-DL.x265.DDP.mkv",
                "reference_id": "magnet:?xt=urn:btih:downloadonly",
                "cached": False,
                "seeders": 500,
            }
        ])

    class FakeAllDebrid:
        async def cache_to_cloud(self, magnet_link):
            raise AssertionError("a non-browser release must not be queued")

    monkeypatch.setattr("moviebot.api.web_routes.search_sources_tool", fake_search)
    monkeypatch.setattr("moviebot.adapters.alldebrid_client.AllDebridClient", FakeAllDebrid)

    result = client.post(
        "/api/stream/prepare",
        json={"domain": "movies", "title": "Mutiny", "year": 2026},
    ).json()
    assert result["ok"] is False
    assert result["code"] == "NO_BROWSER_SAFE_RELEASE"
    assert "Search" in result["error"]
