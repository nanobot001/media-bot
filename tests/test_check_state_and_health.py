import os
import json
import pytest
import yaml
from unittest.mock import AsyncMock, MagicMock, patch
from moviebot.db.repositories import LibraryItemRepository, DownloadJobRepository, EventRepository
from moviebot.tools.check_movie_state_tool import check_movie_state_tool
from moviebot.tools.get_system_health_tool import get_system_health_tool
from moviebot.tools.get_tool_manifest_tool import get_tool_manifest_tool
from moviebot.tools.get_recent_events_tool import get_recent_events_tool
from moviebot.tools.tail_logs_tool import tail_logs_tool


@pytest.fixture
def mock_db(tmp_path):
    """Sets up a temporary SQLite database for testing."""
    db_file = tmp_path / "test_moviebot_diagnostics.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


@pytest.mark.asyncio
async def test_check_movie_state_tool_empty(mock_db):
    # Mock os.path.exists to return False for all paths scanned
    with patch("os.path.exists", return_value=False):
        res = await check_movie_state_tool(title="Inception", year=2010)
        assert res["ok"] is True
        data = res["data"]
        assert data["in_plex"] is False
        assert len(data["plex_matches"]) == 0
        assert len(data["jobs"]) == 0
        assert len(data["intake_files"]) == 0
        assert len(data["destination_files"]) == 0
        assert len(data["watcher_logs"]) == 0


@pytest.mark.asyncio
async def test_check_movie_state_tool_matches(mock_db):
    # Insert LibraryItem and DownloadJob
    LibraryItemRepository.upsert(
        id="plex123",
        source="plex",
        rating_key="12345",
        title="Inception",
        normalized_title="inception",
        year=2010,
        imdb_id="tt1375666",
        file_path="/movies/Inception.mkv",
        size_bytes=100000000
    )
    DownloadJobRepository.create_job("job999", "magnet123", "Inception.2010.mkv", "/target", "pending")

    # Mock AllDebridClient
    mock_ad = MagicMock()
    mock_ad.get_magnet_status = AsyncMock(return_value={
        "status": "downloading",
        "progress": 45
    })

    # Side effect for os.path.exists
    def exists_side_effect(path):
        if any(x in path for x in ["_temp", "Media", "watcher"]):
            return True
        return False

    # Mock os.scandir
    mock_entry = MagicMock()
    mock_entry.name = "Inception.2010.1080p.mkv"
    mock_entry.is_dir = MagicMock(return_value=False)
    mock_entry.stat = MagicMock(return_value=MagicMock(st_size=5000000000))
    
    # Mock open for log parsing
    mock_file = MagicMock()
    mock_file.__enter__.return_value = ["2026-05-29 10:00:00 - INFO - watcher: Inception detected in intake folder"]

    with patch("moviebot.tools.check_movie_state_tool.AllDebridClient", return_value=mock_ad), \
         patch("os.path.exists", side_effect=exists_side_effect), \
         patch("os.scandir", return_value=[mock_entry]), \
         patch("os.walk", return_value=[("F:\\Media", [], ["Inception.2010.mkv"])]), \
         patch("os.path.isdir", return_value=False), \
         patch("os.path.isfile", return_value=True), \
         patch("os.path.getsize", return_value=8000000000), \
         patch("builtins.open", return_value=mock_file):
        
        res = await check_movie_state_tool(title="Inception", year=2010)
        assert res["ok"] is True
        data = res["data"]
        assert data["in_plex"] is True
        assert data["plex_matches"][0]["title"] == "Inception"
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["id"] == "job999"
        assert data["jobs"][0]["alldebrid_status"]["status"] == "downloading"
        assert len(data["intake_files"]) == 1
        assert data["intake_files"][0]["name"] == "Inception.2010.1080p.mkv"
        assert len(data["destination_files"]) == 1
        assert data["destination_files"][0]["name"] == "Inception.2010.mkv"
        assert len(data["watcher_logs"]) == 1
        assert "Inception detected" in data["watcher_logs"][0]


@pytest.mark.asyncio
async def test_get_system_health_tool_success():
    # Mock disk_usage
    mock_disk = (1000 * 1024 * 1024 * 1024, 400 * 1024 * 1024 * 1024, 600 * 1024 * 1024 * 1024)

    # Mock subprocess.run for PM2
    mock_proc_jlist = MagicMock()
    mock_proc_jlist.stdout = json.dumps([
        {
            "name": "media-bot",
            "pm_id": 0,
            "status": "online",
            "restart_time": 2,
            "monit": {"memory": 50 * 1024 * 1024, "cpu": 12},
            "pm_uptime": 100000
        }
    ])
    mock_proc_jlist.returncode = 0

    # Mock httpx responses
    async def client_get_side_effect(url, *args, **kwargs):
        resp = MagicMock()
        resp.status_code = 200
        if "alldebrid" in url:
            resp.json = MagicMock(return_value={"status": "success"})
        elif "idm" in url:
            resp.json = MagicMock(return_value={"status": "ok"})
        elif "tautulli" in url:
            resp.json = MagicMock(return_value={"response": {"result": "success"}})
        else:
            resp.json = MagicMock(return_value={})
        return resp

    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=client_get_side_effect)

    def exists_side_effect(path):
        if path in ["C:\\", "F:\\"]:
            return True
        return False

    with patch("shutil.disk_usage", return_value=mock_disk), \
         patch("subprocess.run", return_value=mock_proc_jlist), \
         patch("httpx.AsyncClient", return_value=mock_client), \
         patch("os.path.exists", side_effect=exists_side_effect), \
         patch("moviebot.config.settings.plex_url", "http://plex"), \
         patch("moviebot.config.settings.tautulli_url", "http://tautulli"), \
         patch("moviebot.config.settings.tautulli_api_key", "key"), \
         patch("moviebot.config.settings.prowlarr_url", "http://prowlarr"), \
         patch("moviebot.config.settings.prowlarr_api_key", "key"), \
         patch("moviebot.config.settings.alldebrid_api_key", "key"), \
         patch("moviebot.config.settings.idm_bridge_url", "http://idm"):
        
        # mock mock_client context manager
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        res = await get_system_health_tool()
        assert res["ok"] is True
        data = res["data"]
        
        # Verify disks
        assert "C" in data["disks"]
        assert "F" in data["disks"]
        assert data["disks"]["C"]["total_gb"] == 1000.0
        assert data["disks"]["C"]["free_gb"] == 600.0
        
        # Verify pm2
        assert data["pm2"]["ok"] is True
        assert len(data["pm2"]["processes"]) == 1
        assert data["pm2"]["processes"][0]["name"] == "media-bot"
        assert data["pm2"]["processes"][0]["status"] == "online"
        
        # Verify services
        assert data["services"]["plex"]["connected"] is True
        assert data["services"]["tautulli"]["connected"] is True
        assert data["services"]["prowlarr"]["connected"] is True
        assert data["services"]["alldebrid"]["connected"] is True
        assert data["services"]["idm_bridge"]["connected"] is True


@pytest.mark.asyncio
async def test_get_tool_manifest_tool(tmp_path):
    # Write a test manifest file
    temp_docs = tmp_path / "docs"
    temp_docs.mkdir()
    manifest_file = temp_docs / "tool-manifest.yaml"
    manifest_content = {
        "version": "1.0.0",
        "tools": [
            {"name": "test_tool", "description": "for testing"}
        ]
    }
    with open(manifest_file, "w", encoding="utf-8") as f:
        yaml.dump(manifest_content, f)

    with patch("os.path.exists", return_value=True), \
         patch("builtins.open", MagicMock(return_value=open(manifest_file, "r", encoding="utf-8"))):
        res = await get_tool_manifest_tool()
        assert res["ok"] is True
        assert res["data"]["version"] == "1.0.0"
        assert res["data"]["tools"][0]["name"] == "test_tool"


@pytest.mark.asyncio
async def test_get_recent_events_tool(mock_db):
    # Insert test events
    EventRepository.insert(
        event_type="test_event",
        source="unit_test",
        title="Test Title",
        summary="A test event occurred",
        severity="info"
    )

    res = await get_recent_events_tool(limit=10)
    assert res["ok"] is True
    events = res["data"]["events"]
    assert len(events) == 1
    assert events[0]["event_type"] == "test_event"
    assert events[0]["source"] == "unit_test"


@pytest.mark.asyncio
async def test_tail_logs_tool(tmp_path):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_file = log_dir / "media-watcher.log"

    # Write test logs
    lines = [f"Log line {i}" for i in range(150)]
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    # Mock mapping path to our temp file
    with patch("os.path.exists", return_value=True), \
         patch("os.path.getsize", return_value=os.path.getsize(log_file)), \
         patch("builtins.open", MagicMock(return_value=open(log_file, "r", encoding="utf-8-sig"))):
        
        # Test fetching 50 lines
        res = await tail_logs_tool(source="watcher", lines=50)
        assert res["ok"] is True
        log_lines = res["data"]["lines"]
        assert len(log_lines) == 50
        assert log_lines[0] == "Log line 100"
        assert log_lines[-1] == "Log line 149"
