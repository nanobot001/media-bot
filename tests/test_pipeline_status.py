from __future__ import annotations
import shutil
import uuid
from pathlib import Path

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from moviebot.core.pipeline_status import PipelineStatus, PipelineStatusService, PipelineStage, create_status_embed
from moviebot.db.repositories import DownloadJobRepository, LibraryItemRepository, SearchResultRepository


@pytest.fixture
def mock_db():
    """Sets up a temporary SQLite database for testing."""
    scratch_dir = Path("scratch") / "pipeline-status-tests" / uuid.uuid4().hex
    scratch_dir.mkdir(parents=True, exist_ok=True)
    db_file = scratch_dir / "test_pipeline_status.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        try:
            yield db_file
        finally:
            shutil.rmtree(scratch_dir, ignore_errors=True)


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
async def test_existing_library_match_does_not_complete_active_job(mock_db):
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

    mock_watcher = MagicMock()
    mock_watcher.get_file_status = MagicMock(return_value=("unknown", None))
    mock_watcher.get_tracked_files = MagicMock(return_value=[])
    mock_plex = MagicMock()
    mock_plex.search_movie = AsyncMock(return_value=[])

    service = PipelineStatusService(watcher_client=mock_watcher, plex_client=mock_plex)
    status = await service.get_status("job123")

    assert status.stage == PipelineStage.DOWNLOADING
    assert status.title == "Inception"
    assert status.year == 2010
    mock_plex.search_movie.assert_not_awaited()


@pytest.mark.asyncio
async def test_processed_library_match_completes_job(mock_db):
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

    mock_watcher = MagicMock()
    mock_watcher.get_file_status = MagicMock(return_value=("processed", None))
    mock_watcher.get_tracked_files = MagicMock(return_value=[])

    service = PipelineStatusService(watcher_client=mock_watcher)
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
    
    # Mock PlexClient
    mock_plex = MagicMock()
    mock_plex.search_movie = AsyncMock(return_value=[])
    mock_plex.refresh_movie_sections = AsyncMock()
    
    service = PipelineStatusService(watcher_client=mock_watcher, alldebrid_client=mock_ad, plex_client=mock_plex)
    
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
    assert "Downloading (IDM)" in embed.description
    assert "Job ID: job_emb" in embed.footer.text


@pytest.mark.asyncio
async def test_create_status_embed_ticks_and_layout(mock_db):
    import datetime
    five_mins_ago = (datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None) - datetime.timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
    
    status = PipelineStatus(
        job_id="job_ticks",
        stage=PipelineStage.DOWNLOADING,
        status_text="Downloading with ticks",
        progress=50.0,
        file_name="Movie.mkv",
        title="Movie Title",
        year=2026,
        created_at=five_mins_ago
    )
    
    embed = create_status_embed(status)
    assert "Movie Title (2026)" in embed.title
    # Verify table formatting has vertical separators
    assert "`Debrid Cache       |`" in embed.description
    assert "`Downloading (IDM)  |` 🟡 Active" in embed.description
    # Verify ticks display for 5 minutes ago (minutes + 1 = 6 ticks)
    assert "▰▰▰▰▰▰" in embed.description
    assert "5m" in embed.description
