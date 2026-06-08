import pytest
import shutil
import uuid
from pathlib import Path
from unittest.mock import patch
from moviebot.core.dedupe import normalize_title, levenshtein_ratio, evaluate_deduplication
from moviebot.db.repositories import LibraryItemRepository


def test_normalize_title():
    assert normalize_title("The Matrix: Resurrections (2021)!!") == "matrixresurrections"
    assert normalize_title("Avatar: The Way of Water") == "avatarwayofwater"
    assert normalize_title("A Quiet Place Part II (2020)") == "quietplacepartii"


def test_levenshtein_ratio():
    assert levenshtein_ratio("matrix", "matrix") == 1.0
    assert levenshtein_ratio("matrix", "matrices") == 0.625  # distance = 3, max_len = 8, 1 - 3/8 = 0.625
    assert levenshtein_ratio("", "") == 1.0


@pytest.fixture
def mock_db():
    """Sets up a temporary SQLite database for testing."""
    scratch_dir = Path("scratch") / "dedupe-tests" / uuid.uuid4().hex
    scratch_dir.mkdir(parents=True, exist_ok=True)
    db_file = scratch_dir / "test_moviebot.sqlite3"
    
    # Patch the settings database path
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        try:
            yield db_file
        finally:
            shutil.rmtree(scratch_dir, ignore_errors=True)


def test_evaluate_deduplication(mock_db):
    # Seed the mock database
    LibraryItemRepository.upsert(
        id="plex_123",
        source="plex",
        rating_key="123",
        title="The Matrix",
        normalized_title="matrix",
        year=1999,
        imdb_id="tt0133093",
        file_path="F:\\movies\\Matrix.mkv",
        size_bytes=100000
    )
    LibraryItemRepository.upsert(
        id="plex_456",
        source="plex",
        rating_key="456",
        title="The Matrix Resurrections",
        normalized_title="matrixresurrections",
        year=2021,
        imdb_id="tt10838180",
        file_path="F:\\movies\\MatrixResurrections.mkv",
        size_bytes=200000
    )
    LibraryItemRepository.upsert(
        id="plex_789",
        source="plex",
        rating_key="789",
        title="Dune: Part One",
        normalized_title="dunepartone",
        year=2021,
        imdb_id="tt1160419",
        file_path="F:\\movies\\DunePartOne.mkv",
        size_bytes=700000
    )

    # 1. Test exact_guid match
    tier, action, details, item = evaluate_deduplication("The Matrix Reloaded", 2003, imdb_id="tt0133093")
    assert tier == "exact_guid"
    assert action == "block"

    # 2. Test exact_title_year match
    tier, action, details, item = evaluate_deduplication("The Matrix", 1999)
    assert tier == "exact_title_year"
    assert action == "block"

    # 3. Test fuzzy_likely match (matrixresurrections vs matrxresurrections, year within range)
    tier, action, details, item = evaluate_deduplication("Matrx Resurrections", 2021)
    assert tier == "fuzzy_likely"
    assert action == "warn"

    # 4. Test not_found match
    tier, action, details, item = evaluate_deduplication("Inception", 2010)
    assert tier == "not_found"
    assert action == "allow"

    # 5. Test contained canonical title match (Dune vs Dune: Part One)
    tier, action, details, item = evaluate_deduplication("Dune", 2021)
    assert tier == "contained_title_year"
    assert action == "block"
    assert item["title"] == "Dune: Part One"


def test_quality_upgrade(mock_db):
    # Seed a 1080p movie
    LibraryItemRepository.upsert(
        id="plex_789",
        source="plex",
        rating_key="789",
        title="Interstellar",
        normalized_title="interstellar",
        year=2014,
        imdb_id="tt0816692",
        file_path="F:\\movies\\Interstellar.mkv",
        size_bytes=10 * 1024**3,  # 10 GB
        resolution="1080p",
        bitrate_kbps=8000
    )

    # 1. Higher resolution (2160p) with valid size & bitrate -> ALLOWED (upgrade_eligible)
    tier, action, details, item = evaluate_deduplication(
        "Interstellar", 2014, imdb_id="tt0816692",
        incoming_resolution="2160p",
        incoming_size_bytes=15 * 1024**3,
        incoming_bitrate_kbps=15000
    )
    assert tier == "upgrade_eligible"
    assert action == "allow"
    assert "higher resolution" in details

    # Check that the upgrade_allowed event was inserted
    from moviebot.db.repositories import EventRepository
    events = EventRepository.get_all()
    assert len(events) > 0
    assert events[0]["event_type"] == "upgrade_allowed"
    assert "Interstellar" in events[0]["title"]

    # 2. Higher resolution (2160p) but suspiciously small size -> BLOCKED (exact_guid / exact_title_year)
    tier, action, details, item = evaluate_deduplication(
        "Interstellar", 2014, imdb_id="tt0816692",
        incoming_resolution="2160p",
        incoming_size_bytes=2 * 1024**3,  # 2 GB (suspiciously small for 4k/2160p, min 3GB)
        incoming_bitrate_kbps=15000
    )
    assert tier == "exact_guid"
    assert action == "block"
    assert "suspiciously small" in details

    # 3. Same resolution (1080p) but significantly better size (1.5x) -> ALLOWED (upgrade_eligible)
    tier, action, details, item = evaluate_deduplication(
        "Interstellar", 2014, imdb_id="tt0816692",
        incoming_resolution="1080p",
        incoming_size_bytes=16 * 1024**3,  # 16 GB vs 10 GB (1.6x)
        incoming_bitrate_kbps=8000
    )
    assert tier == "upgrade_eligible"
    assert action == "allow"
    assert "significantly better" in details

    # 4. Same resolution (1080p) but similar size -> BLOCKED
    tier, action, details, item = evaluate_deduplication(
        "Interstellar", 2014, imdb_id="tt0816692",
        incoming_resolution="1080p",
        incoming_size_bytes=11 * 1024**3,  # 11 GB vs 10 GB (1.1x)
        incoming_bitrate_kbps=8000
    )
    assert tier == "exact_guid"
    assert action == "block"
    assert "similar or worse quality metrics" in details

    # 5. Missing incoming details (None) -> BLOCKED
    tier, action, details, item = evaluate_deduplication(
        "Interstellar", 2014, imdb_id="tt0816692"
    )
    assert tier == "exact_guid"
    assert action == "block"
    assert "No incoming quality evidence provided" in details
