from __future__ import annotations
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from moviebot.core.pipeline_status import PipelineStatus, PipelineStatusService, PipelineStage, create_status_embed
from moviebot.db.repositories import DownloadJobRepository, LibraryItemRepository, SearchResultRepository


@pytest.fixture
def mock_db(tmp_path):
    """Sets up a temporary SQLite database for testing."""
    db_file = tmp_path / "test_pipeline_status.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


def test_parse_title_year():
    service = PipelineStatusService()
    
    t, y = service.parse_title_year("Predator.Badlands.2025.1080p.mkv")
    assert t == "Predator Badlands"
    assert y == 2025
    
    t, y = service.parse_title_year("Inception (2010) [Bluray].mp4")
    assert t == "Inception"
    assert y == 2010

    t, y = service.parse_title_year("Gladiator.II.1080p.mkv")
    assert t == "Gladiator II"
    assert y is None


@pytest.mark.asyncio
async def test_get_status_plex_shortcut(mock_db):
    # Setup mock library items
    LibraryItemRepository.upsert(
        id="plex123",
        source="plex",
        rating_key="12345",
        title="Inception",
        normalized_title="inception",
        year=2010,
        imdb_id="tt1375666",
        file_path="/movies/Inception.2010.mkv",
        size_bytes=100000
    )
    
    DownloadJobRepository.create_job(
        id="job123",
        alldebrid_magnet_id="magnet123",
        selected_file_name="Inception.2010.mkv",
        target_dir="/target",
        status="downloading"
    )
    
    service = PipelineStatusService()
    status = await service.get_status("job123")
    
    assert status.stage == PipelineStage.IN_PLEX
    assert status.title == "Inception"
    assert status.year == 2010


@pytest.mark.asyncio
async def test_get_status_stages(mock_db):
    # Create the job
    DownloadJobRepository.create_job(
        id="job999",
        alldebrid_magnet_id="magnet999",
        selected_file_name="Predator.Badlands.2025.mkv",
        target_dir="/target",
        status="pending"
    )
    
    # Mock AllDebridClient
    mock_ad = MagicMock()
    mock_ad.get_magnet_status = AsyncMock(return_value={
        "status": "downloading",
        "progress": 45.5
    })
    
    # Mock MediaWatcherClient
    mock_watcher = MagicMock()
    mock_watcher.get_file_status = MagicMock(return_value=("unknown", None))
    mock_watcher.get_tracked_files = MagicMock(return_value=[])
    
    service = PipelineStatusService(watcher_client=mock_watcher, alldebrid_client=mock_ad)
    
    # 1. Test DEBRID stage
    status = await service.get_status("job999")
    assert status.stage == PipelineStage.DEBRID
    assert status.progress == 45.5
    assert "downloading" in status.status_text.lower()
    
    # 2. Test DOWNLOADING stage
    DownloadJobRepository.update_status("job999", "downloading")
    status = await service.get_status("job999")
    assert status.stage == PipelineStage.DOWNLOADING
    
    # 3. Test IN_FOLDER stage (watcher tracking but not stable)
    mock_watcher.get_file_status = MagicMock(return_value=("tracking", None))
    mock_watcher.get_tracked_files = MagicMock(return_value=[
        {"filename": "Predator.Badlands.2025.mkv", "stable": False}
    ])
    status = await service.get_status("job999")
    assert status.stage == PipelineStage.IN_FOLDER
    
    # 4. Test FILEBOT stage (watcher tracking and stable)
    mock_watcher.get_tracked_files = MagicMock(return_value=[
        {"filename": "Predator.Badlands.2025.mkv", "stable": True}
    ])
    status = await service.get_status("job999")
    assert status.stage == PipelineStage.FILEBOT
    
    # 5. Test FILEBOT stage (watcher processed)
    mock_watcher.get_file_status = MagicMock(return_value=("processed", None))
    mock_watcher.get_tracked_files = MagicMock(return_value=[])
    status = await service.get_status("job999")
    assert status.stage == PipelineStage.FILEBOT
    
    # 6. Test ERROR stage (watcher failed)
    mock_watcher.get_file_status = MagicMock(return_value=("failed", "FileBot failed"))
    status = await service.get_status("job999")
    assert status.stage == PipelineStage.ERROR
    assert status.error_message == "FileBot failed"


@pytest.mark.asyncio
async def test_create_status_embed(mock_db):
    status = PipelineStatus(
        job_id="job_emb",
        stage=PipelineStage.DOWNLOADING,
        status_text="Downloading now",
        progress=88.2,
        file_name="Predator.Badlands.2025.mkv",
        title="Predator Badlands",
        year=2025
    )
    
    embed = create_status_embed(status)
    assert embed.title == "⏳ Ingestion Pipeline: Predator Badlands (2025)"
    assert "Downloading now" in embed.description
    assert any("Downloading (IDM)" in f.name for f in embed.fields)
    assert "Job ID: job_emb" in embed.footer.text
