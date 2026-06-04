import pytest
import json
from unittest.mock import patch, AsyncMock
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.db.repositories import LibraryItemRepository
from moviebot.core.embeddings import EmbeddingResult, encode_vector
from moviebot.tools.query_library_tool import query_library_tool

@pytest.fixture
def temp_db_path(tmp_path):
    """Fixture that returns a temporary database file path and patches settings."""
    db_file = tmp_path / "test_query_library_semantic_regression.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        yield db_file

@pytest.mark.asyncio
async def test_query_library_semantic_regression_sad_movies(temp_db_path):
    init_db()

    # 1. Insert action/John Wick movie
    LibraryItemRepository.upsert(
        id="plex_john_wick",
        source="plex",
        rating_key="wick",
        title="John Wick",
        normalized_title="johnwick",
        year=2014,
        imdb_id="tt2911666",
        file_path="/movies/John Wick.mkv",
        size_bytes=1000,
        synopsis="An ex-hitman comes out of retirement to track down the gangsters that took everything from him.",
        synopsis_hash="wickhash",
        synopsis_vector=encode_vector([1.0, 0.0, 0.0] + [0.0] * 765),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-04T00:00:00Z"
    )
    LibraryItemRepository.update_tmdb_enrichment(
        id="plex_john_wick",
        brand_tags=json.dumps(["Summit Entertainment"]),
        franchise_tags=json.dumps(["John Wick"]),
        universe_tags=json.dumps([]),
        source_property_tags=json.dumps(["John Wick"])
    )

    # 2. Insert sad movie
    LibraryItemRepository.upsert(
        id="plex_schindlers_list",
        source="plex",
        rating_key="schindler",
        title="Schindler's List",
        normalized_title="schindlerslist",
        year=1993,
        imdb_id="tt0108052",
        file_path="/movies/Schindlers List.mkv",
        size_bytes=1000,
        synopsis="A tragic and sad historical drama about the Holocaust.",
        synopsis_hash="schindlerhash",
        synopsis_vector=encode_vector([0.0, 1.0, 0.0] + [0.0] * 765),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-04T00:00:00Z"
    )
    LibraryItemRepository.update_tmdb_enrichment(
        id="plex_schindlers_list",
        brand_tags=json.dumps([]),
        franchise_tags=json.dumps([]),
        universe_tags=json.dumps([]),
        source_property_tags=json.dumps([])
    )

    # 3. Insert Marvel movie
    LibraryItemRepository.upsert(
        id="plex_iron_man",
        source="plex",
        rating_key="ironman",
        title="Iron Man",
        normalized_title="ironman",
        year=2008,
        imdb_id="tt0371746",
        file_path="/movies/Iron Man.mkv",
        size_bytes=1000,
        synopsis="Tony Stark builds an armored suit to fight evil.",
        synopsis_hash="ironmanhash",
        synopsis_vector=encode_vector([0.0, 0.0, 1.0] + [0.0] * 765),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-04T00:00:00Z"
    )
    LibraryItemRepository.update_tmdb_enrichment(
        id="plex_iron_man",
        brand_tags=json.dumps(["Marvel"]),
        franchise_tags=json.dumps(["Iron Man"]),
        universe_tags=json.dumps(["Marvel Cinematic Universe"]),
        source_property_tags=json.dumps(["Spider-Man"])  # Mock source property tag
    )

    # Case A: Querying for "sad movies"
    # Should perform a regular semantic search WITHOUT any brand/franchise filters,
    # and since Schindler's List has a closer mock vector [0.0, 1.0, 0.0] + [0.0]*765 to "sad movies" vector [0.0, 1.0, 0.0] + [0.0]*765,
    # it should rank it first, and query_routing should not contain inferred brand/franchise filters.
    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.0, 1.0, 0.0] + [0.0] * 765, "gemini-embedding-001", 768, "gemini")
        res = await query_library_tool(semantic_query="sad movies", limit=5)

    assert res["ok"] is True
    movies = res["data"]["movies"]
    assert len(movies) == 3
    assert movies[0]["title"] == "Schindler's List"
    routing = res["data"]["query_routing"]
    assert routing["inferred_brand"] is None
    assert routing["inferred_franchise"] is None
    assert routing["inferred_universe"] is None
    assert routing["inferred_source_property"] is None

    # Case B: Querying for "John Wick movies"
    # Should infer franchise "John Wick" and apply the franchise filter.
    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([1.0, 0.0, 0.0] + [0.0] * 765, "gemini-embedding-001", 768, "gemini")
        res = await query_library_tool(semantic_query="John Wick movies", limit=5)

    assert res["ok"] is True
    movies = res["data"]["movies"]
    assert len(movies) == 1
    assert movies[0]["title"] == "John Wick"
    routing = res["data"]["query_routing"]
    assert routing["inferred_franchise"] == "John Wick"
    assert "franchise" in routing["structured_filters_applied"]

    # Case C: Querying for "Marvel movies"
    # Should infer brand "Marvel" and apply the brand filter.
    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.0, 0.0, 1.0] + [0.0] * 765, "gemini-embedding-001", 768, "gemini")
        res = await query_library_tool(semantic_query="Marvel movies", limit=5)

    assert res["ok"] is True
    movies = res["data"]["movies"]
    assert len(movies) == 1
    assert movies[0]["title"] == "Iron Man"
    routing = res["data"]["query_routing"]
    assert routing["inferred_brand"] == "Marvel"
    assert "brand" in routing["structured_filters_applied"]


@pytest.mark.asyncio
async def test_query_library_semantic_regression_bond_and_starwars(temp_db_path):
    init_db()

    # 1. Insert Bond movie
    LibraryItemRepository.upsert(
        id="plex_skyfall",
        source="plex",
        rating_key="skyfall",
        title="Skyfall",
        normalized_title="skyfall",
        year=2012,
        imdb_id="tt1074638",
        file_path="/movies/Skyfall.mkv",
        size_bytes=1000,
        synopsis="Bond's loyalty to M is tested when her past comes back to haunt her.",
        synopsis_hash="skyfallhash",
        synopsis_vector=encode_vector([0.0, 0.0, 0.0, 1.0] + [0.0] * 764),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-04T00:00:00Z"
    )
    LibraryItemRepository.update_tmdb_enrichment(
        id="plex_skyfall",
        brand_tags=json.dumps([]),
        franchise_tags=json.dumps(["James Bond"]),
        universe_tags=json.dumps([]),
        source_property_tags=json.dumps(["James Bond"])
    )

    # 2. Insert non-Bond spy movie
    LibraryItemRepository.upsert(
        id="plex_bourne_identity",
        source="plex",
        rating_key="bourne",
        title="The Bourne Identity",
        normalized_title="thebourneidentity",
        year=2002,
        imdb_id="tt0258463",
        file_path="/movies/Bourne Identity.mkv",
        size_bytes=1000,
        synopsis="A man is picked up by a fishing boat, bullet-riddled and suffering from amnesia.",
        synopsis_hash="bournehash",
        synopsis_vector=encode_vector([0.0, 0.0, 0.0, 0.95] + [0.0] * 764),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-04T00:00:00Z"
    )
    LibraryItemRepository.update_tmdb_enrichment(
        id="plex_bourne_identity",
        brand_tags=json.dumps([]),
        franchise_tags=json.dumps([]),
        universe_tags=json.dumps([]),
        source_property_tags=json.dumps([])
    )

    # 3. Insert Star Wars movie
    LibraryItemRepository.upsert(
        id="plex_a_new_hope",
        source="plex",
        rating_key="sw4",
        title="Star Wars: Episode IV - A New Hope",
        normalized_title="starwarsepisodeivanewhope",
        year=1977,
        imdb_id="tt0076759",
        file_path="/movies/Star Wars A New Hope.mkv",
        size_bytes=1000,
        synopsis="Luke Skywalker joins forces with a Jedi Knight, a cocky pilot, a Wookiee and two droids.",
        synopsis_hash="sw4hash",
        synopsis_vector=encode_vector([0.0, 0.0, 0.0, 0.0, 1.0] + [0.0] * 763),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-04T00:00:00Z"
    )
    LibraryItemRepository.update_tmdb_enrichment(
        id="plex_a_new_hope",
        brand_tags=json.dumps(["Lucasfilm"]),
        franchise_tags=json.dumps(["Star Wars"]),
        universe_tags=json.dumps([]),
        source_property_tags=json.dumps(["Star Wars"])
    )

    # 4. Insert generic space movie
    LibraryItemRepository.upsert(
        id="plex_interstellar",
        source="plex",
        rating_key="interstellar",
        title="Interstellar",
        normalized_title="interstellar",
        year=2014,
        imdb_id="tt0816692",
        file_path="/movies/Interstellar.mkv",
        size_bytes=1000,
        synopsis="A team of explorers travel through a wormhole in space in an attempt to ensure humanity's survival.",
        synopsis_hash="interstellarhash",
        synopsis_vector=encode_vector([0.0, 0.0, 0.0, 0.0, 0.95] + [0.0] * 763),
        synopsis_vector_model="gemini-embedding-001",
        synopsis_vector_dim=768,
        synopsis_vector_updated_at="2026-06-04T00:00:00Z"
    )
    LibraryItemRepository.update_tmdb_enrichment(
        id="plex_interstellar",
        brand_tags=json.dumps([]),
        franchise_tags=json.dumps([]),
        universe_tags=json.dumps([]),
        source_property_tags=json.dumps([])
    )

    # Test "bond spy movies"
    # Should infer franchise "James Bond" (or source property "James Bond") and return ONLY Skyfall.
    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.0, 0.0, 0.0, 1.0] + [0.0] * 764, "gemini-embedding-001", 768, "gemini")
        res = await query_library_tool(semantic_query="bond spy movies", limit=5)

    assert res["ok"] is True
    movies = res["data"]["movies"]
    assert len(movies) == 1
    assert movies[0]["title"] == "Skyfall"
    routing = res["data"]["query_routing"]
    assert routing["inferred_franchise"] == "James Bond"
    assert "franchise" in routing["structured_filters_applied"]

    # Test "star wars sci-fi movies"
    # Should infer franchise "Star Wars" and return ONLY Star Wars: Episode IV - A New Hope.
    with patch("moviebot.tools.query_library_tool.get_embedding_result", new_callable=AsyncMock) as mock_embed:
        mock_embed.return_value = EmbeddingResult([0.0, 0.0, 0.0, 0.0, 1.0] + [0.0] * 763, "gemini-embedding-001", 768, "gemini")
        res = await query_library_tool(semantic_query="star wars sci-fi movies", limit=5)

    assert res["ok"] is True
    movies = res["data"]["movies"]
    assert len(movies) == 1
    assert movies[0]["title"] == "Star Wars: Episode IV - A New Hope"
    routing = res["data"]["query_routing"]
    assert routing["inferred_franchise"] == "Star Wars"
    assert "franchise" in routing["structured_filters_applied"]
