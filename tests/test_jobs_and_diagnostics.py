import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from moviebot.config import settings
from moviebot.db.repositories import DownloadJobRepository, ErrorLogRepository
from moviebot.tools.get_download_jobs_tool import get_download_jobs_tool
from moviebot.tools.resolve_pending_jobs_tool import resolve_pending_jobs_tool
from moviebot.tools.get_error_logs_tool import get_error_logs_tool
from moviebot.bot.discord_app import is_bot_manager


@pytest.fixture
def mock_db(tmp_path):
    """Sets up a temporary SQLite database for testing."""
    db_file = tmp_path / "test_moviebot_jobs.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


def test_download_job_repository(mock_db):
    # Create jobs
    DownloadJobRepository.create_job("job1", "magnet1", "file1.mkv", "/target", "pending")
    DownloadJobRepository.create_job("job2", "magnet2", "file2.mkv", "/target", "downloading")
    DownloadJobRepository.create_job("job3", "magnet3", "file3.mkv", "/target", "completed")

    # Verify active jobs
    active = DownloadJobRepository.get_active_jobs()
    assert len(active) == 2
    active_ids = [j["id"] for j in active]
    assert "job1" in active_ids
    assert "job2" in active_ids
    assert "job3" not in active_ids

    # Verify all jobs
    all_jobs = DownloadJobRepository.get_all_jobs(limit=10)
    assert len(all_jobs) == 3

    # Update job details
    DownloadJobRepository.update_job_details("job1", "downloading", "resolved_file.mkv")
    job1 = DownloadJobRepository.get_job("job1")
    assert job1["status"] == "downloading"
    assert job1["selected_file_name"] == "resolved_file.mkv"


@pytest.mark.asyncio
async def test_get_download_jobs_tool(mock_db):
    DownloadJobRepository.create_job("job1", "magnet1", "file1.mkv", "/target", "pending")
    DownloadJobRepository.create_job("job2", "magnet2", "file2.mkv", "/target", "completed")

    # Active only
    res = await get_download_jobs_tool(active_only=True)
    assert res["ok"] is True
    assert len(res["data"]["jobs"]) == 1
    assert res["data"]["jobs"][0]["id"] == "job1"

    # All jobs
    res_all = await get_download_jobs_tool(active_only=False, limit=5)
    assert res_all["ok"] is True
    assert len(res_all["data"]["jobs"]) == 2


@pytest.mark.asyncio
async def test_resolve_pending_jobs_tool_no_jobs(mock_db):
    res = await resolve_pending_jobs_tool()
    assert res["ok"] is True
    assert res["data"]["resolved"] == []


@pytest.mark.asyncio
async def test_resolve_pending_jobs_tool_success(mock_db):
    # Create a pending job
    DownloadJobRepository.create_job("job1", "magnet1", "Resolving metadata...", "/target", "pending")

    # Mock AllDebridClient
    mock_debrid = MagicMock()
    # Mock magnet status response
    mock_debrid.get_magnet_status = AsyncMock(return_value={
        "files": [{"id": 1, "name": "movie.mkv", "size": 10000000}],
        "links": [{"link": "http://direct-link/movie.mkv"}]
    })
    mock_debrid.unlock_link = AsyncMock(return_value="http://unlocked-link/movie.mkv")

    # Mock IdmAdapter
    mock_idm = MagicMock()
    mock_idm.send_to_idm = AsyncMock(return_value={"message": "Sent successfully"})

    with patch("moviebot.tools.resolve_pending_jobs_tool.AllDebridClient", return_value=mock_debrid), \
         patch("moviebot.tools.resolve_pending_jobs_tool.IdmAdapter", return_value=mock_idm):
        res = await resolve_pending_jobs_tool()

        assert res["ok"] is True
        assert len(res["data"]["resolved"]) == 1
        assert res["data"]["resolved"][0]["job_id"] == "job1"
        assert res["data"]["resolved"][0]["selected_file"] == "movie.mkv"

        # Verify job state changed to downloading
        job = DownloadJobRepository.get_job("job1")
        assert job["status"] == "downloading"
        assert job["selected_file_name"] == "movie.mkv"


@pytest.mark.asyncio
async def test_resolve_pending_jobs_tool_ambiguous(mock_db):
    # Create a pending job
    DownloadJobRepository.create_job("job1", "magnet1", "Resolving metadata...", "/target", "pending")

    # Mock AllDebridClient returning files within 10% size window
    mock_debrid = MagicMock()
    mock_debrid.get_magnet_status = AsyncMock(return_value={
        "files": [
            {"id": 1, "name": "movie_part1.mkv", "size": 10000000},
            {"id": 2, "name": "movie_part2.mkv", "size": 9500000}
        ],
        "links": []
    })

    with patch("moviebot.tools.resolve_pending_jobs_tool.AllDebridClient", return_value=mock_debrid):
        res = await resolve_pending_jobs_tool()

        assert res["ok"] is True
        assert len(res["data"]["ambiguous_requires_selection"]) == 1
        assert res["data"]["ambiguous_requires_selection"][0]["job_id"] == "job1"

        # Verify status transitioned to requires_selection
        job = DownloadJobRepository.get_job("job1")
        assert job["status"] == "requires_selection"


@pytest.mark.asyncio
async def test_get_error_logs_tool(mock_db):
    ErrorLogRepository.insert("search", "111", "user", "error message", "traceback")

    res = await get_error_logs_tool(limit=5)
    assert res["ok"] is True
    assert len(res["data"]["errors"]) == 1
    assert res["data"]["errors"][0]["command_name"] == "search"


def test_is_bot_manager():
    # 1. User ID Match
    with patch("moviebot.config.settings.bot_manager_user_ids", "111,222"):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock()
        interaction.user.id = 111
        assert is_bot_manager(interaction) is True

    # 2. Role ID Match
    with patch("moviebot.config.settings.bot_manager_user_ids", ""), \
         patch("moviebot.config.settings.bot_manager_role_ids", "777,888"):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock()
        interaction.user.id = 333
        mock_role = MagicMock()
        mock_role.id = 777
        interaction.user.roles = [mock_role]
        assert is_bot_manager(interaction) is True

    # 3. Fallback to Manage Guild
    with patch("moviebot.config.settings.bot_manager_user_ids", ""), \
         patch("moviebot.config.settings.bot_manager_role_ids", ""):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.user = MagicMock()
        interaction.user.id = 333
        del interaction.user.roles  # Remove roles attribute to test fallback
        
        # Test true
        interaction.permissions = MagicMock()
        interaction.permissions.manage_guild = True
        assert is_bot_manager(interaction) is True

        # Test false
        interaction.permissions.manage_guild = False
        assert is_bot_manager(interaction) is False
