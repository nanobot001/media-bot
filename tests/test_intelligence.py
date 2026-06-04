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
            "studios", "writers", "producers", "cast", "countries",
            "content_rating", "audience_rating", "tagline", "originally_available_at", "labels",
            "resolution", "bitrate_kbps", "watch_status", "watch_count",
            "last_watched_at", "synopsis", "synopsis_hash", "metadata_refreshed_at",
            "synopsis_vector", "synopsis_vector_model", "synopsis_vector_dim",
            "synopsis_vector_updated_at", "enrichment_json", "setting_locations",
            "premise_tags", "character_tags", "theme_tags", "tone_tags", "craft_tags",
            "content_warning_tags", "content_warnings_json", "field_confidence_json",
            "field_evidence_json", "enrichment_version", "enrichment_model",
            "enrichment_updated_at", "story_locations", "filming_locations",
            "production_countries", "mentioned_locations", "event_locations",
            "central_premise_tags", "subplot_tags", "protagonist_tags",
            "antagonist_tags", "supporting_character_tags", "central_theme_tags",
            "minor_theme_tags", "dominant_tone_tags", "secondary_tone_tags",
            "ending_tone_tags", "format_tags", "visual_style_tags",
            "narrative_structure_tags", "music_role_tags",
            "depicted_content_warning_tags", "discussed_content_warning_tags",
            "award_tags", "award_wins_json", "award_nominations_json",
            "acclaim_tags", "source_material_tags", "adaptation_type_tags",
            "popularity_tags", "cultural_impact_tags", "box_office_tier",
            "hard_fact_sources_json"
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


def test_plex_parser_extracts_factual_discovery_fields():
    client = PlexClient()
    parsed = client._parse_metadata_item({
        "ratingKey": "123",
        "title": "Toy Story",
        "year": 1995,
        "Studio": [{"tag": "Pixar"}],
        "Writer": [{"tag": "Joss Whedon"}],
        "Producer": [{"tag": "Ralph Guggenheim"}],
        "Role": [{"tag": "Tom Hanks"}, {"tag": "Tim Allen"}],
        "Country": [{"tag": "United States"}],
        "Label": [{"tag": "Pixar"}],
        "contentRating": "G",
        "audienceRating": 9.1,
        "tagline": "The adventure takes off!",
        "originallyAvailableAt": "1995-11-22",
        "Genre": [{"tag": "Animation"}],
        "Director": [{"tag": "John Lasseter"}],
        "Collection": [{"tag": "Toy Story Collection"}],
        "summary": "A cowboy doll is threatened by a new spaceman figure.",
    })

    assert json.loads(parsed["studios"]) == ["Pixar"]
    assert json.loads(parsed["cast"]) == ["Tom Hanks", "Tim Allen"]
    assert json.loads(parsed["writers"]) == ["Joss Whedon"]
    assert parsed["content_rating"] == "G"
    assert parsed["audience_rating"] == 9.1
    assert parsed["originally_available_at"] == "1995-11-22"


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


def test_upsert_preserves_vector_when_synopsis_hash_is_unchanged(temp_db_path):
    init_db()
    from moviebot.core.embeddings import encode_vector

    original_vector = encode_vector([0.1] * 768)
    LibraryItemRepository.upsert(
        id="plex_preserve",
        source="plex",
        rating_key="preserve",
        title="Preserve Me",
        normalized_title="preserveme",
        year=2020,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        synopsis="Original synopsis",
        synopsis_hash="samehash",
        synopsis_vector=original_vector,
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-05-31T00:00:00Z",
    )

    LibraryItemRepository.upsert(
        id="plex_preserve",
        source="plex",
        rating_key="preserve",
        title="Preserve Me",
        normalized_title="preserveme",
        year=2020,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        synopsis="Original synopsis",
        synopsis_hash="samehash",
    )

    with get_db_connection() as conn:
        row = dict(conn.execute("SELECT * FROM library_items WHERE id = 'plex_preserve'").fetchone())
        assert row["synopsis_vector"] == original_vector
        assert row["synopsis_vector_model"] == "gemini-embedding-001"
        assert row["synopsis_vector_dim"] == 768


def test_upsert_clears_vector_when_synopsis_hash_changes_without_new_vector(temp_db_path):
    init_db()
    from moviebot.core.embeddings import encode_vector

    LibraryItemRepository.upsert(
        id="plex_clear",
        source="plex",
        rating_key="clear",
        title="Clear Me",
        normalized_title="clearme",
        year=2020,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        synopsis="Original synopsis",
        synopsis_hash="oldhash",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-05-31T00:00:00Z",
    )

    LibraryItemRepository.upsert(
        id="plex_clear",
        source="plex",
        rating_key="clear",
        title="Clear Me",
        normalized_title="clearme",
        year=2020,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        synopsis="Changed synopsis",
        synopsis_hash="newhash",
    )

    with get_db_connection() as conn:
        row = dict(conn.execute("SELECT * FROM library_items WHERE id = 'plex_clear'").fetchone())
        assert row["synopsis_vector"] is None
        assert row["synopsis_vector_model"] is None
        assert row["synopsis_vector_dim"] is None


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
        assert get_configured_model() == "gemini-embedding-001"
        with patch("moviebot.config.settings.gemini_embedding_model", "models/gemini-embedding-001"):
            assert get_configured_model() == "gemini-embedding-001"

        # Mock Gemini success
        with respx.mock:
            respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent").mock(
                return_value=Response(200, json={"embedding": {"values": [0.5] * 768}})
            )
            v = await get_embedding("test")
            assert v == [0.5] * 768

        # Mock Gemini failure fallback to Ollama
        with respx.mock:
            respx.post("https://generativelanguage.googleapis.com/v1beta/models/gemini-embedding-001:embedContent").mock(
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
async def test_query_library_skips_incompatible_embedding_models(temp_db_path):
    init_db()
    from moviebot.core.embeddings import EmbeddingResult, encode_vector
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_semantic",
        source="plex",
        rating_key="semantic",
        title="Stored Gemini Movie",
        normalized_title="storedgeminimovie",
        year=2020,
        imdb_id=None,
        file_path="/private/path/movie.mkv",
        size_bytes=None,
        synopsis="A movie about space travel.",
        synopsis_hash="hash",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-05-31T00:00:00Z",
    )

    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.1] * 768, "mock-hash-v1", 768, "mock", fallback=True)
        res = await query_library_tool(semantic_query="space travel", limit=5)

    assert res["ok"] is True
    assert res["data"]["movies"] == []
    assert res["data"]["semantic_search"]["query_model"] == "mock-hash-v1"
    assert res["data"]["semantic_search"]["skipped_model_mismatch"] == 1


@pytest.mark.asyncio
async def test_query_library_scores_matching_embedding_models(temp_db_path):
    init_db()
    from moviebot.core.embeddings import EmbeddingResult, encode_vector
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_semantic_match",
        source="plex",
        rating_key="semantic-match",
        title="Matching Model Movie",
        normalized_title="matchingmodelmovie",
        year=2020,
        imdb_id=None,
        file_path="/private/path/movie.mkv",
        size_bytes=None,
        synopsis="A movie about space travel.",
        synopsis_hash="hash",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-05-31T00:00:00Z",
    )

    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.1] * 768, "gemini-embedding-001", 768, "gemini")
        res = await query_library_tool(semantic_query="space travel", limit=5)

    assert res["ok"] is True
    assert len(res["data"]["movies"]) == 1
    assert res["data"]["movies"][0]["title"] == "Matching Model Movie"
    assert res["data"]["movies"][0]["similarity_score"] == pytest.approx(1.0)
    assert "file_path" not in res["data"]["movies"][0]


@pytest.mark.asyncio
async def test_sync_enrichment_tool_dry_run_and_real_mode(temp_db_path):
    init_db()
    from moviebot.tools.sync_enrichment_tool import sync_enrichment_tool

    LibraryItemRepository.upsert(
        id="plex_canada",
        source="plex",
        rating_key="canada",
        title="Come from Away",
        normalized_title="comefromaway",
        year=2021,
        imdb_id=None,
        file_path="/private/path/Come from Away.mkv",
        size_bytes=1000,
        genres=json.dumps(["Comedy", "Drama", "Musical"]),
        synopsis="After the 9/11 attacks, passengers are stranded in a small town in Newfoundland and welcomed by the community.",
        synopsis_hash="canadahash",
        studios=json.dumps(["Junkyard Dog"]),
        cast=json.dumps(["Jenn Colella"]),
        countries=json.dumps(["Canada", "United States"]),
        content_rating="PG-13",
    )

    dry_res = await sync_enrichment_tool(dry_run=True, limit=1)
    assert dry_res["ok"] is True
    assert dry_res["data"]["processed"] == 1
    assert dry_res["data"]["limit"] == 1
    assert dry_res["data"]["offset"] == 0
    assert dry_res["data"]["only_missing_hard_facts"] is False
    assert "Canada" in dry_res["data"]["items"][0]["setting_locations"]
    
    # Assert audit counts include both Plex fields and Block 2-9 hard facts
    audit_fields = dry_res["data"]["audit"]["fields"]
    assert "studios" in audit_fields
    assert "award_tags" in audit_fields
    assert "source_material_tags" in audit_fields
    assert "popularity_tags" in audit_fields
    assert "cultural_impact_tags" in audit_fields
    assert "box_office_tier" in audit_fields

    with get_db_connection() as conn:
        row = dict(conn.execute("SELECT * FROM library_items WHERE id = 'plex_canada'").fetchone())
        assert row["enrichment_json"] is None

    real_res = await sync_enrichment_tool(dry_run=False, limit=1)
    assert real_res["ok"] is True

    with get_db_connection() as conn:
        row = dict(conn.execute("SELECT * FROM library_items WHERE id = 'plex_canada'").fetchone())
        assert "Canada" in json.loads(row["setting_locations"])
        assert "community" in json.loads(row["theme_tags"])
        assert row["enrichment_version"] == "structured-enrichment-v2"
        assert "Canada" in json.loads(row["story_locations"])
        assert row["enrichment_model"] == "moviebot-rule-enricher-v1"
        evidence = json.loads(row["field_evidence_json"])
        assert "Canada" in evidence["setting"]


@pytest.mark.asyncio
async def test_sync_enrichment_tool_supports_offset_and_missing_hard_fact_batches(temp_db_path):
    init_db()
    from moviebot.tools.sync_enrichment_tool import sync_enrichment_tool

    for idx, title, award_tags in [
        (1, "Alpha", []),
        (2, "Bravo", ["award_winning"]),
        (3, "Charlie", []),
    ]:
        LibraryItemRepository.upsert(
            id=f"plex_batch_{idx}",
            source="plex",
            rating_key=f"batch_{idx}",
            title=title,
            normalized_title=title.lower(),
            year=2021,
            imdb_id=None,
            file_path=f"/private/path/{title}.mkv",
            size_bytes=1000,
            studios=json.dumps(["Test Studio"]),
            cast=json.dumps(["Test Actor"]),
            countries=json.dumps(["United States"]),
            content_rating="PG",
            synopsis=title,
            synopsis_hash=title.lower(),
        )
        if award_tags:
            LibraryItemRepository.update_enrichment(
                id=f"plex_batch_{idx}",
                enrichment_json=json.dumps({}),
                setting_locations=json.dumps([]),
                premise_tags=json.dumps([]),
                character_tags=json.dumps([]),
                theme_tags=json.dumps([]),
                tone_tags=json.dumps([]),
                craft_tags=json.dumps([]),
                content_warning_tags=json.dumps([]),
                content_warnings_json=json.dumps({}),
                field_confidence_json=json.dumps({}),
                field_evidence_json=json.dumps({}),
                enrichment_version="structured-enrichment-v2",
                enrichment_model="moviebot-rule-enricher-v1",
                enrichment_updated_at="2026-05-31T00:00:00Z",
                award_tags=json.dumps(award_tags),
                source_material_tags=json.dumps(["based_on_book"]),
                popularity_tags=json.dumps(["blockbuster"]),
                cultural_impact_tags=json.dumps(["classic"]),
                box_office_tier="blockbuster",
            )
            LibraryItemRepository.update_tmdb_enrichment(
                id=f"plex_batch_{idx}",
                brand_tags=json.dumps([]),
                franchise_tags=json.dumps([]),
                universe_tags=json.dumps([]),
                source_property_tags=json.dumps([]),
            )

    with patch("moviebot.tools.sync_enrichment_tool.WikidataFactProvider") as mock_provider:
        mock_provider.return_value.get_facts.return_value = {}
        offset_res = await sync_enrichment_tool(dry_run=True, limit=1, offset=1)
        missing_res = await sync_enrichment_tool(
            dry_run=True,
            limit=10,
            only_missing_hard_facts=True,
        )

    assert offset_res["ok"] is True
    assert offset_res["data"]["offset"] == 1
    assert [item["title"] for item in offset_res["data"]["items"]] == ["Bravo"]

    assert missing_res["ok"] is True
    assert missing_res["data"]["only_missing_hard_facts"] is True
    assert [item["title"] for item in missing_res["data"]["items"]] == ["Alpha", "Charlie"]

    with patch("moviebot.tools.sync_enrichment_tool.WikidataFactProvider") as mock_provider:
        mock_provider.return_value.get_facts.return_value = None
        mock_provider.return_value._rate_limited = True
        rate_limited_res = await sync_enrichment_tool(dry_run=False, limit=1)

    assert rate_limited_res["ok"] is True
    assert rate_limited_res["data"]["processed"] == 0
    assert rate_limited_res["data"]["selected"] == 1
    assert "rate-limited" in rate_limited_res["data"]["provider_errors"][0]["message"]


@pytest.mark.asyncio
async def test_sync_enrichment_tool_gemini_provider_normalizes_output(temp_db_path):
    init_db()
    from moviebot.core.gemini_enrichment import normalize_gemini_enrichment
    from moviebot.tools.sync_enrichment_tool import sync_enrichment_tool

    LibraryItemRepository.upsert(
        id="plex_gemini",
        source="plex",
        rating_key="gemini",
        title="Stage Movie",
        normalized_title="stagemovie",
        year=2021,
        imdb_id=None,
        file_path="/private/path/stage.mkv",
        size_bytes=1000,
        genres=json.dumps(["Musical"]),
        synopsis="A filmed stage performance in New York City.",
        synopsis_hash="geminihash",
        studios=json.dumps(["Stage Studio"]),
        cast=json.dumps(["Stage Actor"]),
        countries=json.dumps(["United States"]),
        content_rating="G",
    )
    gemini_raw = {
        "story_locations": [],
        "event_locations": ["New York"],
        "central_premise_tags": ["stage performance"],
        "dominant_tone_tags": ["warm"],
        "format_tags": ["musical"],
        "music_role_tags": ["musical theatre"],
        "award_tags": ["tony award winner"],
        "award_wins": {"tony": ["best musical"]},
        "award_nominations": {"emmy": ["outstanding television movie"]},
        "acclaim_tags": ["critically acclaimed"],
        "source_material_tags": ["based on a stage musical"],
        "adaptation_type_tags": ["stage adaptation"],
        "popularity_tags": ["mainstream"],
        "cultural_impact_tags": ["modern classic"],
        "box_office_tier": "modest",
        "hard_fact_sources": {"awards": "provided metadata"},
        "content_warnings": {"violence": {"level": "none", "confidence": 0.8, "evidence": None}},
        "field_confidence": {"geography": {"New York": 0.9}},
        "field_evidence": {"geography": {"New York": "filmed stage performance in New York City"}},
    }

    async def fake_gemini(item, wikidata_facts=None):
        return normalize_gemini_enrichment(item, gemini_raw, "gemini-2.5-flash")

    fake_rules_res = {
        "award_tags": ["tony award winner"],
        "award_wins_json": {"tony": ["best musical"]},
        "award_nominations_json": {"emmy": ["outstanding television movie"]},
        "acclaim_tags": ["critically acclaimed"],
        "source_material_tags": ["based on a stage musical"],
        "adaptation_type_tags": ["stage adaptation"],
        "popularity_tags": ["mainstream"],
        "cultural_impact_tags": ["modern classic"],
        "box_office_tier": "modest",
        "hard_fact_sources_json": {"awards": "provided metadata"},
        "enrichment_json": {
            "hard_facts": {
                "awards": {
                    "tags": ["tony award winner"],
                    "wins": {"tony": ["best musical"]},
                    "nominations": {"emmy": ["outstanding television movie"]},
                    "acclaim": ["critically acclaimed"],
                },
                "source_material": ["based on a stage musical"],
                "adaptation_types": ["stage adaptation"],
                "popularity": {
                    "tags": ["mainstream"],
                    "cultural_impact": ["modern classic"],
                    "box_office_tier": "modest",
                },
                "sources": {"awards": "provided metadata"},
            }
        }
    }

    with patch("moviebot.tools.fact_normalizer.enrich_library_item_with_gemini", new=fake_gemini), \
         patch("moviebot.tools.fact_normalizer.FactNormalizer.normalize_with_rules", return_value=fake_rules_res):
        res = await sync_enrichment_tool(dry_run=False, limit=1, provider="gemini")

    assert res["ok"] is True
    assert res["data"]["provider"] == "gemini"
    assert res["data"]["items"][0]["provider_used"] == "gemini"
    with get_db_connection() as conn:
        row = dict(conn.execute("SELECT * FROM library_items WHERE id = 'plex_gemini'").fetchone())
        assert json.loads(row["story_locations"]) == []
        assert json.loads(row["event_locations"]) == ["New York"]
        assert json.loads(row["central_premise_tags"]) == ["stage performance"]
        assert row["enrichment_model"] == "gemini-2.5-flash"
        assert json.loads(row["award_tags"]) == ["tony award winner"]
        assert json.loads(row["award_wins_json"]) == {"tony": ["best musical"]}
        assert json.loads(row["source_material_tags"]) == ["based on a stage musical"]
        assert json.loads(row["popularity_tags"]) == ["mainstream"]
        assert json.loads(row["cultural_impact_tags"]) == ["modern classic"]
        assert row["box_office_tier"] == "modest"


@pytest.mark.asyncio
async def test_query_library_routes_setting_phrase_to_structured_filter(temp_db_path):
    init_db()
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_canada",
        source="plex",
        rating_key="canada",
        title="Canada Movie",
        normalized_title="canadamovie",
        year=2021,
        imdb_id=None,
        file_path="/private/path/canada.mkv",
        size_bytes=1000,
        synopsis="A story in Newfoundland.",
        synopsis_hash="canada",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_canada",
        enrichment_json=json.dumps({}),
        setting_locations=json.dumps(["Canada"]),
        premise_tags=json.dumps([]),
        character_tags=json.dumps([]),
        theme_tags=json.dumps([]),
        tone_tags=json.dumps([]),
        craft_tags=json.dumps([]),
        content_warning_tags=json.dumps([]),
        content_warnings_json=json.dumps({}),
        field_confidence_json=json.dumps({"setting": {"Canada": 0.9}}),
        field_evidence_json=json.dumps({"setting": {"Canada": "Newfoundland"}}),
        enrichment_version="structured-enrichment-v1",
        enrichment_model="moviebot-rule-enricher-v1",
        enrichment_updated_at="2026-05-31T00:00:00Z",
        story_locations=json.dumps(["Canada"]),
    )
    LibraryItemRepository.upsert(
        id="plex_hockey",
        source="plex",
        rating_key="hockey",
        title="Hockey Movie",
        normalized_title="hockeymovie",
        year=2021,
        imdb_id=None,
        file_path="/private/path/hockey.mkv",
        size_bytes=1000,
        synopsis="A hockey player joins a tournament.",
        synopsis_hash="hockey",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_hockey",
        enrichment_json=json.dumps({}),
        setting_locations=json.dumps([]),
        premise_tags=json.dumps(["competition"]),
        character_tags=json.dumps(["athlete"]),
        theme_tags=json.dumps([]),
        tone_tags=json.dumps([]),
        craft_tags=json.dumps([]),
        content_warning_tags=json.dumps([]),
        content_warnings_json=json.dumps({}),
        field_confidence_json=json.dumps({}),
        field_evidence_json=json.dumps({}),
        enrichment_version="structured-enrichment-v1",
        enrichment_model="moviebot-rule-enricher-v1",
        enrichment_updated_at="2026-05-31T00:00:00Z",
    )

    res = await query_library_tool(semantic_query="takes place in Canada", limit=10)
    assert res["ok"] is True
    assert [m["title"] for m in res["data"]["movies"]] == ["Canada Movie"]
    assert res["data"]["query_routing"]["inferred_setting_location"] == "Canada"
    assert "story_location" in res["data"]["query_routing"]["structured_filters_applied"]
    assert "file_path" not in res["data"]["movies"][0]


@pytest.mark.asyncio
async def test_query_library_routes_new_york_phrase_to_city_location(temp_db_path):
    init_db()
    from moviebot.core.enrichment import enrich_library_item, serialize_enrichment
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_new_york",
        source="plex",
        rating_key="new_york",
        title="New York Movie",
        normalized_title="newyorkmovie",
        year=2021,
        imdb_id=None,
        file_path="/private/path/new-york.mkv",
        size_bytes=1000,
        synopsis="A writer starts over in New York City.",
        synopsis_hash="new_york",
    )
    row = {
        "title": "New York Movie",
        "genres": json.dumps(["Drama"]),
        "directors": json.dumps([]),
        "synopsis": "A writer starts over in New York City.",
    }
    enriched = serialize_enrichment(enrich_library_item(row, now_iso="2026-05-31T00:00:00Z"))
    LibraryItemRepository.update_enrichment(id="plex_new_york", **enriched)

    LibraryItemRepository.upsert(
        id="plex_american",
        source="plex",
        rating_key="american",
        title="Generic American Movie",
        normalized_title="genericamericanmovie",
        year=2021,
        imdb_id=None,
        file_path="/private/path/american.mkv",
        size_bytes=1000,
        synopsis="An American family moves across the country.",
        synopsis_hash="american",
    )
    row = {
        "title": "Generic American Movie",
        "genres": json.dumps(["Drama"]),
        "directors": json.dumps([]),
        "synopsis": "An American family moves across the country.",
    }
    enriched = serialize_enrichment(enrich_library_item(row, now_iso="2026-05-31T00:00:00Z"))
    LibraryItemRepository.update_enrichment(id="plex_american", **enriched)

    res = await query_library_tool(semantic_query="takes place in New York", limit=10)
    assert res["ok"] is True
    assert [m["title"] for m in res["data"]["movies"]] == ["New York Movie"]
    assert res["data"]["query_routing"]["inferred_setting_location"] == "New York"
    assert res["data"]["semantic_search"] is not None


@pytest.mark.asyncio
async def test_query_library_routes_studio_phrase_to_plex_studio(temp_db_path):
    init_db()
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_pixar",
        source="plex",
        rating_key="pixar",
        title="Toy Story",
        normalized_title="toystory",
        year=1995,
        imdb_id=None,
        file_path="/private/path/toy-story.mkv",
        size_bytes=1000,
        genres=json.dumps(["Animation"]),
        studios=json.dumps(["Pixar"]),
        cast=json.dumps(["Tom Hanks"]),
        content_rating="G",
        synopsis="A cowboy doll is threatened by a new spaceman figure.",
        synopsis_hash="pixar",
    )
    LibraryItemRepository.upsert(
        id="plex_non_pixar",
        source="plex",
        rating_key="non_pixar",
        title="Animated Movie",
        normalized_title="animatedmovie",
        year=1995,
        imdb_id=None,
        file_path="/private/path/animated.mkv",
        size_bytes=1000,
        genres=json.dumps(["Animation"]),
        studios=json.dumps(["Other Studio"]),
        synopsis="An animated adventure.",
        synopsis_hash="non_pixar",
    )

    res = await query_library_tool(semantic_query="pixar movies", limit=10)
    assert res["ok"] is True
    assert [m["title"] for m in res["data"]["movies"]] == ["Toy Story"]
    assert res["data"]["query_routing"]["inferred_studio"] == "Pixar"
    assert "studio" in res["data"]["query_routing"]["structured_filters_applied"]
    assert res["data"]["semantic_search"] is not None


@pytest.mark.asyncio
async def test_query_library_discards_invalid_studio_inference(temp_db_path):
    init_db()
    from moviebot.core.embeddings import EmbeddingResult, encode_vector
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_action_movie",
        source="plex",
        rating_key="action_movie",
        title="Lethal Weapon",
        normalized_title="lethalweapon",
        year=1987,
        imdb_id=None,
        file_path="/private/path/lethal-weapon.mkv",
        size_bytes=1000,
        genres=json.dumps(["Action", "Comedy"]),
        studios=json.dumps(["Warner Bros. Pictures"]),
        synopsis="Two mismatched cops are forced to work together.",
        synopsis_hash="lethal_weapon",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="mock-hash-v1",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-05-31T00:00:00Z",
    )

    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.1] * 768, "mock-hash-v1", 768, "mock")
        # Search for "buddy cop movies". It should NOT apply a studio filter because "Buddy Cop" is not in the DB
        res = await query_library_tool(semantic_query="buddy cop movies", limit=10)

    assert res["ok"] is True
    # It should NOT have "studio" in structured_filters_applied
    assert "studio" not in res["data"]["query_routing"]["structured_filters_applied"]
    assert res["data"]["query_routing"]["inferred_studio"] is None
    # It should still return Lethal Weapon because no studio filter was applied
    assert len(res["data"]["movies"]) == 1
    assert res["data"]["movies"][0]["title"] == "Lethal Weapon"


@pytest.mark.asyncio
async def test_query_library_discards_various_genre_and_style_studio_inferences(temp_db_path):
    init_db()
    from moviebot.core.embeddings import EmbeddingResult, encode_vector
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_sci_fi_movie",
        source="plex",
        rating_key="sci_fi_movie",
        title="The Matrix",
        normalized_title="thematrix",
        year=1999,
        imdb_id=None,
        file_path="/private/path/the-matrix.mkv",
        size_bytes=1000,
        genres=json.dumps(["Sci-Fi", "Action"]),
        studios=json.dumps(["Warner Bros. Pictures"]),
        synopsis="A computer hacker learns about the true nature of his reality.",
        synopsis_hash="matrix",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="mock-hash-v1",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-05-31T00:00:00Z",
    )

    test_queries = [
        "sci-fi movies",
        "action films",
        "comedy movies",
        "rom-com films",
    ]

    for q in test_queries:
        with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
            mock_embed.return_value = EmbeddingResult([0.1] * 768, "mock-hash-v1", 768, "mock")
            res = await query_library_tool(semantic_query=q, limit=10)
        assert res["ok"] is True
        assert "studio" not in res["data"]["query_routing"]["structured_filters_applied"]
        assert res["data"]["query_routing"]["inferred_studio"] is None
        assert len(res["data"]["movies"]) == 1
        assert res["data"]["movies"][0]["title"] == "The Matrix"


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_query", [
    # Geographic / nationality phrases
    "hong kong movies released in 1998",
    "hong kong films",
    "japanese movies",
    "korean films",
    "french movies",
    "chinese films",
    "british movies",
    "australian films",
    # Genre / style phrases
    "martial arts movies",
    "superhero films",
    "indie movies",
    "noir films",
    "western movies",
    "heist films",
    "spy movies",
    "biopic films",
    # Year / decade phrases
    "1998 movies",
    "90s films",
    # Descriptive adjective phrases
    "great movies",
    "popular films",
    "modern movies",
    "feel-good movies",
])
async def test_studio_inference_never_fires_on_non_brand_queries(bad_query, temp_db_path):
    """Geographic, genre, year, and adjective phrases must never become hard studio filters."""
    init_db()
    from moviebot.core.embeddings import EmbeddingResult, encode_vector
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_rush_hour_2",
        source="plex",
        rating_key="rush_hour_2",
        title="Rush Hour 2",
        normalized_title="rushhour2",
        year=2001,
        imdb_id=None,
        file_path="/private/path/rush-hour-2.mkv",
        size_bytes=1000,
        genres=json.dumps(["Action", "Comedy"]),
        studios=json.dumps(["New Line Cinema"]),
        synopsis="Two detectives tackle a criminal syndicate in Hong Kong.",
        synopsis_hash="rushhour2",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="mock-hash-v1",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-01T00:00:00Z",
    )

    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.1] * 768, "mock-hash-v1", 768, "mock")
        res = await query_library_tool(semantic_query=bad_query, limit=10)

    assert res["ok"] is True, f"Query failed for: {bad_query!r}"
    routing = res["data"]["query_routing"]
    assert routing["inferred_studio"] is None, (
        f"Expected inferred_studio=None for {bad_query!r}, got {routing['inferred_studio']!r}"
    )
    assert "studio" not in routing["structured_filters_applied"], (
        f"Studio filter was applied for non-brand query: {bad_query!r}"
    )
    assert len(res["data"]["movies"]) == 1, (
        f"Expected 1 result for {bad_query!r}, got {len(res['data']['movies'])}"
    )


@pytest.mark.asyncio
async def test_studio_inference_fires_for_exact_brand_element(temp_db_path):
    """A query like 'marvel movies' should infer studio='Marvel' when 'Marvel' is an exact JSON element."""
    init_db()
    from moviebot.core.embeddings import EmbeddingResult, encode_vector
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_marvel",
        source="plex",
        rating_key="marvel",
        title="Iron Man",
        normalized_title="ironman",
        year=2008,
        imdb_id=None,
        file_path="/private/path/iron-man.mkv",
        size_bytes=1000,
        genres=json.dumps(["Action", "Sci-Fi"]),
        studios=json.dumps(["Marvel"]),
        synopsis="Billionaire Tony Stark builds a powered suit of armor.",
        synopsis_hash="ironman",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="mock-hash-v1",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-01T00:00:00Z",
    )
    LibraryItemRepository.upsert(
        id="plex_other",
        source="plex",
        rating_key="other",
        title="Some Other Film",
        normalized_title="someotherfilm",
        year=2010,
        imdb_id=None,
        file_path="/private/path/other.mkv",
        size_bytes=1000,
        genres=json.dumps(["Drama"]),
        studios=json.dumps(["Other Studio"]),
        synopsis="A drama about nothing related to Marvel.",
        synopsis_hash="otherfilm",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="mock-hash-v1",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-01T00:00:00Z",
    )

    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.1] * 768, "mock-hash-v1", 768, "mock")
        res = await query_library_tool(semantic_query="marvel movies", limit=10)

    assert res["ok"] is True
    routing = res["data"]["query_routing"]
    assert routing["inferred_studio"] == "Marvel"
    assert "studio" in routing["structured_filters_applied"]
    titles = [m["title"] for m in res["data"]["movies"]]
    assert titles == ["Iron Man"], f"Expected only Marvel movie, got: {titles}"


@pytest.mark.asyncio
async def test_semantic_query_includes_fallback_warning_when_embedding_unavailable(temp_db_path):
    """When embedding model falls back, semantic_search must include a fallback_warning string."""
    init_db()
    from moviebot.core.embeddings import EmbeddingResult, encode_vector
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_any",
        source="plex",
        rating_key="any",
        title="Any Movie",
        normalized_title="anymovie",
        year=2000,
        imdb_id=None,
        file_path="/private/path/any.mkv",
        size_bytes=1000,
        synopsis="A movie.",
        synopsis_hash="any",
        synopsis_vector=encode_vector([0.1] * 768),
        synopsis_vector_model="mock-hash-v1",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-01T00:00:00Z",
    )

    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.1] * 768, "mock-hash-v1", 768, "mock", fallback=True)
        res = await query_library_tool(semantic_query="any movie", limit=10)

    assert res["ok"] is True
    sem = res["data"]["semantic_search"]
    assert sem is not None
    assert sem["fallback"] is True
    assert "fallback_warning" in sem
    assert "unavailable" in sem["fallback_warning"].lower()


@pytest.mark.asyncio
async def test_query_library_routes_hard_fact_phrases_to_structured_filters(temp_db_path):
    init_db()
    from moviebot.tools.query_library_tool import query_library_tool

    LibraryItemRepository.upsert(
        id="plex_award",
        source="plex",
        rating_key="award",
        title="Award Movie",
        normalized_title="awardmovie",
        year=2021,
        imdb_id=None,
        file_path="/private/path/award.mkv",
        size_bytes=1000,
        synopsis="A prestige drama.",
        synopsis_hash="award",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_award",
        enrichment_json=json.dumps({}),
        setting_locations=json.dumps([]),
        premise_tags=json.dumps([]),
        character_tags=json.dumps([]),
        theme_tags=json.dumps([]),
        tone_tags=json.dumps([]),
        craft_tags=json.dumps([]),
        content_warning_tags=json.dumps([]),
        content_warnings_json=json.dumps({}),
        field_confidence_json=json.dumps({}),
        field_evidence_json=json.dumps({}),
        enrichment_version="structured-enrichment-v2",
        enrichment_model="moviebot-rule-enricher-v1",
        enrichment_updated_at="2026-05-31T00:00:00Z",
        award_tags=json.dumps(["oscar winner"]),
        award_wins_json=json.dumps({"academy awards": ["best picture"]}),
        acclaim_tags=json.dumps(["critically acclaimed"]),
    )

    LibraryItemRepository.upsert(
        id="plex_book",
        source="plex",
        rating_key="book",
        title="Book Movie",
        normalized_title="bookmovie",
        year=2020,
        imdb_id=None,
        file_path="/private/path/book.mkv",
        size_bytes=1000,
        synopsis="An adaptation.",
        synopsis_hash="book",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_book",
        enrichment_json=json.dumps({}),
        setting_locations=json.dumps([]),
        premise_tags=json.dumps([]),
        character_tags=json.dumps([]),
        theme_tags=json.dumps([]),
        tone_tags=json.dumps([]),
        craft_tags=json.dumps([]),
        content_warning_tags=json.dumps([]),
        content_warnings_json=json.dumps({}),
        field_confidence_json=json.dumps({}),
        field_evidence_json=json.dumps({}),
        enrichment_version="structured-enrichment-v2",
        enrichment_model="moviebot-rule-enricher-v1",
        enrichment_updated_at="2026-05-31T00:00:00Z",
        source_material_tags=json.dumps(["based on a book"]),
    )

    LibraryItemRepository.upsert(
        id="plex_blockbuster",
        source="plex",
        rating_key="blockbuster",
        title="Blockbuster Movie",
        normalized_title="blockbustermovie",
        year=2019,
        imdb_id=None,
        file_path="/private/path/blockbuster.mkv",
        size_bytes=1000,
        synopsis="A crowd-pleasing spectacle.",
        synopsis_hash="blockbuster",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_blockbuster",
        enrichment_json=json.dumps({}),
        setting_locations=json.dumps([]),
        premise_tags=json.dumps([]),
        character_tags=json.dumps([]),
        theme_tags=json.dumps([]),
        tone_tags=json.dumps([]),
        craft_tags=json.dumps([]),
        content_warning_tags=json.dumps([]),
        content_warnings_json=json.dumps({}),
        field_confidence_json=json.dumps({}),
        field_evidence_json=json.dumps({}),
        enrichment_version="structured-enrichment-v2",
        enrichment_model="moviebot-rule-enricher-v1",
        enrichment_updated_at="2026-05-31T00:00:00Z",
        popularity_tags=json.dumps(["blockbuster"]),
        cultural_impact_tags=json.dumps(["classic"]),
    )

    award_res = await query_library_tool(semantic_query="award winning movies", limit=10)
    assert [m["title"] for m in award_res["data"]["movies"]] == ["Award Movie"]
    assert award_res["data"]["query_routing"]["inferred_award_tag"] == "award winning"
    assert "award_tag" in award_res["data"]["query_routing"]["structured_filters_applied"]
    assert award_res["data"]["semantic_search"] is not None

    oscar_res = await query_library_tool(semantic_query="oscar movies", limit=10)
    assert [m["title"] for m in oscar_res["data"]["movies"]] == ["Award Movie"]

    book_res = await query_library_tool(semantic_query="based on a book", limit=10)
    assert [m["title"] for m in book_res["data"]["movies"]] == ["Book Movie"]
    assert book_res["data"]["query_routing"]["inferred_source_material_tag"] == "based on a book"

    blockbuster_res = await query_library_tool(semantic_query="blockbuster movies", limit=10)
    assert [m["title"] for m in blockbuster_res["data"]["movies"]] == ["Blockbuster Movie"]
    assert blockbuster_res["data"]["query_routing"]["inferred_popularity_tag"] == "blockbuster"


@pytest.mark.asyncio
async def test_query_library_excludes_content_warnings_conservatively(temp_db_path):
    init_db()
    from moviebot.tools.query_library_tool import query_library_tool

    for movie_id, title, warnings_json in [
        ("plex_safe", "Safe Movie", {"gore": {"level": "none"}}),
        ("plex_gore", "Gory Movie", {"gore": {"level": "moderate"}}),
        ("plex_unknown", "Unknown Movie", {}),
    ]:
        LibraryItemRepository.upsert(
            id=movie_id,
            source="plex",
            rating_key=movie_id,
            title=title,
            normalized_title=title.lower().replace(" ", ""),
            year=2021,
            imdb_id=None,
            file_path=f"/private/path/{title}.mkv",
            size_bytes=1000,
            synopsis=title,
            synopsis_hash=movie_id,
        )
        LibraryItemRepository.update_enrichment(
            id=movie_id,
            enrichment_json=json.dumps({}),
            setting_locations=json.dumps([]),
            premise_tags=json.dumps([]),
            character_tags=json.dumps([]),
            theme_tags=json.dumps([]),
            tone_tags=json.dumps([]),
            craft_tags=json.dumps([]),
            content_warning_tags=json.dumps(list(warnings_json.keys())),
            content_warnings_json=json.dumps(warnings_json),
            field_confidence_json=json.dumps({}),
            field_evidence_json=json.dumps({}),
            enrichment_version="structured-enrichment-v1",
            enrichment_model="moviebot-rule-enricher-v1",
            enrichment_updated_at="2026-05-31T00:00:00Z",
        )

    strict_res = await query_library_tool(exclude_content_warnings=["gore"], limit=10)
    assert [m["title"] for m in strict_res["data"]["movies"]] == ["Safe Movie"]

    relaxed_res = await query_library_tool(
        exclude_content_warnings=["gore"],
        include_unknown_content_warnings=True,
        limit=10
    )
    assert [m["title"] for m in relaxed_res["data"]["movies"]] == ["Safe Movie", "Unknown Movie"]


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

        from moviebot.core.embeddings import EmbeddingResult, encode_vector

        with patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch, \
             patch("moviebot.core.embeddings.get_embedding_result", new_callable=AsyncMock) as mock_embed:
            
            mock_fetch.return_value = mock_details
            mock_embed.return_value = EmbeddingResult([0.1] * 768, "nomic-embed-text", 768, "ollama")

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
             patch("moviebot.core.embeddings.get_embedding_result", new_callable=AsyncMock) as mock_embed:
            
            mock_fetch.return_value = mock_details
            mock_embed.return_value = EmbeddingResult([0.2] * 768, "nomic-embed-text", 768, "ollama")

            status = await cmd_sync_intelligence(args)
            assert status == 0
            mock_fetch.assert_called_once_with("333")
            mock_embed.assert_not_called()

        # 3. Change synopsis hash -> should fetch new embedding
        mock_details_changed = mock_details.copy()
        mock_details_changed["synopsis_hash"] = "inceptionhash2"
        mock_details_changed["synopsis"] = "A thief who steals corporate secrets using dream-sharing tech."

        with patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch, \
             patch("moviebot.core.embeddings.get_embedding_result", new_callable=AsyncMock) as mock_embed:
            
            mock_fetch.return_value = mock_details_changed
            mock_embed.return_value = EmbeddingResult([0.3] * 768, "nomic-embed-text", 768, "ollama")

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


def test_wikidata_fact_provider_and_normalizer():
    from moviebot.tools.fact_provider import WikidataFactProvider
    from moviebot.tools.fact_normalizer import FactNormalizer

    # 1. Test WikidataFactProvider caching/fetching mock
    provider = WikidataFactProvider()
    with patch("httpx.Client.get") as mock_get:
        # Mock Search response to get QID
        mock_search_resp = MagicMock()
        mock_search_resp.json.return_value = {
            "query": {
                "search": [
                    {"title": "Q105753", "snippet": "IMDb ID: tt0133093"}
                ]
            }
        }
        
        # Mock Entity data response
        mock_entity_resp = MagicMock()
        mock_entity_resp.json.return_value = {
            "entities": {
                "Q105753": {
                    "claims": {
                        "P345": [{"mainsnak": {"datavalue": {"type": "string", "value": "tt0133093"}}}], # IMDb ID
                        "P2142": [{"mainsnak": {"datavalue": {"type": "quantity", "value": {"amount": "+463517383"}}}}], # Box office
                        "P2522": [{"mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": "Q1111"}}}}], # Award received
                        "P144": [{"mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": "Q2222"}}}}], # Based on
                        "P179": [{"mainsnak": {"datavalue": {"type": "wikibase-entityid", "value": {"id": "Q3333"}}}}], # Part of series
                    }
                }
            }
        }
        
        # Batched labels mock
        mock_label_resp = MagicMock()
        mock_label_resp.json.return_value = {
            "entities": {
                "Q105753": {"labels": {"en": {"value": "The Matrix"}}},
                "Q1111": {"labels": {"en": {"value": "Academy Award for Best Visual Effects"}}},
                "Q2222": {"labels": {"en": {"value": "Philosophical concepts"}}},
                "Q3333": {"labels": {"en": {"value": "The Matrix film series"}}}
            }
        }
        
        mock_get.side_effect = [
            mock_search_resp,
            mock_entity_resp,
            mock_label_resp
        ]
        
        facts = provider.get_facts(title="The Matrix", year=1999, imdb_id="tt0133093")
        
        assert facts["qid"] == "Q105753"
        assert facts["box_office"] == 463517383
        assert "Academy Award for Best Visual Effects" in facts["awards_received"]
        assert "Philosophical concepts" in facts["based_on"]
        assert "The Matrix film series" in facts["series"]

    # 2. Test FactNormalizer rules-based mapping
    item = {
        "title": "The Matrix",
        "year": 1999,
        "rating": 8.7,
        "genres": ["Action", "Sci-Fi"]
    }
    normalized = FactNormalizer.normalize_with_rules(facts, item)
    
    assert "oscar_winner" in normalized["award_tags"]
    assert "award_winning" in normalized["award_tags"]
    assert "critically_acclaimed" in normalized["acclaim_tags"]
    assert "blockbuster" in normalized["popularity_tags"]
    assert normalized["box_office_tier"] == "blockbuster"
    assert "franchise" in normalized["adaptation_type_tags"]
    assert normalized["hard_fact_sources_json"]["qid"] == "Q105753"


@pytest.mark.asyncio
async def test_query_library_hard_fact_filters(temp_db_path):
    init_db()
    from moviebot.tools.query_library_tool import query_library_tool
    
    LibraryItemRepository.upsert(
        id="plex_matrix",
        source="plex",
        rating_key="matrix",
        title="The Matrix",
        normalized_title="thematrix",
        year=1999,
        imdb_id="tt0133093",
        file_path="/movies/matrix.mkv",
        size_bytes=1000,
        genres=json.dumps(["Action"]),
        studios=json.dumps(["Warner Bros"]),
        cast=json.dumps(["Keanu Reeves"]),
        countries=json.dumps(["United States"]),
        content_rating="R",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_matrix",
        enrichment_json=json.dumps({}),
        setting_locations=json.dumps([]),
        premise_tags=json.dumps([]),
        character_tags=json.dumps([]),
        theme_tags=json.dumps([]),
        tone_tags=json.dumps([]),
        craft_tags=json.dumps([]),
        content_warning_tags=json.dumps([]),
        content_warnings_json=json.dumps({}),
        field_confidence_json=json.dumps({}),
        field_evidence_json=json.dumps({}),
        enrichment_version="structured-enrichment-v2",
        enrichment_model="rules",
        enrichment_updated_at="2026-05-31T00:00:00Z",
        award_tags=json.dumps(["oscar_winner", "award_winning"]),
        award_wins_json=json.dumps({"oscar": 4}),
        award_nominations_json=json.dumps({}),
        acclaim_tags=json.dumps(["critically_acclaimed"]),
        source_material_tags=json.dumps(["based_on_book"]),
        adaptation_type_tags=json.dumps(["franchise"]),
        popularity_tags=json.dumps(["blockbuster", "mainstream"]),
        cultural_impact_tags=json.dumps(["classic"]),
        box_office_tier="blockbuster",
        hard_fact_sources_json=json.dumps({"qid": "Q105753"}),
    )

    # Test filtering by award_tag
    res = await query_library_tool(award_tag="oscar_winner")
    assert res["ok"] is True
    assert len(res["data"]["movies"]) == 1
    assert res["data"]["movies"][0]["title"] == "The Matrix"

    # Test filtering by source_material_tag
    res = await query_library_tool(source_material_tag="based_on_book")
    assert res["ok"] is True
    assert len(res["data"]["movies"]) == 1

    # Test filtering by popularity_tag
    res = await query_library_tool(popularity_tag="blockbuster")
    assert res["ok"] is True
    assert len(res["data"]["movies"]) == 1

    # Test filtering by cultural_impact_tag
    res = await query_library_tool(cultural_impact_tag="classic")
    assert res["ok"] is True
    assert len(res["data"]["movies"]) == 1


def test_fact_normalizer_plex_curation_cues():
    from moviebot.tools.fact_normalizer import FactNormalizer
    
    item = {
        "title": "Anne of Green Gables",
        "year": 1985,
        "rating": 8.5,
        "labels": json.dumps(["Classic"]),
        "collections": json.dumps(["Canadian Classic"])
    }
    
    # Run normalizer with empty Wikidata facts, relying solely on Plex curation
    normalized = FactNormalizer.normalize_with_rules(facts={}, item=item)
    
    assert "classic" in normalized["cultural_impact_tags"]
    assert "classic" in normalized["popularity_tags"]
    assert normalized["hard_fact_sources_json"]["source"] == "plex_curation"


@pytest.mark.asyncio
async def test_gemini_fills_gaps_when_rules_empty():
    """Gemini values should survive when rules produce nothing for a hard-fact field."""
    from moviebot.tools.fact_normalizer import FactNormalizer
    from moviebot.core.gemini_enrichment import normalize_gemini_enrichment

    item = {
        "title": "Anne of Green Gables",
        "year": 1985,
        "rating": 8.5,
        "genres": json.dumps(["Drama"]),
        "synopsis": "An orphan girl is sent to live with elderly siblings on Prince Edward Island.",
    }

    # Gemini says: classic, canadian icon, based on a book
    gemini_raw = {
        "story_locations": ["Prince Edward Island"],
        "central_premise_tags": ["orphan", "coming of age"],
        "dominant_tone_tags": ["warm", "nostalgic"],
        "award_tags": [],
        "award_wins": {},
        "award_nominations": {},
        "acclaim_tags": [],
        "source_material_tags": ["based_on_book"],
        "adaptation_type_tags": ["book_adaptation"],
        "popularity_tags": ["mainstream"],
        "cultural_impact_tags": ["classic", "canadian icon"],
        "box_office_tier": None,
        "hard_fact_sources": {},
        "content_warnings": {},
        "field_confidence": {},
        "field_evidence": {},
    }

    async def fake_gemini(item, wikidata_facts=None):
        return normalize_gemini_enrichment(item, gemini_raw, "gemini-2.5-flash")

    with patch("moviebot.tools.fact_normalizer.enrich_library_item_with_gemini", new=fake_gemini):
        result = await FactNormalizer.normalize_with_gemini(facts={}, item=item)

    # Rules had nothing for these fields, so Gemini values should survive
    assert "based_on_book" in result["source_material_tags"]
    assert "book_adaptation" in result["adaptation_type_tags"]
    assert "classic" in result["cultural_impact_tags"]
    assert "canadian icon" in result["cultural_impact_tags"]
    assert "mainstream" in result["popularity_tags"]

    # Provenance should record gemini_fallback
    prov = result["hard_fact_sources_json"]["field_provenance"]
    assert prov["source_material_tags"] == "gemini_fallback"
    # Rules also infer "classic" from age+rating, so both sources contribute
    assert prov["cultural_impact_tags"] == "rules+gemini"


@pytest.mark.asyncio
async def test_gemini_merge_rules_win_when_both_have_data():
    """When both rules and Gemini have data, the result should be the union with rules taking credit."""
    from moviebot.tools.fact_normalizer import FactNormalizer
    from moviebot.core.gemini_enrichment import normalize_gemini_enrichment

    item = {
        "title": "Test Movie",
        "year": 2020,
        "rating": 7.0,
        "genres": json.dumps(["Drama"]),
        "synopsis": "A test movie.",
    }

    gemini_raw = {
        "story_locations": [],
        "central_premise_tags": [],
        "dominant_tone_tags": [],
        "award_tags": ["golden_globe_nominee"],
        "award_wins": {},
        "award_nominations": {"golden_globe": ["best drama"]},
        "acclaim_tags": [],
        "source_material_tags": ["true_story"],
        "adaptation_type_tags": [],
        "popularity_tags": ["mainstream"],
        "cultural_impact_tags": [],
        "box_office_tier": None,
        "hard_fact_sources": {},
        "content_warnings": {},
        "field_confidence": {},
        "field_evidence": {},
    }

    async def fake_gemini(item, wikidata_facts=None):
        return normalize_gemini_enrichment(item, gemini_raw, "gemini-2.5-flash")

    # Rules produce oscar_winner from Wikidata
    fake_facts = {
        "qid": "Q12345",
        "awards_received": ["Academy Award for Best Picture"],
        "nominated_for": [],
        "based_on": [],
        "series": [],
        "box_office": None,
    }

    with patch("moviebot.tools.fact_normalizer.enrich_library_item_with_gemini", new=fake_gemini):
        result = await FactNormalizer.normalize_with_gemini(facts=fake_facts, item=item)

    # Union: rules' oscar_winner + gemini's golden_globe_nominee
    assert "oscar_winner" in result["award_tags"]
    assert "golden_globe_nominee" in result["award_tags"]
    assert "award_winning" in result["award_tags"]

    # Source material: rules had nothing, Gemini fills in
    assert "true_story" in result["source_material_tags"]

    # Provenance should reflect merged sources
    prov = result["hard_fact_sources_json"]["field_provenance"]
    assert prov["award_tags"] == "rules+gemini"
    assert prov["source_material_tags"] == "gemini_fallback"


@pytest.mark.asyncio
async def test_sync_enrichment_tool_only_missing_enrichment(temp_db_path):
    init_db()
    from moviebot.tools.sync_enrichment_tool import sync_enrichment_tool

    # Insert items with different enrichment_json source states
    # 1. No enrichment
    LibraryItemRepository.upsert(
        id="plex_none",
        source="plex",
        rating_key="none",
        title="Movie None",
        normalized_title="movienone",
        year=2021,
        imdb_id=None,
        file_path="/movies/none.mkv",
        size_bytes=1000,
        studios=json.dumps(["Test Studio"]),
        cast=json.dumps(["Test Actor"]),
        countries=json.dumps(["United States"]),
        content_rating="PG",
    )
    # 2. Rules source
    LibraryItemRepository.upsert(
        id="plex_rules",
        source="plex",
        rating_key="rules",
        title="Movie Rules",
        normalized_title="movierules",
        year=2021,
        imdb_id=None,
        file_path="/movies/rules.mkv",
        size_bytes=1000,
        studios=json.dumps(["Test Studio"]),
        cast=json.dumps(["Test Actor"]),
        countries=json.dumps(["United States"]),
        content_rating="PG",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_rules",
        enrichment_json=json.dumps({"source": "rules"}),
        setting_locations="[]", premise_tags="[]", character_tags="[]", theme_tags="[]", tone_tags="[]", craft_tags="[]",
        content_warning_tags="[]", content_warnings_json="{}", field_confidence_json="{}", field_evidence_json="{}",
        enrichment_version="v2", enrichment_model="rules", enrichment_updated_at="2026-06-01T00:00:00Z",
        award_tags="[]", source_material_tags="[]", popularity_tags="[]", cultural_impact_tags="[]", box_office_tier=""
    )
    # 3. Gemini source (already done)
    LibraryItemRepository.upsert(
        id="plex_gemini",
        source="plex",
        rating_key="gemini",
        title="Movie Gemini",
        normalized_title="moviegemini",
        year=2021,
        imdb_id=None,
        file_path="/movies/gemini.mkv",
        size_bytes=1000,
        studios=json.dumps(["Test Studio"]),
        cast=json.dumps(["Test Actor"]),
        countries=json.dumps(["United States"]),
        content_rating="PG",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_gemini",
        enrichment_json=json.dumps({"source": "gemini"}),
        setting_locations="[]", premise_tags="[]", character_tags="[]", theme_tags="[]", tone_tags="[]", craft_tags="[]",
        content_warning_tags="[]", content_warnings_json="{}", field_confidence_json="{}", field_evidence_json="{}",
        enrichment_version="v2", enrichment_model="gemini", enrichment_updated_at="2026-06-01T00:00:00Z",
        award_tags="[]", source_material_tags="[]", popularity_tags="[]", cultural_impact_tags="[]", box_office_tier=""
    )
    # 4. Rules fallback source
    LibraryItemRepository.upsert(
        id="plex_fallback",
        source="plex",
        rating_key="fallback",
        title="Movie Fallback",
        normalized_title="moviefallback",
        year=2021,
        imdb_id=None,
        file_path="/movies/fallback.mkv",
        size_bytes=1000,
        studios=json.dumps(["Test Studio"]),
        cast=json.dumps(["Test Actor"]),
        countries=json.dumps(["United States"]),
        content_rating="PG",
    )
    LibraryItemRepository.update_enrichment(
        id="plex_fallback",
        enrichment_json=json.dumps({"source": "rules_fallback"}),
        setting_locations="[]", premise_tags="[]", character_tags="[]", theme_tags="[]", tone_tags="[]", craft_tags="[]",
        content_warning_tags="[]", content_warnings_json="{}", field_confidence_json="{}", field_evidence_json="{}",
        enrichment_version="v2", enrichment_model="rules_fallback", enrichment_updated_at="2026-06-01T00:00:00Z",
        award_tags="[]", source_material_tags="[]", popularity_tags="[]", cultural_impact_tags="[]", box_office_tier=""
    )

    # When querying with gemini provider and only_missing_enrichment=True
    with patch("moviebot.tools.sync_enrichment_tool.WikidataFactProvider") as mock_prov, \
         patch("moviebot.tools.fact_normalizer.FactNormalizer.normalize_with_gemini") as mock_gemini:
        
        mock_prov.return_value.get_facts.return_value = {}
        # Return a dummy enrichment dictionary
        mock_gemini.return_value = {
            "setting_locations": [],
            "premise_tags": [],
            "character_tags": [],
            "theme_tags": [],
            "tone_tags": [],
            "craft_tags": [],
            "content_warning_tags": [],
            "content_warnings_json": {},
            "field_confidence_json": {},
            "field_evidence_json": {},
            "enrichment_version": "v2",
            "enrichment_model": "gemini",
            "enrichment_json": {"source": "gemini"},
            "award_tags": [],
            "source_material_tags": [],
            "popularity_tags": [],
            "cultural_impact_tags": [],
            "box_office_tier": "",
            "hard_fact_sources_json": {},
        }

        res = await sync_enrichment_tool(
            dry_run=True,
            provider="gemini",
            only_missing_enrichment=True,
            limit=10,
        )

    assert res["ok"] is True
    found_ids = {item["id"] for item in res["data"]["items"]}
    assert "plex_none" in found_ids
    assert "plex_rules" in found_ids
    assert "plex_fallback" in found_ids
    assert "plex_gemini" not in found_ids


@pytest.mark.asyncio
async def test_sync_enrichment_tool_transient_error_handling(temp_db_path):
    import httpx
    init_db()
    from moviebot.tools.sync_enrichment_tool import sync_enrichment_tool

    LibraryItemRepository.upsert(
        id="plex_transient",
        source="plex",
        rating_key="transient",
        title="Transient Movie",
        normalized_title="transientmovie",
        year=2021,
        imdb_id=None,
        file_path="/movies/transient.mkv",
        size_bytes=1000,
        studios=json.dumps(["Test Studio"]),
        cast=json.dumps(["Test Actor"]),
        countries=json.dumps(["United States"]),
        content_rating="PG",
    )

    # Mock Wikidata fact provider success, but FactNormalizer.normalize_with_gemini throws 503 status error
    mock_response = httpx.Response(503, request=httpx.Request("POST", "https://api.example.com"))
    transient_error = httpx.HTTPStatusError("503 Service Unavailable", request=mock_response.request, response=mock_response)

    with patch("moviebot.tools.sync_enrichment_tool.WikidataFactProvider") as mock_prov, \
         patch("moviebot.tools.fact_normalizer.FactNormalizer.normalize_with_gemini", side_effect=transient_error):
        mock_prov.return_value.get_facts.return_value = {}

        res = await sync_enrichment_tool(
            dry_run=False,
            provider="gemini",
            limit=1,
        )

    # Should bubble up / return an error envelope for transient rate-limit / overload error
    assert res["ok"] is False
    assert res["error"]["code"] == "RATE_LIMIT_OR_OVERLOAD"
    assert "Transient enrichment error" in res["error"]["message"]

    # Verify that database has NOT been updated with rules_fallback (i.e. remains NULL)
    with get_db_connection() as conn:
        row = dict(conn.execute("SELECT * FROM library_items WHERE id = 'plex_transient'").fetchone())
        assert row["enrichment_json"] is None


@pytest.mark.asyncio
async def test_fact_provider_qid_bypass_and_normalizer_smart_merge():
    from moviebot.tools.fact_provider import WikidataFactProvider
    from moviebot.tools.fact_normalizer import FactNormalizer

    provider = WikidataFactProvider()
    with patch("httpx.Client.get") as mock_get:
        # Mock Entity data response
        mock_entity_resp = MagicMock()
        mock_entity_resp.json.return_value = {
            "entities": {
                "Q99999": {
                    "claims": {
                        "P2142": [{"mainsnak": {"datavalue": {"type": "quantity", "value": {"amount": "+5000000"}}}}], # Box office
                    }
                }
            }
        }
        
        # Batched labels mock
        mock_label_resp = MagicMock()
        mock_label_resp.json.return_value = {
            "entities": {
                "Q99999": {"labels": {"en": {"value": "Pre-provided QID Movie"}}}
            }
        }
        
        mock_get.side_effect = [
            mock_entity_resp,
            mock_label_resp
        ]
        
        # Passing qid="Q99999" directly — it shouldn't call get_qid_by_imdb_id or get_qid_by_title_year
        facts = provider.get_facts(title="Pre-provided QID Movie", year=2021, qid="Q99999")
        
        assert facts["qid"] == "Q99999"
        assert facts["box_office"] == 5000000

    # Test smart-merge in normalize_with_rules:
    # Existing item in database has awards and a box office tier
    item = {
        "title": "Pre-provided QID Movie",
        "year": 2021,
        "rating": 7.5,
        "award_tags": json.dumps(["oscar_winner"]),
        "award_wins_json": json.dumps({"oscar": 2}),
        "award_nominations_json": json.dumps({"oscar": 3}),
        "box_office_tier": "hit",
        "hard_fact_sources_json": json.dumps({"qid": "Q99999"}),
    }
    
    # New facts say we got a Saturn Award win, but no box office info
    new_facts = {
        "qid": "Q99999",
        "box_office": None,
        "awards_received": ["Saturn Award"],
        "nominated_for": [],
        "based_on": [],
        "series": []
    }
    
    normalized = FactNormalizer.normalize_with_rules(new_facts, item)
    
    # Check that they merged additively
    assert "oscar_winner" in normalized["award_tags"]
    assert "award_winning" in normalized["award_tags"]
    assert normalized["award_wins_json"]["oscar"] == 2
    assert normalized["award_wins_json"]["Saturn Award"] == 1
    assert normalized["box_office_tier"] == "hit"
    assert normalized["hard_fact_sources_json"]["qid"] == "Q99999"

