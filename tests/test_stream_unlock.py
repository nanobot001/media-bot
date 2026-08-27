import pytest
from starlette.testclient import TestClient
from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.db.stream_history_repo import StreamHistoryRepository
from moviebot.adapters.alldebrid_client import AllDebridClient
from moviebot.api import web_routes


@pytest.fixture
def client(monkeypatch, tmp_path):
    movies_db = tmp_path / "stream_movies.sqlite3"
    tv_db = tmp_path / "stream_tv.sqlite3"
    tv_classic_db = tmp_path / "stream_tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))
    monkeypatch.setattr(settings, "alldebrid_api_key", "mock")

    init_db()
    return TestClient(app)


def test_stream_history_repository_lifecycle(client):
    stream_id = "movies:test_film:0:0"
    
    # 1. Upsert initial stream session
    StreamHistoryRepository.upsert(
        id=stream_id,
        domain="movies",
        title="Test Film",
        season=0,
        episode=0,
        release_title="Test.Film.2024.1080p.mkv",
        stream_url="https://alldebrid.mock/stream/test",
        duration_seconds=7200.0,
        progress_seconds=120.0,
        player_type="web"
    )

    item = StreamHistoryRepository.get_by_id(stream_id)
    assert item is not None
    assert item["title"] == "Test Film"
    assert item["duration_seconds"] == 7200.0
    assert item["progress_seconds"] == 120.0
    assert item["completed"] == 0

    # 2. Update progress to 95% (should mark completed)
    updated = StreamHistoryRepository.update_progress(
        id=stream_id,
        progress_seconds=6900.0,
        duration_seconds=7200.0
    )
    assert updated is not None
    assert updated["progress_percent"] >= 90.0
    assert updated["completed"] == 1

    # 3. Retrieve recent
    recents = StreamHistoryRepository.get_recent(limit=10, domain="movies")
    assert len(recents) >= 1
    assert any(r["id"] == stream_id for r in recents)

    # 4. Delete
    deleted = StreamHistoryRepository.delete(stream_id)
    assert deleted is True
    assert StreamHistoryRepository.get_by_id(stream_id) is None


@pytest.mark.asyncio
async def test_alldebrid_client_mock_stream_unlock():
    ad_client = AllDebridClient()
    ad_client.api_key = "mock"
    
    res = await ad_client.unlock_magnet_stream(
        magnet_link="magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12",
        season=1,
        episode=1
    )
    assert "stream_url" in res
    assert res["stream_url"].startswith("http")
    assert "filename" in res
    assert len(res["all_files"]) >= 1


@pytest.mark.asyncio
async def test_alldebrid_client_mock_cache_to_cloud():
    ad_client = AllDebridClient()
    ad_client.api_key = "mock"

    res = await ad_client.cache_to_cloud(
        magnet_link="magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12"
    )
    assert "id" in res
    assert res["status"] in ("Downloading", "Ready")


def test_api_stream_endpoints(client):
    # 1. Unlock stream endpoint
    unlock_payload = {
        "title": "Inception",
        "domain": "movies",
        "season": 0,
        "episode": 0,
        "magnet_url": "magnet:?xt=urn:btih:0123456789abcdef0123456789abcdef01234567&dn=Inception.2010.1080p",
        "player_type": "web"
    }
    res = client.post("/api/stream/unlock", json=unlock_payload)
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "stream_url" in data
    stream_id = data["stream_id"]

    # 2. Progress heartbeat endpoint
    prog_payload = {
        "id": stream_id,
        "progress_seconds": 450.0,
        "duration_seconds": 9000.0,
        "completed": False
    }
    res_prog = client.post("/api/stream/progress", json=prog_payload)
    assert res_prog.status_code == 200
    assert res_prog.json()["ok"] is True

    # 3. Stream history endpoint
    res_hist = client.get("/api/stream/history?limit=10")
    assert res_hist.status_code == 200
    hist_data = res_hist.json()
    assert hist_data["ok"] is True
    assert len(hist_data["streams"]) >= 1

    # 4. Cloud pre-cache endpoint
    cloud_payload = {
        "title": "The Matrix",
        "domain": "movies",
        "season": 0,
        "magnet_url": "magnet:?xt=urn:btih:9876543210fedcba9876543210fedcba98765432&dn=The.Matrix.1999"
    }
    res_cloud = client.post("/api/cloud/pre-cache", json=cloud_payload)
    assert res_cloud.status_code == 200
    assert res_cloud.json()["ok"] is True

    # 5. Active cloud transfers endpoint
    res_trans = client.get("/api/cloud/transfers")
    assert res_trans.status_code == 200
    assert res_trans.json()["ok"] is True

    # 6. Delete stream history endpoint
    res_del = client.delete(f"/api/stream/history/{stream_id}")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True


def test_api_stream_unlock_search_includes_movie_year(client, monkeypatch):
    search_calls = []
    magnet_url = "magnet:?xt=urn:btih:abcdef1234567890abcdef1234567890abcdef12&dn=The.Sheep.Detectives.2026.1080p"

    async def fake_search_sources_tool(**kwargs):
        search_calls.append(kwargs)
        return {
            "ok": True,
            "data": {
                "results": [
                    {
                        "reference_id": magnet_url,
                        "title": "The.Sheep.Detectives.2026.1080p.x264",
                    }
                ]
            },
        }

    monkeypatch.setattr(web_routes, "search_sources_tool", fake_search_sources_tool)

    response = client.post(
        "/api/stream/unlock",
        json={
            "title": "The Sheep Detectives",
            "year": 2026,
            "domain": "movies",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert search_calls[0]["query"] == "The Sheep Detectives 2026"


def test_api_stream_unlock_prefers_cached_browser_release(client, monkeypatch):
    h264 = "magnet:?xt=urn:btih:h264hash12345678901234567890123456789012"
    hevc = "magnet:?xt=urn:btih:hevchash12345678901234567890123456789012"
    selected = []

    async def fake_search_sources_tool(**kwargs):
        return {
            "ok": True,
            "data": {
                "results": [
                    {"reference_id": hevc, "title": "Example.2020.2160p.WEB-DL.HEVC"},
                    {"reference_id": h264, "title": "Example.2020.1080p.WEB-DL.H.264.AAC"},
                ]
            },
        }

    class FakeAllDebridClient:
        async def instant_check(self, magnets):
            return {"magnets": [{"magnet": hevc, "instant": True}, {"magnet": h264, "instant": True}]}

        async def unlock_magnet_stream(self, magnet_link, **kwargs):
            selected.append(magnet_link)
            return {
                "stream_url": "https://example.test/stream.mp4",
                "filename": "Example.2020.1080p.WEB-DL.H.264.AAC.mp4",
                "filesize": 10,
                "mime_type": "video/mp4",
                "file_id": 1,
                "subtitles": [],
                "all_files": [],
            }

    monkeypatch.setattr(web_routes, "search_sources_tool", fake_search_sources_tool)
    monkeypatch.setattr("moviebot.adapters.alldebrid_client.AllDebridClient", FakeAllDebridClient)

    response = client.post(
        "/api/stream/unlock",
        json={"title": "Example", "year": 2020, "domain": "movies"},
    )

    assert response.status_code == 200
    assert response.json()["browser_stream_ready"] is True
    assert response.json()["instant_cached"] is True
    assert response.json()["cloud_cached"] is True
    assert selected == [h264]


def test_api_stream_unlock_direct_magnet_persists_browser_proof(client, monkeypatch):
    magnet_url = "magnet:?xt=urn:btih:directbrowser12345678901234567890123456789012"

    class FakeAllDebridClient:
        async def unlock_magnet_stream(self, magnet_link, **kwargs):
            assert magnet_link == magnet_url
            return {
                "stream_url": "https://example.test/direct-browser.mp4",
                "filename": "The.Mandalorian.and.Grogu.2026.1080p.WEB-DL.H264.AAC.mp4",
                "filesize": 10,
                "mime_type": "video/mp4",
                "file_id": 1,
                "subtitles": [],
                "all_files": [],
            }

    monkeypatch.setattr("moviebot.adapters.alldebrid_client.AllDebridClient", FakeAllDebridClient)

    response = client.post(
        "/api/stream/unlock",
        json={
            "title": "The Mandalorian and Grogu",
            "year": 2026,
            "domain": "movies",
            "magnet_url": magnet_url,
        },
    )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["browser_stream_ready"] is True
    assert data["instant_cached"] is True


def test_api_stream_unlock_marks_mkv_ddp_release_external_only(client, monkeypatch):
    mutiny = "magnet:?xt=urn:btih:mutinyhash12345678901234567890123456789012"

    async def fake_search_sources_tool(**kwargs):
        return {
            "ok": True,
            "data": {
                "results": [
                    {
                        "reference_id": mutiny,
                        "title": "Mutiny.2026.1080p.AMZN.WEB-DL.DDP5.1.H.264-ppkhoa.mkv",
                    }
                ]
            },
        }

    class FakeAllDebridClient:
        async def instant_check(self, magnets):
            return {"magnets": [{"magnet": mutiny, "instant": True}]}

        async def unlock_magnet_stream(self, magnet_link, **kwargs):
            return {
                "stream_url": "https://example.test/mutiny.mkv",
                "filename": "Mutiny.2026.1080p.AMZN.WEB-DL.DDP5.1.H.264-ppkhoa.mkv",
                "filesize": 10,
                "mime_type": "video/x-matroska",
                "file_id": 1,
                "subtitles": [],
                "all_files": [],
            }

    monkeypatch.setattr(web_routes, "search_sources_tool", fake_search_sources_tool)
    monkeypatch.setattr("moviebot.adapters.alldebrid_client.AllDebridClient", FakeAllDebridClient)

    response = client.post(
        "/api/stream/unlock",
        json={"title": "Mutiny", "year": 2026, "domain": "movies"},
    )

    assert response.status_code == 200
    assert response.json()["browser_stream_ready"] is False
    assert response.json()["instant_cached"] is False
    assert response.json()["cloud_cached"] is True
