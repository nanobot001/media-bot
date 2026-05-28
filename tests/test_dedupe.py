import pytest
import sqlite3
import os
from unittest.mock import patch
from moviebot.core.dedupe import normalize_title, levenshtein_ratio, evaluate_deduplication
from moviebot.db.connection import get_db_connection
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
def mock_db(tmp_path):
    """Sets up a temporary SQLite database for testing."""
    db_file = tmp_path / "test_moviebot.sqlite3"
    
    # Patch the settings database path
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


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

