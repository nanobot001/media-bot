import pytest
import shutil
import sqlite3
from pathlib import Path
from unittest.mock import patch
import uuid

from moviebot.db.connection import get_db_connection, init_db, CANONICAL_DOMAINS


@pytest.fixture
def temp_db_paths():
    """Sets up a temporary directory structure and patches all database path settings."""
    scratch_dir = Path("scratch") / "router-tests" / uuid.uuid4().hex
    scratch_dir.mkdir(parents=True, exist_ok=True)
    
    movies_db = scratch_dir / "movies.sqlite3"
    anime_db = scratch_dir / "anime.sqlite3"
    tv_db = scratch_dir / "tv.sqlite3"
    tv_classic_db = scratch_dir / "tvclassic.sqlite3"
    
    with patch("moviebot.config.settings.database_path", str(movies_db)), \
         patch("moviebot.config.settings.anime_database_path", str(anime_db)), \
         patch("moviebot.config.settings.tv_database_path", str(tv_db)), \
         patch("moviebot.config.settings.tv_classic_database_path", str(tv_classic_db)):
        yield {
            "movies": movies_db,
            "anime": anime_db,
            "tv": tv_db,
            "tv_classic": tv_classic_db,
            "scratch_dir": scratch_dir
        }
        
    shutil.rmtree(scratch_dir, ignore_errors=True)


def test_default_routing_to_movies(temp_db_paths):
    """Calling get_db_connection() without arguments should default to the movies database."""
    conn = get_db_connection()
    try:
        # Check that the connection is a sqlite3 Connection
        assert isinstance(conn, sqlite3.Connection)
        
        # Verify it created and pointed to the movies DB path
        movies_path = temp_db_paths["movies"]
        assert movies_path.exists()
        
        # Verify WAL mode is active
        cursor = conn.execute("PRAGMA journal_mode")
        assert cursor.fetchone()[0].lower() == "wal"
    finally:
        conn.close()


def test_explicit_domain_routing(temp_db_paths):
    """Calling get_db_connection(domain) should route to the correct SQLite file for all canonical domains."""
    for domain in CANONICAL_DOMAINS:
        conn = get_db_connection(domain)
        try:
            assert isinstance(conn, sqlite3.Connection)
            expected_path = temp_db_paths[domain]
            assert expected_path.exists()
            
            cursor = conn.execute("PRAGMA journal_mode")
            assert cursor.fetchone()[0].lower() == "wal"
        finally:
            conn.close()


def test_invalid_domain_routing(temp_db_paths):
    """Calling get_db_connection with an invalid domain name should raise ValueError."""
    with pytest.raises(ValueError) as excinfo:
        get_db_connection("invalid_domain")
    assert "Invalid media domain: 'invalid_domain'" in str(excinfo.value)


def test_init_db_movies(temp_db_paths):
    """init_db() or init_db('movies') should bootstrap the full schema only for movies."""
    init_db("movies")
    
    # Check that movie schema exists in the movie database
    conn = get_db_connection("movies")
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='library_items'")
        assert cursor.fetchone() is not None
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='kv_store'")
        assert cursor.fetchone() is not None
    finally:
        conn.close()


def test_init_db_other_domains(temp_db_paths):
    """init_db(domain) for non-movie domains should create the file but NOT execute the movie SCHEMA_SQL."""
    for domain in ["anime", "tv", "tv_classic"]:
        init_db(domain)
        
        expected_path = temp_db_paths[domain]
        assert expected_path.exists()
        
        # Verify file is initialized but doesn't have movie tables
        conn = get_db_connection(domain)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='library_items'")
            assert cursor.fetchone() is None
        finally:
            conn.close()


def test_invalid_domain_init(temp_db_paths):
    """init_db with an invalid domain should raise ValueError."""
    with pytest.raises(ValueError) as excinfo:
        init_db("music")
    assert "Invalid media domain: 'music'" in str(excinfo.value)
