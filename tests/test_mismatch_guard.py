import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from moviebot.core.mismatch_guard import MismatchGuard, clean_title, extract_year, check_mismatch
from moviebot.db.repositories import DownloadJobRepository, LibraryItemRepository, EventRepository

@pytest.fixture
def mock_db(tmp_path):
    """Sets up a temporary SQLite database for testing."""
    db_file = tmp_path / "test_moviebot_mismatch.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


def test_clean_title():
    assert clean_title("Predator.Badlands.2025.1080p.mkv") == "predator badlands"
    assert clean_title("The.Matrix.1999.Bluray.mp4") == "the matrix"
    assert clean_title("Movie: Title (2020)") == "movie title"


def test_extract_year():
    assert extract_year("Predator.Badlands.2025.1080p.mkv") == 2025
    assert extract_year("Some Movie (1998) 720p.mp4") == 1998
    assert extract_year("No Year here.mkv") is None


def test_check_mismatch():
    # Correct Match
    is_mis, score, year = check_mismatch("Predator.Badlands.2025.1080p.mkv", "Predator: Badlands", 2025)
    assert not is_mis
    assert score >= 80
    assert year == 2025

    # Mismatch: Year difference
    is_mis, score, year = check_mismatch("Predator.Badlands.2025.1080p.mkv", "Predator: Badlands", 2024)
    assert is_mis
    assert year == 2025

    # Mismatch: Low similarity score
    is_mis, score, year = check_mismatch("Predator.Badlands.2025.1080p.mkv", "Alien Romulus", 2025)
    assert is_mis


@pytest.mark.asyncio
async def test_audit_plex_item_ignored_no_plex(mock_db):
    mock_plex = MagicMock()
    mock_plex.fetch_movie_details = AsyncMock(return_value=None)
    
    guard = MismatchGuard(mock_plex)
    res = await guard.audit_plex_item("123")
    assert res["status"] == "ignored"
    assert "not found" in res["reason"]


@pytest.mark.asyncio
async def test_audit_plex_item_ignored_no_jobs(mock_db):
    mock_plex = MagicMock()
    mock_plex.fetch_movie_details = AsyncMock(return_value={
        "id": "plex_123",
        "source": "plex",
        "rating_key": "123",
        "title": "Inception",
        "year": 2010,
        "imdb_id": "tt1375666",
        "file_path": "/movies/Inception (2010).mkv",
        "size_bytes": 1000
    })
    
    guard = MismatchGuard(mock_plex)
    res = await guard.audit_plex_item("123")
    assert res["status"] == "ignored"
    assert "No completed download jobs" in res["reason"]


@pytest.mark.asyncio
async def test_audit_plex_item_correct(mock_db):
    # Insert completed download job matching the Plex movie
    DownloadJobRepository.create_job(
        id="job_abc",
        alldebrid_magnet_id="magnet_123",
        selected_file_name="Inception.2010.1080p.mkv",
        target_dir="/movies",
        status="completed"
    )

    mock_plex = MagicMock()
    mock_plex.fetch_movie_details = AsyncMock(return_value={
        "id": "plex_123",
        "source": "plex",
        "rating_key": "123",
        "title": "Inception",
        "year": 2010,
        "imdb_id": "tt1375666",
        "file_path": "/movies/Inception.2010.1080p.mkv",
        "size_bytes": 1000
    })

    guard = MismatchGuard(mock_plex)
    res = await guard.audit_plex_item("123")
    assert res["status"] == "correct"
    assert res["job_id"] == "job_abc"


@pytest.mark.asyncio
async def test_audit_plex_item_mismatch_alert(mock_db):
    # Completed download job for Predator Badlands, but Plex matched it to Predator (1987)
    DownloadJobRepository.create_job(
        id="job_xyz",
        alldebrid_magnet_id="magnet_456",
        selected_file_name="Predator.Badlands.2025.1080p.mkv",
        target_dir="/movies",
        status="completed"
    )

    mock_plex = MagicMock()
    mock_plex.fetch_movie_details = AsyncMock(return_value={
        "id": "plex_789",
        "source": "plex",
        "rating_key": "789",
        "title": "Predator",
        "year": 1987,
        "imdb_id": "tt0093773",
        "file_path": "/movies/Predator.Badlands.2025.1080p.mkv",
        "size_bytes": 1000
    })
    # Mock search matches returning nothing or low score, so it can't auto-correct
    mock_plex.get_matches = AsyncMock(return_value=[])

    guard = MismatchGuard(mock_plex)
    res = await guard.audit_plex_item("789")
    assert res["status"] == "mismatch_detected"
    assert res["job_expected_title"] == "predator badlands"
    assert res["job_expected_year"] == 2025
    assert res["plex_matched_title"] == "Predator"


@pytest.mark.asyncio
async def test_audit_plex_item_auto_corrected(mock_db):
    # Job is Predator Badlands, Plex matches Predator
    DownloadJobRepository.create_job(
        id="job_xyz",
        alldebrid_magnet_id="magnet_456",
        selected_file_name="Predator.Badlands.2025.1080p.mkv",
        target_dir="/movies",
        status="completed"
    )

    mock_plex = MagicMock()
    # Initially returns Predator (1987), after auto-correction mock fetch returns Predator Badlands
    mock_plex.fetch_movie_details = AsyncMock(side_effect=[
        {
            "id": "plex_789",
            "source": "plex",
            "rating_key": "789",
            "title": "Predator",
            "year": 1987,
            "imdb_id": "tt0093773",
            "file_path": "/movies/Predator.Badlands.2025.1080p.mkv",
            "size_bytes": 1000
        },
        {
            "id": "plex_789",
            "source": "plex",
            "rating_key": "789",
            "title": "Predator Badlands",
            "year": 2025,
            "imdb_id": "tt_new",
            "file_path": "/movies/Predator.Badlands.2025.1080p.mkv",
            "size_bytes": 1000
        }
    ])

    # Search candidates has the correct item
    mock_plex.get_matches = AsyncMock(return_value=[
        {"guid": "plex://movie/predator-badlands", "name": "Predator Badlands", "year": 2025, "score": 99}
    ])
    mock_plex.unmatch_item = AsyncMock(return_value=True)
    mock_plex.match_item = AsyncMock(return_value=True)

    guard = MismatchGuard(mock_plex)
    res = await guard.audit_plex_item("789")
    assert res["status"] == "auto_corrected"
    assert res["new_title"] == "Predator Badlands"
    
    # Verify unmatch & match were called
    mock_plex.unmatch_item.assert_called_once_with("789")
    mock_plex.match_item.assert_called_once_with(rating_key="789", guid="plex://movie/predator-badlands", name="Predator Badlands")
