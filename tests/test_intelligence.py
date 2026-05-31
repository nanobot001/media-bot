import pytest
import sqlite3
import os
import json
import datetime
from unittest.mock import patch, AsyncMock, MagicMock
from moviebot.config import settings
from moviebot.db.connection import init_db, get_db_connection
from moviebot.db.repositories import LibraryItemRepository
from moviebot.adapters.plex_client import PlexClient
from moviebot.cli.tool_cli import cmd_sync_intelligence


@pytest.fixture
def temp_db_path(tmp_path):
    """Fixture that returns a temporary database file path and patches settings."""
    db_file = tmp_path / "test_intelligence.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        yield db_file


def test_self_healing_migration(temp_db_path):
    # 1. Create a basic table mimicking the legacy schema (without new columns or FTS table/triggers)
    conn = sqlite3.connect(str(temp_db_path))
    conn.execute(
        """
        CREATE TABLE library_items (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            rating_key TEXT,
            title TEXT NOT NULL,
            normalized_title TEXT NOT NULL,
            year INTEGER,
            imdb_id TEXT,
            file_path TEXT,
            size_bytes INTEGER,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.close()

    # 2. Run init_db() to trigger self-healing migrations
    init_db()

    # 3. Check table info to verify that new columns have been added
    with get_db_connection() as check_conn:
        cursor = check_conn.execute("PRAGMA table_info(library_items)")
        columns = {row[1] for row in cursor.fetchall()}
        
        expected_new_cols = [
            "genres", "directors", "rating", "runtime", "collections",
            "resolution", "bitrate_kbps", "watch_status", "watch_count",
            "last_watched_at", "synopsis", "synopsis_hash", "metadata_refreshed_at",
            "synopsis_vector", "synopsis_vector_model", "synopsis_vector_dim",
            "synopsis_vector_updated_at"
        ]
        for col in expected_new_cols:
            assert col in columns, f"Column '{col}' was not migrated successfully."

        # Verify FTS virtual table exists
        fts_table_cursor = check_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='library_items_fts'"
        )
        assert fts_table_cursor.fetchone() is not None, "Virtual table 'library_items_fts' does not exist."

        # Verify Triggers exist
        triggers_cursor = check_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'library_items_a%'"
        )
        triggers = {row[0] for row in triggers_cursor.fetchall()}
        assert "library_items_ai" in triggers
        assert "library_items_ad" in triggers
        assert "library_items_au" in triggers


def test_fts_triggers_and_search(temp_db_path):
    # Initialize the database (which runs the full schema)
    init_db()

    # 1. Insert a movie with enriched metadata
    LibraryItemRepository.upsert(
        id="plex_111",
        source="plex",
        rating_key="111",
        title="Predator",
        normalized_title="predator",
        year=1987,
        imdb_id="tt0093773",
        file_path="/movies/Predator.mkv",
        size_bytes=1073741824,
        genres=json.dumps(["Action", "Sci-Fi"]),
        directors=json.dumps(["John McTiernan"]),
        rating=7.8,
        runtime=107,
        collections=json.dumps(["Predator Collection"]),
        resolution="1080",
        bitrate_kbps=8000,
        watch_status="watched",
        watch_count=2,
        last_watched_at="2026-05-30T12:00:00Z",
        synopsis="A team of commandos on a mission in a Central American jungle find themselves hunted by an extraterrestrial warrior.",
        synopsis_hash="fakehash1"
    )

    # Verify triggering: query library_items_fts virtual table directly
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM library_items_fts")
        fts_rows = cursor.fetchall()
        assert len(fts_rows) == 1
        assert fts_rows[0]["title"] == "Predator"
        assert "extraterrestrial" in fts_rows[0]["synopsis"]

    # 2. Test search_fts matching various fields
    # Match by title keyword
    results = LibraryItemRepository.search_fts("Predator")
    assert len(results) == 1
    assert results[0]["id"] == "plex_111"

    # Match by synopsis keyword
    results = LibraryItemRepository.search_fts("extraterrestrial")
    assert len(results) == 1
    assert results[0]["id"] == "plex_111"

    # Match by genres keyword
    results = LibraryItemRepository.search_fts("Action")
    assert len(results) == 1
    assert results[0]["id"] == "plex_111"

    # Match by directors keyword
    results = LibraryItemRepository.search_fts("McTiernan")
    assert len(results) == 1
    assert results[0]["id"] == "plex_111"

    # 3. Test automatic sync on update (upsert again)
    LibraryItemRepository.upsert(
        id="plex_111",
        source="plex",
        rating_key="111",
        title="Predator Updated",
        normalized_title="predatorupdated",
        year=1987,
        imdb_id="tt0093773",
        file_path="/movies/Predator.mkv",
        size_bytes=1073741824,
        genres=json.dumps(["Action", "Sci-Fi", "Thriller"]),
        directors=json.dumps(["John McTiernan"]),
        rating=7.9,
        runtime=107,
        synopsis="An updated synopsis about a special forces team hunted by an alien warrior in Central America.",
        synopsis_hash="fakehash2"
    )

    # Search for new keyword in synopsis
    results = LibraryItemRepository.search_fts("special forces")
    assert len(results) == 1
    assert results[0]["title"] == "Predator Updated"

    # Verify old synopsis word is no longer found
    results = LibraryItemRepository.search_fts("extraterrestrial")
    assert len(results) == 0


@pytest.mark.asyncio
async def test_sync_intelligence_cli_dry_run(temp_db_path):
    init_db()

    # Seed an item in database first
    LibraryItemRepository.upsert(
        id="plex_222",
        source="plex",
        rating_key="222",
        title="The Matrix",
        normalized_title="matrix",
        year=1999,
        imdb_id="tt0133093",
        file_path="/movies/Matrix.mkv",
        size_bytes=5000
    )

    mock_details = {
        "id": "plex_222",
        "source": "plex",
        "rating_key": "222",
        "title": "The Matrix",
        "year": 1999,
        "imdb_id": "tt0133093",
        "file_path": "/movies/Matrix.mkv",
        "size_bytes": 5000,
        "genres": json.dumps(["Action", "Sci-Fi"]),
        "directors": json.dumps(["Lana Wachowski", "Lilly Wachowski"]),
        "rating": 8.7,
        "runtime": 136,
        "collections": json.dumps(["The Matrix Collection"]),
        "resolution": "4k",
        "bitrate_kbps": 15000,
        "watch_status": "unwatched",
        "watch_count": 0,
        "last_watched_at": None,
        "synopsis": "A computer hacker learns from mysterious rebels about the true nature of his reality.",
        "synopsis_hash": "matrixhash123"
    }

    # Test Dry-Run (Default)
    args = MagicMock()
    args.no_dry_run = False  # means dry-run is True

    with patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_details
        
        status = await cmd_sync_intelligence(args)
        assert status == 0
        mock_fetch.assert_called_once_with("222")

    # Verify that database has NOT been updated with the intelligence fields (since dry-run is True)
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM library_items WHERE id = 'plex_222'")
        row = dict(cursor.fetchone())
        assert row["genres"] is None
        assert row["directors"] is None
        assert row["synopsis"] is None


@pytest.mark.asyncio
async def test_sync_intelligence_cli_real_mode(temp_db_path):
    init_db()

    # Seed an item in database
    LibraryItemRepository.upsert(
        id="plex_222",
        source="plex",
        rating_key="222",
        title="The Matrix",
        normalized_title="matrix",
        year=1999,
        imdb_id="tt0133093",
        file_path="/movies/Matrix.mkv",
        size_bytes=5000
    )

    mock_details = {
        "id": "plex_222",
        "source": "plex",
        "rating_key": "222",
        "title": "The Matrix",
        "year": 1999,
        "imdb_id": "tt0133093",
        "file_path": "/movies/Matrix.mkv",
        "size_bytes": 5000,
        "genres": json.dumps(["Action", "Sci-Fi"]),
        "directors": json.dumps(["Lana Wachowski", "Lilly Wachowski"]),
        "rating": 8.7,
        "runtime": 136,
        "collections": json.dumps(["The Matrix Collection"]),
        "resolution": "4k",
        "bitrate_kbps": 15000,
        "watch_status": "unwatched",
        "watch_count": 0,
        "last_watched_at": None,
        "synopsis": "A computer hacker learns from mysterious rebels about the true nature of his reality.",
        "synopsis_hash": "matrixhash123"
    }

    # Test Real Mode (no-dry-run)
    args = MagicMock()
    args.no_dry_run = True  # dry-run is False

    with patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_details
        
        status = await cmd_sync_intelligence(args)
        assert status == 0
        mock_fetch.assert_called_once_with("222")

    # Verify that database HAS been updated with the intelligence fields
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM library_items WHERE id = 'plex_222'")
        row = dict(cursor.fetchone())
        assert json.loads(row["genres"]) == ["Action", "Sci-Fi"]
        assert json.loads(row["directors"]) == ["Lana Wachowski", "Lilly Wachowski"]
        assert row["rating"] == 8.7
        assert row["synopsis"] == "A computer hacker learns from mysterious rebels about the true nature of his reality."
        assert row["synopsis_hash"] == "matrixhash123"
        assert row["metadata_refreshed_at"] is not None
