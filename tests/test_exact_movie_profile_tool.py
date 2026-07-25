import json
from unittest.mock import patch

import pytest

from moviebot.db.connection import get_db_connection, init_db
from moviebot.db.repositories import LibraryItemRepository
from moviebot.tools.exact_movie_profile_tool import exact_movie_profile_tool
from moviebot.core.dedupe import normalize_title


@pytest.fixture
def temp_db_path(tmp_path):
    db_file = tmp_path / "test_exact_profile.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        init_db()
        yield db_file


def _insert_movie(item_id, rating_key, imdb_id="tt3228774", tmdb_id=566525):
    LibraryItemRepository.upsert(
        id=item_id,
        source="plex",
        rating_key=rating_key,
        title="Shang-Chi and the Legend of the Ten Rings",
        normalized_title=normalize_title("Shang-Chi and the Legend of the Ten Rings"),
        year=2021,
        imdb_id=imdb_id,
        file_path="F:/private/movies/shang-chi.mkv",
        size_bytes=1_000,
        genres=json.dumps(["Action", "Adventure", "Fantasy"]),
        directors=json.dumps(["Destin Daniel Cretton"]),
        cast=json.dumps(["Simu Liu", "Awkwafina", "Tony Leung"]),
        studios=json.dumps(["Marvel Studios"]),
        countries=json.dumps(["United States"]),
        content_rating="PG-13",
        tagline="You can't outrun your destiny.",
        originally_available_at="2021-09-03",
        runtime=132,
        synopsis="Shang-Chi confronts the past he thought he left behind.",
        metadata_refreshed_at="2026-07-15T12:00:00Z",
    )
    LibraryItemRepository.update_tmdb_enrichment(
        id=item_id,
        brand_tags=json.dumps(["Marvel"]),
        franchise_tags=json.dumps(["Shang-Chi"]),
        universe_tags=json.dumps(["Marvel Cinematic Universe"]),
        source_property_tags=json.dumps(["Marvel Comics"]),
        tmdb_id=tmdb_id,
    )


def test_exact_profile_uses_indexed_identity_and_redacts_private_fields(temp_db_path):
    _insert_movie("plex_shangchi", "57417")

    for kwargs, matched_by in [
        ({"rating_key": "57417"}, "rating_key"),
        ({"imdb_id": "tt3228774"}, "imdb_id"),
        ({"tmdb_id": 566525}, "tmdb_id"),
        ({"title": "Shang-Chi and the Legend of the Ten Rings", "year": 2021}, "title_year"),
    ]:
        result = exact_movie_profile_tool(**kwargs)
        assert result["ok"] is True
        assert result["data"]["status"] == "available"
        assert result["data"]["matched_by"] == matched_by
        profile = result["data"]["profile"]
        assert profile["runtime_minutes"] == 132
        assert profile["directors"] == ["Destin Daniel Cretton"]
        assert profile["universe_tags"] == ["Marvel Cinematic Universe"]
        serialized = json.dumps(result)
        assert "file_path" not in serialized
        assert "shang-chi.mkv" not in serialized
        assert "poster" not in serialized

    with get_db_connection() as conn:
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(library_items)").fetchall()}
    assert "idx_library_items_rating_key" in indexes
    assert "idx_library_items_imdb_id" in indexes
    assert "idx_library_items_tmdb_id" in indexes
    assert "idx_library_items_title_year" in indexes


def test_exact_profile_reports_not_found_and_ambiguous_without_fuzzy_matching(temp_db_path):
    _insert_movie("plex_one", "57417", imdb_id=None, tmdb_id=None)
    _insert_movie("plex_two", "other-key", imdb_id=None, tmdb_id=None)

    assert exact_movie_profile_tool(rating_key="missing")["data"]["status"] == "not_found"
    ambiguous = exact_movie_profile_tool(title="Shang-Chi and the Legend of the Ten Rings", year=2021)
    assert ambiguous["data"]["status"] == "ambiguous"
    assert "profile" not in ambiguous["data"]
