import pytest
import sqlite3
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from moviebot.db.connection import get_db_connection, init_db
from moviebot.db.repositories import LibraryItemRepository
from moviebot.config import settings
from moviebot.bot.discord_app import build_movie_detail_embed, ensure_poster_url

@pytest.fixture(autouse=True)
def setup_test_db(monkeypatch):
    db_dir = Path("scratch") / "poster-integration-tests"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / f"test_moviebot_{uuid.uuid4().hex}.db"
    monkeypatch.setattr(settings, "database_path", str(db_file))
    init_db()
    yield

def test_poster_url_repository_ops():
    # 1. Test upsert saves poster_url
    LibraryItemRepository.upsert(
        id="movie_1",
        source="plex",
        rating_key="123",
        title="Test Movie",
        normalized_title="test movie",
        year=2024,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        poster_url="https://example.com/poster.jpg"
    )
    
    movie = LibraryItemRepository.get_by_id("movie_1")
    assert movie is not None
    assert movie["poster_url"] == "https://example.com/poster.jpg"
    
    # 2. Test upsert with None preserves existing poster_url (COALESCE)
    LibraryItemRepository.upsert(
        id="movie_1",
        source="plex",
        rating_key="123",
        title="Test Movie",
        normalized_title="test movie",
        year=2024,
        imdb_id=None,
        file_path=None,
        size_bytes=None,
        poster_url=None
    )
    
    movie = LibraryItemRepository.get_by_id("movie_1")
    assert movie["poster_url"] == "https://example.com/poster.jpg"
    
    # 3. Test update_tmdb_enrichment updates poster_url if provided
    LibraryItemRepository.update_tmdb_enrichment(
        id="movie_1",
        poster_url="https://example.com/poster_new.jpg"
    )
    movie = LibraryItemRepository.get_by_id("movie_1")
    assert movie["poster_url"] == "https://example.com/poster_new.jpg"

    # 4. Test update_tmdb_enrichment with None preserves existing poster_url (COALESCE)
    LibraryItemRepository.update_tmdb_enrichment(
        id="movie_1",
        poster_url=None
    )
    movie = LibraryItemRepository.get_by_id("movie_1")
    assert movie["poster_url"] == "https://example.com/poster_new.jpg"

    # 5. Test update_poster_url
    LibraryItemRepository.update_poster_url("movie_1", "https://example.com/poster_manual.jpg")
    movie = LibraryItemRepository.get_by_id("movie_1")
    assert movie["poster_url"] == "https://example.com/poster_manual.jpg"

@pytest.mark.asyncio
async def test_ensure_poster_url_dynamic_fetch():
    item = {
        "id": "movie_2",
        "title": "Dynamic Movie",
        "year": 2023,
        "imdb_id": "tt1234567"
    }
    
    # Insert initial item without poster_url
    LibraryItemRepository.upsert(
        id=item["id"],
        source="plex",
        rating_key="456",
        title=item["title"],
        normalized_title="dynamic movie",
        year=item["year"],
        imdb_id=item["imdb_id"],
        file_path=None,
        size_bytes=None,
        poster_url=None
    )
    
    mock_facts = {
        "tmdb_id": 99999,
        "poster_path": "/path_to_poster.jpg"
    }
    
    with patch("moviebot.tools.tmdb_fact_provider.TMDbFactProvider.get_facts", return_value=mock_facts):
        await ensure_poster_url(item)
        
    assert item["poster_url"] == "https://image.tmdb.org/t/p/w500/path_to_poster.jpg"
    
    # Verify saved to DB
    movie = LibraryItemRepository.get_by_id("movie_2")
    assert movie["poster_url"] == "https://image.tmdb.org/t/p/w500/path_to_poster.jpg"

def test_build_movie_detail_embed_poster():
    item = {
        "title": "Poster Embed Movie",
        "year": 2022,
        "poster_url": "https://example.com/embed_poster.jpg"
    }
    embed = build_movie_detail_embed(item)
    assert embed.image.url == "https://example.com/embed_poster.jpg"
    assert embed.thumbnail.url == "https://example.com/embed_poster.jpg"

@pytest.mark.asyncio
async def test_slash_movie_fetches_and_displays_poster():
    from moviebot.bot.discord_app import slash_movie
    from moviebot.core.dedupe import normalize_title

    LibraryItemRepository.upsert(
        id="movie_3",
        source="plex",
        rating_key="789",
        title="Poster Command Movie",
        normalized_title=normalize_title("Poster Command Movie"),
        year=2024,
        imdb_id="tt7654321",
        file_path=None,
        size_bytes=None,
        poster_url=None
    )

    interaction = MagicMock()
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    mock_facts = {
        "tmdb_id": 777,
        "poster_url": "https://image.tmdb.org/t/p/w500/full_url_poster.jpg"
    }

    with patch("moviebot.tools.tmdb_fact_provider.TMDbFactProvider.get_facts", return_value=mock_facts):
        await slash_movie.callback(interaction, title="Poster Command Movie", year=2024)

    interaction.followup.send.assert_awaited_once()
    _, kwargs = interaction.followup.send.call_args
    embed = kwargs["embed"]
    assert embed.thumbnail.url == "https://image.tmdb.org/t/p/w500/full_url_poster.jpg"
    assert embed.image.url == "https://image.tmdb.org/t/p/w500/full_url_poster.jpg"
