import json
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch
import httpx
import pytest

from moviebot.config import settings
from moviebot.db.connection import init_db, get_db_connection, SCHEMA_SQL
from moviebot.db.repositories import LibraryItemRepository, TVLibraryRepository
from moviebot.tools.tmdb_fact_provider import TMDbFactProvider

from moviebot.tools.discover_media_tool import (
    discover_media_tool,
    _resolve_genre_id,
    _resolve_network_id,
    _resolve_date_range,
    DECADE_RANGES,
)
from moviebot.cli.tool_cli import cmd_discover


@pytest.fixture
def temp_dbs(monkeypatch):
    """Sets up temporary databases for movies, tv, and classic tv."""
    scratch_dir = Path("scratch") / "discover-tests" / uuid.uuid4().hex
    scratch_dir.mkdir(parents=True, exist_ok=True)

    movies_db = scratch_dir / "movies.sqlite3"
    tv_db = scratch_dir / "tv.sqlite3"
    tv_classic_db = scratch_dir / "tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))

    init_db("movies")
    init_db("tv")
    init_db("tv_classic")

    with get_db_connection("tv") as conn:
        conn.executescript(SCHEMA_SQL)
    with get_db_connection("tv_classic") as conn:
        conn.executescript(SCHEMA_SQL)

    yield {
        "movies": movies_db,
        "tv": tv_db,
        "tv_classic": tv_classic_db,
    }



# ============================================================================
# TMDbFactProvider TV Extension Tests
# ============================================================================

def test_tmdb_get_tv_id_by_imdb_id():
    provider = TMDbFactProvider(api_key="fake-key")
    with patch.object(provider, "_get_json") as mock_get:
        mock_get.return_value = {
            "tv_results": [{"id": 1399, "name": "Game of Thrones"}]
        }
        tv_id = provider.get_tv_id_by_imdb_id("tt0944947")
        assert tv_id == 1399
        mock_get.assert_called_once_with("find/tt0944947", {"external_source": "imdb_id"})


def test_tmdb_get_tv_id_by_title_year():
    provider = TMDbFactProvider(api_key="fake-key")
    with patch.object(provider, "_get_json") as mock_get:
        mock_get.return_value = {
            "results": [{"id": 1396, "name": "Breaking Bad"}]
        }
        tv_id = provider.get_tv_id_by_title_year("Breaking Bad", 2008)
        assert tv_id == 1396
        mock_get.assert_called_once_with("search/tv", {"query": "Breaking Bad", "first_air_date_year": "2008"})


def test_tmdb_get_tv_show_facts_structured():
    provider = TMDbFactProvider(api_key="fake-key")
    with patch.object(provider, "_get_json") as mock_get:
        mock_get.return_value = {
            "id": 1396,
            "name": "Breaking Bad",
            "overview": "A chemistry teacher diagnosed with cancer...",
            "first_air_date": "2008-01-20",
            "last_air_date": "2013-09-29",
            "status": "Ended",
            "number_of_seasons": 5,
            "number_of_episodes": 62,
            "seasons": [{"season_number": 1, "episode_count": 7}],
            "networks": [{"name": "AMC"}],
            "production_companies": [{"name": "Sony Pictures Television"}],
            "genres": [{"name": "Drama"}, {"name": "Crime"}],
            "keywords": {"results": [{"name": "drug dealer"}, {"name": "methamphetamine"}]},
            "content_ratings": {
                "results": [
                    {"iso_3166_1": "GB", "rating": "18"},
                    {"iso_3166_1": "US", "rating": "TV-MA"},
                ]
            },
            "poster_path": "/ztkUQFLlC19CCMYHW9o1zWhJRNq.jpg",
            "backdrop_path": "/tsRy63Mu5cu8etL1X7ZLyf7UP1M.jpg",
            "vote_average": 8.9,
            "vote_count": 14000,
        }

        facts = provider.get_tv_show_facts(1396)
        assert facts is not None
        assert facts["source"] == "tmdb"
        assert facts["tmdb_id"] == 1396
        assert facts["title"] == "Breaking Bad"
        assert facts["overview"].startswith("A chemistry teacher")
        assert facts["genres"] == ["Drama", "Crime"]
        assert facts["networks"] == ["AMC"]
        assert facts["content_rating"] == "TV-MA"
        assert facts["number_of_seasons"] == 5
        assert facts["number_of_episodes"] == 62
        assert facts["keywords"] == ["drug dealer", "methamphetamine"]
        assert facts["poster_url"] == "https://image.tmdb.org/t/p/w500/ztkUQFLlC19CCMYHW9o1zWhJRNq.jpg"
        assert facts["vote_average"] == 8.9


def test_tmdb_get_tv_season_facts():
    provider = TMDbFactProvider(api_key="fake-key")
    with patch.object(provider, "_get_json") as mock_get:
        mock_get.return_value = {
            "season_number": 1,
            "name": "Season 1",
            "overview": "High school chemistry teacher Walter White...",
            "air_date": "2008-01-20",
            "poster_path": "/1yeAQ8T3Yp5o8pQ8hB.jpg",
            "episodes": [
                {
                    "episode_number": 1,
                    "name": "Pilot",
                    "overview": "When an unassuming high school chemistry teacher...",
                    "air_date": "2008-01-20",
                    "vote_average": 8.3,
                    "still_path": "/ydlY3iPfeOogA.jpg",
                },
                {
                    "episode_number": 2,
                    "name": "Cat's in the Bag...",
                    "overview": "Walt and Jesse attempt to dispose of the bodies...",
                    "air_date": "2008-01-27",
                    "vote_average": 8.0,
                    "still_path": "/kZ3Y5p7r9.jpg",
                }
            ]
        }

        season_facts = provider.get_tv_season_facts(1396, 1)
        assert season_facts is not None
        assert season_facts["tv_id"] == 1396
        assert season_facts["season_number"] == 1
        assert len(season_facts["episodes"]) == 2
        assert season_facts["episodes"][0]["name"] == "Pilot"
        assert season_facts["episodes"][0]["episode_number"] == 1


def test_tmdb_trending_and_discover():
    provider = TMDbFactProvider(api_key="fake-key")
    with patch.object(provider, "_get_json") as mock_get:
        mock_get.return_value = {"results": [{"id": 1, "title": "Inception"}]}

        provider.get_trending_movies("week")
        mock_get.assert_called_with("trending/movie/week", None)

        provider.get_trending_tv("day")
        mock_get.assert_called_with("trending/tv/day", None)

        provider.discover_movies({"sort_by": "popularity.desc"})
        mock_get.assert_called_with("discover/movie", {"sort_by": "popularity.desc"})

        provider.discover_tv({"sort_by": "vote_average.desc"})
        mock_get.assert_called_with("discover/tv", {"sort_by": "vote_average.desc"})


# ============================================================================
# Helpers & Presets Tests
# ============================================================================

def test_resolve_genre_id():
    assert _resolve_genre_id("Action", is_tv=False) == 28
    assert _resolve_genre_id("Action", is_tv=True) == 10759
    assert _resolve_genre_id("Comedy", is_tv=False) == 35
    assert _resolve_genre_id("Comedy", is_tv=True) == 35
    assert _resolve_genre_id("Sci-Fi", is_tv=False) == 878
    assert _resolve_genre_id("Sci-Fi", is_tv=True) == 10765
    assert _resolve_genre_id("878", is_tv=False) == 878
    assert _resolve_genre_id("UnknownGenre", is_tv=False) is None


def test_resolve_network_id():
    assert _resolve_network_id("NBC") == "6"
    assert _resolve_network_id("cbs") == "16"
    assert _resolve_network_id("HBO") == "49"
    assert _resolve_network_id("123") == "123"


def test_resolve_date_range():
    # Decade preset
    start, end = _resolve_date_range(decade="80s")
    assert start == "1980-01-01"
    assert end == "1989-12-31"

    # Year range
    start, end = _resolve_date_range(year_range="1975-1982")
    assert start == "1975-01-01"
    assert end == "1982-12-31"

    # Single year
    start, end = _resolve_date_range(year_range="1999")
    assert start == "1999-01-01"
    assert end == "1999-12-31"

    # Default max date
    start, end = _resolve_date_range(default_max_date="2010-01-01")
    assert start is None
    assert end == "2010-01-01"


# ============================================================================
# Discovery Tool Functional Tests
# ============================================================================

@pytest.mark.asyncio
async def test_discover_media_tool_invalid_domain():
    res = await discover_media_tool(domain="invalid_domain")
    assert res["ok"] is False
    assert res["error"]["code"] == "INVALID_DOMAIN"


@pytest.mark.asyncio
async def test_discover_media_movies_trending(temp_dbs):
    mock_provider = MagicMock()
    mock_provider.get_trending_movies.return_value = {
        "results": [
            {
                "id": 101,
                "title": "Dune: Part Two",
                "overview": "Paul Atreides unites with Chani...",
                "release_date": "2024-03-01",
                "vote_average": 8.3,
                "vote_count": 5200,
                "popularity": 350.5,
                "genre_ids": [878, 12],
                "poster_path": "/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg",
            }
        ]
    }

    res = await discover_media_tool(domain="movies", feed="trending", tmdb_provider=mock_provider)
    assert res["ok"] is True
    assert res["data"]["domain"] == "movies"
    assert res["data"]["feed"] == "trending"
    assert len(res["data"]["results"]) == 1

    item = res["data"]["results"][0]
    assert item["tmdb_id"] == 101
    assert item["title"] == "Dune: Part Two"
    assert item["year"] == 2024
    assert item["vote_average"] == 8.3
    assert item["genres"] == ["Science Fiction", "Adventure"]
    assert item["poster_url"] == "https://image.tmdb.org/t/p/w500/1pdfLvkbY9ohJlCjQH2CZjjYVvJ.jpg"
    assert item["owned"] is False


@pytest.mark.asyncio
async def test_discover_media_classic_tv_with_presets_and_dedup(temp_dbs):
    # Insert owned classic show in tv_classic DB
    TVLibraryRepository.upsert_show(
        id="plex:10",
        title="Cheers",
        normalized_title="cheers",
        year=1982,
        tmdb_id=192,
        domain="tv_classic",
    )

    mock_provider = MagicMock()

    mock_provider.discover_tv.return_value = {
        "results": [
            {
                "id": 192,
                "name": "Cheers",
                "overview": "The regulars of the Boston bar Cheers share their lives...",
                "first_air_date": "1982-09-30",
                "vote_average": 7.9,
                "vote_count": 450,
                "popularity": 45.2,
                "genre_ids": [35],
                "poster_path": "/cheers.jpg",
            },
            {
                "id": 180,
                "name": "Miami Vice",
                "overview": "Two undercover detectives work Vice in Miami...",
                "first_air_date": "1984-09-16",
                "vote_average": 7.5,
                "vote_count": 300,
                "popularity": 38.0,
                "genre_ids": [80, 18],
                "poster_path": "/miamivice.jpg",
            }
        ]
    }

    # Test 1: Without exclude_owned -> Cheers is owned=True, Miami Vice is owned=False
    res = await discover_media_tool(
        domain="classic_tv",
        feed="popular",
        decade="80s",
        network="NBC",
        exclude_owned=False,
        tmdb_provider=mock_provider,
    )
    assert res["ok"] is True
    assert len(res["data"]["results"]) == 2
    assert res["data"]["results"][0]["title"] == "Cheers"
    assert res["data"]["results"][0]["owned"] is True
    assert res["data"]["results"][1]["title"] == "Miami Vice"
    assert res["data"]["results"][1]["owned"] is False

    # Check discover_tv called with 80s range and NBC network
    args, kwargs = mock_provider.discover_tv.call_args
    call_params = args[0]
    assert call_params.get("with_status") == "3|4"
    assert call_params.get("first_air_date.gte") == "1980-01-01"
    assert call_params.get("first_air_date.lte") == "1989-12-31"
    assert call_params.get("with_networks") == "6"

    # Test 2: With exclude_owned=True -> Cheers is filtered out
    res_filtered = await discover_media_tool(
        domain="classic_tv",
        feed="popular",
        decade="80s",
        network="NBC",
        exclude_owned=True,
        tmdb_provider=mock_provider,
    )
    assert res_filtered["ok"] is True
    assert len(res_filtered["data"]["results"]) == 1
    assert res_filtered["data"]["results"][0]["title"] == "Miami Vice"
    assert res_filtered["data"]["results"][0]["owned"] is False


@pytest.mark.asyncio
async def test_discover_media_tv_genre_and_rating_filter(temp_dbs):
    mock_provider = MagicMock()
    mock_provider.discover_tv.return_value = {
        "results": [
            {
                "id": 1396,
                "name": "Breaking Bad",
                "overview": "A high school chemistry teacher...",
                "first_air_date": "2008-01-20",
                "vote_average": 8.9,
                "vote_count": 14000,
                "popularity": 120.0,
                "genre_ids": [18, 80],
                "poster_path": "/bb.jpg",
            }
        ]
    }

    res = await discover_media_tool(
        domain="tv",
        feed="top_rated",
        genre="Drama",
        min_rating=8.0,
        limit=5,
        tmdb_provider=mock_provider,
    )
    assert res["ok"] is True
    assert len(res["data"]["results"]) == 1
    assert res["data"]["results"][0]["title"] == "Breaking Bad"

    args, kwargs = mock_provider.discover_tv.call_args
    call_params = args[0]
    assert call_params.get("sort_by") == "vote_average.desc"
    assert call_params.get("with_genres") == "18"
    assert call_params.get("vote_average.gte") == "8.0"


# ============================================================================
# CLI Command Test
# ============================================================================

@pytest.mark.asyncio
async def test_cli_cmd_discover_json_and_table(capsys):
    mock_res = {
        "ok": True,
        "tool": "discover_media_tool",
        "timestamp": "2026-08-23T00:00:00Z",
        "data": {
            "domain": "classic_tv",
            "feed": "popular",
            "total_results": 1,
            "results": [
                {
                    "tmdb_id": 192,
                    "title": "Cheers",
                    "year": 1982,
                    "vote_average": 7.9,
                    "vote_count": 450,
                    "genres": ["Comedy"],
                    "overview": "Where everybody knows your name.",
                    "poster_url": "https://image.tmdb.org/t/p/w500/cheers.jpg",
                    "owned": True,
                }
            ]
        }
    }

    with patch("moviebot.cli.tool_cli.discover_media_tool", new_callable=MagicMock) as mock_tool:
        # Define an async return value for mock_tool
        async def async_return(*args, **kwargs):
            return mock_res
        mock_tool.side_effect = async_return

        args = MagicMock()
        args.domain = "classic_tv"
        args.feed = "popular"
        args.genre = "Comedy"
        args.min_rating = 7.0
        args.year_range = None
        args.decade = "80s"
        args.language = "en"
        args.network = "NBC"
        args.studio = None
        args.exclude_owned = False
        args.time_window = "week"
        args.limit = 10
        args.json = False

        exit_code = await cmd_discover(args)
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "=== Discover CLASSIC_TV [Popular] (1 results) ===" in captured.out
        assert "Cheers (1982) [OWNED]" in captured.out
        assert "Rating: 7.9 (450 votes)" in captured.out
        assert "Synopsis: Where everybody knows your name." in captured.out

        # JSON mode
        args.json = True
        exit_code = await cmd_discover(args)
        assert exit_code == 0
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert parsed["ok"] is True
        assert parsed["data"]["domain"] == "classic_tv"
