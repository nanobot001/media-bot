import pytest
from starlette.testclient import TestClient
from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.db.stream_history_repo import StreamHistoryRepository
from moviebot.adapters.alldebrid_client import AllDebridClient


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
