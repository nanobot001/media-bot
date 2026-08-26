import pytest
from starlette.testclient import TestClient
from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.adapters.alldebrid_client import AllDebridClient


@pytest.fixture
def client(monkeypatch, tmp_path):
    movies_db = tmp_path / "transfer_movies.sqlite3"
    tv_db = tmp_path / "transfer_tv.sqlite3"
    tv_classic_db = tmp_path / "transfer_tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))
    monkeypatch.setattr(settings, "alldebrid_api_key", "mock")

    init_db()
    return TestClient(app)


@pytest.mark.asyncio
async def test_alldebrid_get_cloud_transfers_mock():
    ad = AllDebridClient()
    ad.api_key = "mock"

    transfers = await ad.get_cloud_transfers()
    assert len(transfers) >= 1
    t = transfers[0]
    assert "id" in t
    assert "progress_percent" in t
    assert "speed_formatted" in t
    assert "eta_formatted" in t
    assert "stage_label" in t
    assert t["progress_percent"] == 50.0
    assert t["speed_formatted"] == "15.0 MB/s"
    assert "remaining" in t["eta_formatted"]


@pytest.mark.asyncio
async def test_alldebrid_delete_cloud_transfer_mock():
    ad = AllDebridClient()
    ad.api_key = "mock"

    res = await ad.delete_cloud_transfer("mock-transfer-1")
    assert res is True


def test_api_cloud_transfers_and_notifications_endpoints(client):
    # 1. Get cloud transfers
    res = client.get("/api/cloud/transfers")
    assert res.status_code == 200
    data = res.json()
    assert data["ok"] is True
    assert "transfers" in data
    assert len(data["transfers"]) >= 1

    # 2. Get cloud notifications
    res_notif = client.get("/api/cloud/notifications")
    assert res_notif.status_code == 200
    notif_data = res_notif.json()
    assert notif_data["ok"] is True
    assert "notifications" in notif_data
    assert "unread_count" in notif_data

    # 3. Delete cloud transfer
    res_del = client.delete("/api/cloud/transfers/mock-transfer-1")
    assert res_del.status_code == 200
    assert res_del.json()["ok"] is True
