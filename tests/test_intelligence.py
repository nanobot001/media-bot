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


def test_embeddings_and_similarity():
    from moviebot.core.embeddings import (
        encode_vector,
        decode_vector,
        cosine_similarity,
        get_mock_embedding,
    )

    # 1. Test binary serialization/deserialization
    vec = [float(i) / 1000.0 for i in range(768)]
    blob = encode_vector(vec)
    assert len(blob) == 768 * 4
    decoded = decode_vector(blob)
    assert len(decoded) == 768
    for original, dec in zip(vec, decoded):
        assert abs(original - dec) < 1e-5

    with pytest.raises(ValueError):
        encode_vector([1.0] * 767)
    with pytest.raises(ValueError):
        decode_vector(b"\x00" * 100)

    # 2. Test cosine similarity
    v1 = [1.0, 0.0, 0.0]
    v2 = [1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v1, v2) - 1.0) < 1e-9

    v3 = [0.0, 1.0, 0.0]
    assert abs(cosine_similarity(v1, v3) - 0.0) < 1e-9

    v4 = [-1.0, 0.0, 0.0]
    assert abs(cosine_similarity(v1, v4) - (-1.0)) < 1e-9

    # 3. Test mock embedding L2 normalization & determinism
    mock_vec1 = get_mock_embedding("Hello World")
    mock_vec2 = get_mock_embedding("Hello World")
    mock_vec3 = get_mock_embedding("Goodbye World")

    assert len(mock_vec1) == 768
    # check L2 norm
    norm = sum(x * x for x in mock_vec1) ** 0.5
    assert abs(norm - 1.0) < 1e-5

    # check determinism
    assert mock_vec1 == mock_vec2
    # check differences
    assert mock_vec1 != mock_vec3


@pytest.mark.asyncio
async def test_api_embeddings_gemini_and_ollama():
    import respx
    import httpx
    from httpx import Response
    from moviebot.core.embeddings import (
        get_embedding,
        get_configured_model,
        get_mock_embedding,
    )

    # Case A: Gemini config is set
    with patch("moviebot.config.settings.gemini_api_key", "test_gemini_key"):
        assert get_configured_model() == "text-embedding-004"

        # Mock Gemini success
        with respx.mock:
            respx.post("https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key=test_gemini_key").mock(
                return_value=Response(200, json={"embedding": {"values": [0.5] * 768}})
            )
            v = await get_embedding("test")
            assert v == [0.5] * 768

        # Mock Gemini failure fallback to Ollama
        with respx.mock:
            respx.post("https://generativelanguage.googleapis.com/v1beta/models/text-embedding-004:embedContent?key=test_gemini_key").mock(
                return_value=Response(500)
            )
            respx.post("http://localhost:11434/api/embeddings").mock(
                return_value=Response(200, json={"embedding": [0.25] * 768})
            )
            v = await get_embedding("test")
            assert v == [0.25] * 768

    # Case B: Only Ollama is set
    with patch("moviebot.config.settings.gemini_api_key", ""), \
         patch("moviebot.config.settings.ollama_url", "http://localhost:11434"), \
         patch("moviebot.config.settings.ollama_model", "nomic-embed-text"):
        assert get_configured_model() == "nomic-embed-text"

        with respx.mock:
            respx.post("http://localhost:11434/api/embeddings").mock(
                return_value=Response(200, json={"embedding": [0.1] * 768})
            )
            v = await get_embedding("test")
            assert v == [0.1] * 768

        # Test fallback to mock when Ollama returns invalid dimensions
        with respx.mock:
            respx.post("http://localhost:11434/api/embeddings").mock(
                return_value=Response(200, json={"embedding": [0.1] * 100})
            )
            v = await get_embedding("test")
            assert v == get_mock_embedding("test")

        # Test fallback to mock when Ollama is offline
        with respx.mock:
            respx.post("http://localhost:11434/api/embeddings").mock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            v = await get_embedding("test")
            assert v == get_mock_embedding("test")


@pytest.mark.asyncio
async def test_sync_intelligence_embedding_caching(temp_db_path):
    init_db()

    with patch("moviebot.config.settings.gemini_api_key", ""), \
         patch("moviebot.config.settings.ollama_url", "http://localhost:11434"), \
         patch("moviebot.config.settings.ollama_model", "nomic-embed-text"):

        # 1. Seed movie without embedding in database
        LibraryItemRepository.upsert(
            id="plex_333",
            source="plex",
            rating_key="333",
            title="Inception",
            normalized_title="inception",
            year=2010,
            imdb_id="tt1375666",
            file_path="/movies/Inception.mkv",
            size_bytes=6000
        )

        mock_details = {
            "id": "plex_333",
            "source": "plex",
            "rating_key": "333",
            "title": "Inception",
            "year": 2010,
            "imdb_id": "tt1375666",
            "file_path": "/movies/Inception.mkv",
            "size_bytes": 6000,
            "genres": json.dumps(["Action", "Sci-Fi"]),
            "directors": json.dumps(["Christopher Nolan"]),
            "rating": 8.8,
            "runtime": 148,
            "collections": json.dumps([]),
            "resolution": "1080p",
            "bitrate_kbps": 9000,
            "watch_status": "unwatched",
            "watch_count": 0,
            "last_watched_at": None,
            "synopsis": "A thief who steals corporate secrets through the use of dream-sharing technology.",
            "synopsis_hash": "inceptionhash1"
        }

        args = MagicMock()
        args.no_dry_run = True

        from moviebot.core.embeddings import encode_vector

        with patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch, \
             patch("moviebot.core.embeddings.get_embedding", new_callable=AsyncMock) as mock_embed:
            
            mock_fetch.return_value = mock_details
            mock_embed.return_value = [0.1] * 768

            status = await cmd_sync_intelligence(args)
            assert status == 0
            mock_fetch.assert_called_once_with("333")
            mock_embed.assert_called_once_with(mock_details["synopsis"])

        # Verify database has updated vector details
        with get_db_connection() as conn:
            row = dict(conn.execute("SELECT * FROM library_items WHERE id = 'plex_333'").fetchone())
            assert row["synopsis_vector_model"] == "nomic-embed-text"
            assert row["synopsis_vector_dim"] == 768
            assert row["synopsis_vector"] == encode_vector([0.1] * 768)

        # 2. Run sync-intelligence again with matching hash/model -> should NOT fetch new embedding (caching)
        with patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch, \
             patch("moviebot.core.embeddings.get_embedding", new_callable=AsyncMock) as mock_embed:
            
            mock_fetch.return_value = mock_details
            mock_embed.return_value = [0.2] * 768

            status = await cmd_sync_intelligence(args)
            assert status == 0
            mock_fetch.assert_called_once_with("333")
            mock_embed.assert_not_called()

        # 3. Change synopsis hash -> should fetch new embedding
        mock_details_changed = mock_details.copy()
        mock_details_changed["synopsis_hash"] = "inceptionhash2"
        mock_details_changed["synopsis"] = "A thief who steals corporate secrets using dream-sharing tech."

        with patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch, \
             patch("moviebot.core.embeddings.get_embedding", new_callable=AsyncMock) as mock_embed:
            
            mock_fetch.return_value = mock_details_changed
            mock_embed.return_value = [0.3] * 768

            status = await cmd_sync_intelligence(args)
            assert status == 0
            mock_fetch.assert_called_once_with("333")
            mock_embed.assert_called_once_with(mock_details_changed["synopsis"])

        # Verify vector updated to new value
        with get_db_connection() as conn:
            row = dict(conn.execute("SELECT * FROM library_items WHERE id = 'plex_333'").fetchone())
            assert row["synopsis_vector"] == encode_vector([0.3] * 768)
            assert row["synopsis_hash"] == "inceptionhash2"


@pytest.mark.asyncio
async def test_taste_recommender(temp_db_path):
    init_db()
    from moviebot.core.embeddings import encode_vector
    from moviebot.core.taste_profiler import generate_taste_vector, recommend_movies

    # 1. Test generate_taste_vector
    v1 = [0.1] * 768
    v2 = [0.2] * 768
    taste = generate_taste_vector([v1, v2])
    # The magnitude of average should be 1.0 because of L2 normalization
    mag = sum(x * x for x in taste) ** 0.5
    assert pytest.approx(mag) == 1.0
    # Average of equal dimensions should make all dimensions in taste equal
    assert len(taste) == 768
    assert pytest.approx(taste[0]) == taste[100]

    # Test empty vectors input
    assert generate_taste_vector([]) == [0.0] * 768

    # 2. Seed database
    # Watched: Inception (Action, Sci-Fi)
    LibraryItemRepository.upsert(
        id="plex_111",
        source="plex",
        rating_key="111",
        title="Inception",
        normalized_title="inception",
        year=2010,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        genres=json.dumps(["Action", "Sci-Fi"]),
        directors=json.dumps(["Christopher Nolan"]),
        synopsis_vector=encode_vector([0.1] * 768),
        watch_status="watched",
        watch_count=1
    )
    # Watched: Interstellar (Sci-Fi, Drama)
    LibraryItemRepository.upsert(
        id="plex_222",
        source="plex",
        rating_key="222",
        title="Interstellar",
        normalized_title="interstellar",
        year=2014,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        genres=json.dumps(["Sci-Fi", "Drama"]),
        directors=json.dumps(["Christopher Nolan"]),
        synopsis_vector=encode_vector([0.2] * 768),
        watch_status="watched",
        watch_count=1
    )
    # Unwatched: Tenet (Action, Sci-Fi) - Nolan. High match, expects top rank.
    LibraryItemRepository.upsert(
        id="plex_333",
        source="plex",
        rating_key="333",
        title="Tenet",
        normalized_title="tenet",
        year=2020,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        genres=json.dumps(["Action", "Sci-Fi"]),
        directors=json.dumps(["Christopher Nolan"]),
        synopsis_vector=encode_vector([0.15] * 768),
        watch_status="unwatched",
        watch_count=0
    )
    # Unwatched: The Notebook (Romance, Drama) - Not Nolan, dissimilar vector.
    LibraryItemRepository.upsert(
        id="plex_444",
        source="plex",
        rating_key="444",
        title="The Notebook",
        normalized_title="the notebook",
        year=2004,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        genres=json.dumps(["Romance", "Drama"]),
        directors=json.dumps(["Nick Cassavetes"]),
        synopsis_vector=encode_vector([-0.5] * 768),
        watch_status="unwatched",
        watch_count=0
    )

    with get_db_connection() as conn:
        # A. Run recommend_movies with DB fallback (Tautulli client offline/unconfigured)
        with patch("moviebot.config.settings.tautulli_api_key", None):
            recs = await recommend_movies(conn, limit=5)
            assert len(recs) == 2
            # Tenet should be #1 recommendation due to vector similarity + genres + director match
            assert recs[0]["title"] == "Tenet"
            assert recs[1]["title"] == "The Notebook"
            assert recs[0]["score"] > recs[1]["score"]

        # B. Run recommend_movies with mocked Tautulli client history query
        with patch("moviebot.config.settings.tautulli_api_key", "mock_key"), \
             patch("moviebot.adapters.tautulli_client.TautulliClient._query", new_callable=AsyncMock) as mock_query:
            
            mock_query.return_value = {
                "data": [
                    {"media_type": "movie", "rating_key": "111"},
                    {"media_type": "movie", "rating_key": "222"}
                ]
            }

            recs_tautulli = await recommend_movies(conn, user="anthony", limit=5)
            assert len(recs_tautulli) == 2
            assert recs_tautulli[0]["title"] == "Tenet"


def test_collection_gaps(temp_db_path):
    init_db()
    from moviebot.core.collection_audit import audit_collections

    # 1. Seed popular collection with a gap (John Wick 1, 2, 4 -> missing 3)
    LibraryItemRepository.upsert(
        id="plex_jw1",
        source="plex",
        rating_key="jw1",
        title="John Wick",
        normalized_title="john wick",
        year=2014,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        collections=json.dumps(["John Wick Collection"])
    )
    LibraryItemRepository.upsert(
        id="plex_jw2",
        source="plex",
        rating_key="jw2",
        title="John Wick: Chapter 2",
        normalized_title="john wick chapter 2",
        year=2017,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        collections=json.dumps(["John Wick Collection"])
    )
    LibraryItemRepository.upsert(
        id="plex_jw4",
        source="plex",
        rating_key="jw4",
        title="John Wick: Chapter 4",
        normalized_title="john wick chapter 4",
        year=2023,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        collections=json.dumps(["John Wick Collection"])
    )

    # 2. Seed arbitrary custom collection with a gap (Part 1, Part 3 -> missing Part 2)
    LibraryItemRepository.upsert(
        id="plex_cust1",
        source="plex",
        rating_key="cust1",
        title="My Custom Series: Part 1",
        normalized_title="my custom series part 1",
        year=2020,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        collections=json.dumps(["My Custom Collection"])
    )
    LibraryItemRepository.upsert(
        id="plex_cust3",
        source="plex",
        rating_key="cust3",
        title="My Custom Series: Part 3",
        normalized_title="my custom series part 3",
        year=2024,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        collections=json.dumps(["My Custom Collection"])
    )

    with get_db_connection() as conn:
        reports = audit_collections(conn)
        
        # We expect two collections with gaps
        assert len(reports) == 2
        
        # Verify John Wick Collection gaps
        jw_report = next(r for r in reports if r["collection"] == "John Wick Collection")
        assert jw_report["confidence"] == 1.0
        assert len(jw_report["missing"]) == 1
        assert jw_report["missing"][0]["index"] == 3
        assert jw_report["missing"][0]["title"] == "John Wick: Chapter 3 - Parabellum"
        
        # Verify Custom Collection gaps
        cust_report = next(r for r in reports if r["collection"] == "My Custom Collection")
        assert cust_report["confidence"] == 0.6
        assert len(cust_report["missing"]) == 1
        assert cust_report["missing"][0]["index"] == 2
        assert "Part 2" in cust_report["missing"][0]["title"]


