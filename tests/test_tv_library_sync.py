import json
import pytest
import respx
import httpx
from unittest.mock import patch, MagicMock
from pathlib import Path

from moviebot.adapters.plex_client import PlexClient
from moviebot.config import settings
from moviebot.db.connection import get_db_connection, init_db, TV_SCHEMA_SQL
from moviebot.db.repositories import TVLibraryRepository
from moviebot.tools.sync_tv_library_tool import sync_tv_library_tool
from moviebot.tools.discover_media_tool import is_show_or_episode_owned, discover_media_tool
from moviebot.cli.tool_cli import main


@pytest.fixture
def temp_tv_db(tmp_path, monkeypatch):
    """Sets up temporary SQLite DB paths for movies, tv, and tv_classic domains."""
    movie_db = tmp_path / "moviebot.sqlite3"
    tv_db = tmp_path / "tvbot.sqlite3"
    tv_classic_db = tmp_path / "tvclassicbot.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movie_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))

    init_db("movies")
    init_db("tv")
    init_db("tv_classic")

    return {
        "movies": movie_db,
        "tv": tv_db,
        "tv_classic": tv_classic_db,
    }


def test_tv_schema_initialization(temp_tv_db):
    """Verify init_db('tv') creates tv_shows, tv_seasons, tv_episodes, and FTS5 tables."""
    for domain in ("tv", "tv_classic"):
        with get_db_connection(domain) as conn:
            cur = conn.cursor()
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cur.fetchall()}
            assert "tv_shows" in tables
            assert "tv_seasons" in tables
            assert "tv_episodes" in tables
            assert "tv_shows_fts" in tables


def test_tv_library_repository_crud(temp_tv_db):
    """Verify TVLibraryRepository show, season, and episode upserts and queries."""
    # 1. Upsert show
    TVLibraryRepository.upsert_show(
        id="plex:1001",
        rating_key="1001",
        title="Reacher",
        normalized_title="reacher",
        year=2022,
        imdb_id="tt9288030",
        tmdb_id=108978,
        tvdb_id=369792,
        genres=json.dumps(["Action", "Crime", "Drama"]),
        networks=json.dumps(["Amazon Prime Video"]),
        content_rating="TV-MA",
        synopsis="Jack Reacher was arrested for murder...",
        total_seasons=2,
        total_episodes=16,
        domain="tv",
    )

    # 2. Upsert season
    TVLibraryRepository.upsert_season(
        id="plex:1001:s1",
        show_id="plex:1001",
        season_number=1,
        title="Season 1",
        episode_count=8,
        domain="tv",
    )

    # 3. Upsert episodes
    for ep_num in range(1, 9):
        TVLibraryRepository.upsert_episode(
            id=f"plex:1001:s1:e{ep_num}",
            show_id="plex:1001",
            season_number=1,
            episode_number=ep_num,
            rating_key=f"200{ep_num}",
            title=f"Episode {ep_num}",
            resolution="1080p",
            size_bytes=2_000_000_000,
            domain="tv",
        )

    # 4. Query lookups
    show_by_id = TVLibraryRepository.get_show_by_id("plex:1001", domain="tv")
    assert show_by_id is not None
    assert show_by_id["title"] == "Reacher"
    assert show_by_id["tmdb_id"] == 108978
    assert show_by_id["imdb_id"] == "tt9288030"

    show_by_tmdb = TVLibraryRepository.get_show_by_tmdb_id(108978, domain="tv")
    assert show_by_tmdb is not None
    assert show_by_tmdb["id"] == "plex:1001"

    show_by_norm = TVLibraryRepository.get_show_by_normalized_title_and_year("reacher", 2022, domain="tv")
    assert show_by_norm is not None

    seasons = TVLibraryRepository.get_seasons_for_show("plex:1001", domain="tv")
    assert len(seasons) == 1
    assert seasons[0]["season_number"] == 1

    episodes = TVLibraryRepository.get_episodes_for_show("plex:1001", domain="tv")
    assert len(episodes) == 8

    owned_eps = TVLibraryRepository.get_owned_episodes("plex:1001", domain="tv")
    assert len(owned_eps) == 8
    assert (1, 1) in owned_eps
    assert (1, 8) in owned_eps
    assert (2, 1) not in owned_eps


def test_tv_ownership_checks(temp_tv_db):
    """Verify is_show_owned and is_episode_owned in TVLibraryRepository."""
    TVLibraryRepository.upsert_show(
        id="plex:500",
        rating_key="500",
        title="Cheers",
        normalized_title="cheers",
        year=1982,
        imdb_id="tt0083399",
        tmdb_id=196,
        domain="tv_classic",
    )
    TVLibraryRepository.upsert_episode(
        id="plex:500:s1:e1",
        show_id="plex:500",
        season_number=1,
        episode_number=1,
        title="Give Me a Ring Sometime",
        domain="tv_classic",
    )

    # Show ownership in tv_classic
    assert TVLibraryRepository.is_show_owned(tmdb_id=196, domain="tv_classic") is True
    assert TVLibraryRepository.is_show_owned(title="Cheers", year=1982, domain="tv_classic") is True
    assert TVLibraryRepository.is_show_owned(title="Cheers", domain="classic_tv") is True
    assert TVLibraryRepository.is_show_owned(tmdb_id=999999, domain="tv_classic") is False

    # Episode ownership
    assert TVLibraryRepository.is_episode_owned("Cheers", 1982, 1, 1, domain="tv_classic") is True
    assert TVLibraryRepository.is_episode_owned("Cheers", 1982, 1, 2, domain="tv_classic") is False


def test_canonical_dedup_helper(temp_tv_db):
    """Verify is_show_or_episode_owned helper across movies and tv domains."""
    TVLibraryRepository.upsert_show(
        id="plex:1001",
        title="Reacher",
        normalized_title="reacher",
        year=2022,
        tmdb_id=108978,
        domain="tv",
    )
    TVLibraryRepository.upsert_episode(
        id="plex:1001:s1:e1",
        show_id="plex:1001",
        season_number=1,
        episode_number=1,
        domain="tv",
    )

    # TV show level
    assert is_show_or_episode_owned("Reacher", year=2022, tmdb_id=108978, domain="tv") is True
    assert is_show_or_episode_owned("Severance", year=2022, domain="tv") is False

    # TV episode level
    assert is_show_or_episode_owned("Reacher", year=2022, season_number=1, episode_number=1, tmdb_id=108978, domain="tv") is True
    assert is_show_or_episode_owned("Reacher", year=2022, season_number=2, episode_number=1, tmdb_id=108978, domain="tv") is False


@pytest.mark.asyncio
async def test_plex_client_fetch_all_tv_shows(monkeypatch):
    """Verify PlexClient.fetch_all_tv_shows pulls show metadata and episode leaves."""
    monkeypatch.setattr(settings, "plex_url", "http://fake-plex:32400")
    monkeypatch.setattr(settings, "plex_token", "fake-token")

    client = PlexClient()

    sections_payload = {
        "MediaContainer": {
            "Directory": [
                {"key": "2", "title": "TV Shows", "type": "show", "agent": "tv.plex.agents.series"},
                {"key": "3", "title": "Classic TV", "type": "show", "agent": "tv.plex.agents.series"},
                {"key": "1", "title": "Movies", "type": "movie", "agent": "tv.plex.agents.movie"},
            ]
        }
    }

    tv_shows_payload = {
        "MediaContainer": {
            "Metadata": [
                {
                    "ratingKey": "888",
                    "title": "Breaking Bad",
                    "year": 2008,
                    "summary": "A chemistry teacher diagnosed with cancer...",
                    "contentRating": "TV-MA",
                    "childCount": 5,
                    "leafCount": 62,
                    "Genre": [{"tag": "Drama"}, {"tag": "Crime"}],
                    "Studio": [{"tag": "AMC"}],
                    "Guid": [
                        {"id": "imdb://tt0903747"},
                        {"id": "tmdb://1396"},
                        {"id": "tvdb://81189"}
                    ]
                }
            ]
        }
    }

    leaves_payload = {
        "MediaContainer": {
            "Metadata": [
                {
                    "ratingKey": "9001",
                    "parentIndex": 1,
                    "index": 1,
                    "title": "Pilot",
                    "originallyAvailableAt": "2008-01-20",
                    "summary": "Walter White discovers he has terminal lung cancer...",
                    "duration": 3480000,
                    "Media": [
                        {
                            "videoResolution": "1080",
                            "bitrate": 8000,
                            "Part": [{"file": "/media/tv/Breaking Bad/S01E01.mkv", "size": 2500000000}]
                        }
                    ]
                },
                {
                    "ratingKey": "9002",
                    "parentIndex": 1,
                    "index": 2,
                    "title": "Cat's in the Bag...",
                    "originallyAvailableAt": "2008-01-27",
                    "duration": 2880000,
                    "Media": [
                        {
                            "videoResolution": "1080",
                            "bitrate": 8000,
                            "Part": [{"file": "/media/tv/Breaking Bad/S01E02.mkv", "size": 2200000000}]
                        }
                    ]
                }
            ]
        }
    }

    with respx.mock(base_url="http://fake-plex:32400") as respx_mock:
        respx_mock.get("/library/sections").respond(200, json=sections_payload)
        respx_mock.get("/library/sections/2/all").respond(200, json=tv_shows_payload)
        respx_mock.get("/library/metadata/888/allLeaves").respond(200, json=leaves_payload)

        shows = await client.fetch_all_tv_shows(domain="tv")

        assert len(shows) == 1
        show = shows[0]
        assert show["title"] == "Breaking Bad"
        assert show["year"] == 2008
        assert show["tmdb_id"] == 1396
        assert show["imdb_id"] == "tt0903747"
        assert show["tvdb_id"] == 81189
        assert show["content_rating"] == "TV-MA"
        assert len(show["seasons"]) == 1
        assert len(show["episodes"]) == 2
        assert show["episodes"][0]["title"] == "Pilot"
        assert show["episodes"][0]["file_path"] == "/media/tv/Breaking Bad/S01E01.mkv"


@pytest.mark.asyncio
async def test_sync_tv_library_tool_live_and_dry_run(temp_tv_db):
    """Verify sync_tv_library_tool executes in dry-run and live database modes."""
    fake_client = MagicMock(spec=PlexClient)
    fake_shows = [
        {
            "id": "plex:777",
            "rating_key": "777",
            "title": "Slow Horses",
            "year": 2022,
            "imdb_id": "tt5875444",
            "tmdb_id": 99966,
            "tvdb_id": 372439,
            "genres": json.dumps(["Thriller", "Drama"]),
            "networks": json.dumps(["Apple TV+"]),
            "content_rating": "TV-MA",
            "tagline": "Slough House",
            "synopsis": "Jackson Lamb leads a team of disgraced MI5 agents...",
            "total_seasons": 3,
            "total_episodes": 18,
            "poster_url": "http://poster",
            "banner_url": "http://banner",
            "seasons": [
                {"id": "plex:777:s1", "season_number": 1, "title": "Season 1", "episode_count": 6},
                {"id": "plex:777:s2", "season_number": 2, "title": "Season 2", "episode_count": 6},
            ],
            "episodes": [
                {"id": "plex:777:s1:e1", "season_number": 1, "episode_number": 1, "title": "Failure's Contagious"},
                {"id": "plex:777:s1:e2", "season_number": 1, "episode_number": 2, "title": "Work Drinks"},
            ]
        }
    ]

    async def mock_fetch_tv(domain="tv"):
        return fake_shows

    fake_client.fetch_all_tv_shows = mock_fetch_tv

    # 1. Dry run
    dry_res = await sync_tv_library_tool(domain="tv", dry_run=True, plex_client=fake_client)
    assert dry_res["ok"] is True
    assert dry_res["data"]["dry_run"] is True
    assert dry_res["data"]["shows_synced"] == 1
    assert dry_res["data"]["seasons_synced"] == 2
    assert dry_res["data"]["episodes_synced"] == 2

    # Verify DB is still empty after dry run
    assert TVLibraryRepository.get_show_by_id("plex:777", domain="tv") is None

    # 2. Live run
    live_res = await sync_tv_library_tool(domain="tv", dry_run=False, plex_client=fake_client)
    assert live_res["ok"] is True
    assert live_res["data"]["dry_run"] is False
    assert live_res["data"]["shows_synced"] == 1

    # Verify DB contains the records
    show = TVLibraryRepository.get_show_by_id("plex:777", domain="tv")
    assert show is not None
    assert show["title"] == "Slow Horses"
    assert show["tmdb_id"] == 99966

    seasons = TVLibraryRepository.get_seasons_for_show("plex:777", domain="tv")
    assert len(seasons) == 2

    episodes = TVLibraryRepository.get_episodes_for_show("plex:777", domain="tv")
    assert len(episodes) == 2


@pytest.mark.asyncio
async def test_sync_tv_library_tool_invalid_domain():
    """Verify sync_tv_library_tool returns structured error for unsupported domains."""
    res = await sync_tv_library_tool(domain="unsupported_domain")
    assert res["ok"] is False
    assert res["error"]["code"] == "INVALID_DOMAIN"


@pytest.mark.asyncio
async def test_discover_media_with_synced_tv_dedup(temp_tv_db):
    """Verify discover_media_tool accurately marks [OWNED] on TV shows present in SQLite."""
    # Seed TV show into tvbot.sqlite3
    TVLibraryRepository.upsert_show(
        id="plex:108978",
        title="Reacher",
        normalized_title="reacher",
        year=2022,
        tmdb_id=108978,
        domain="tv",
    )

    # Discover TV feed
    fake_tv_results = {
        "results": [
            {
                "id": 108978,
                "name": "Reacher",
                "first_air_date": "2022-02-03",
                "vote_average": 8.1,
                "vote_count": 2100,
                "genre_ids": [10759, 18, 80],
                "overview": "Jack Reacher...",
                "poster_path": "/reacher.jpg"
            },
            {
                "id": 999999,
                "name": "Brand New Show",
                "first_air_date": "2024-01-01",
                "vote_average": 7.5,
                "vote_count": 50,
                "genre_ids": [18],
                "overview": "New synopsis...",
                "poster_path": "/new.jpg"
            }
        ]
    }

    with respx.mock(base_url="https://api.themoviedb.org/3") as respx_mock:
        respx_mock.get("/trending/tv/week").respond(200, json=fake_tv_results)

        # Unfiltered discovery
        res = await discover_media_tool(domain="tv", feed="trending")
        assert res["ok"] is True
        items = res["data"]["results"]
        assert len(items) == 2
        assert items[0]["title"] == "Reacher"
        assert items[0]["owned"] is True
        assert items[1]["title"] == "Brand New Show"
        assert items[1]["owned"] is False

        # Filtered with exclude_owned=True
        res_filtered = await discover_media_tool(domain="tv", feed="trending", exclude_owned=True)
        assert res_filtered["ok"] is True
        filtered_items = res_filtered["data"]["results"]
        assert len(filtered_items) == 1
        assert filtered_items[0]["title"] == "Brand New Show"



def test_cli_sync_tv_invocation(capsys):
    """Verify CLI sync-tv subcommand parsing and formatted table / JSON output."""
    with patch("moviebot.tools.sync_tv_library_tool.sync_tv_library_tool") as mock_tool:
        mock_tool.return_value = {
            "ok": True,
            "tool": "sync_tv_library_tool",
            "timestamp": "2026-08-23T00:00:00Z",
            "data": {
                "domain": "tv",
                "dry_run": True,
                "shows_synced": 1,
                "seasons_synced": 3,
                "episodes_synced": 18,
                "shows": [
                    {"id": "plex:100", "title": "Reacher", "year": 2022, "seasons_count": 2, "episodes_count": 16}
                ]
            }
        }

        # Table output
        with patch("sys.argv", ["tool_cli.py", "sync-tv", "--domain", "tv", "--dry-run"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            captured = capsys.readouterr().out
            assert "TV Library Sync: TV [DRY-RUN]" in captured
            assert "Shows Synced:    1" in captured
            assert "Reacher (2022): 2 seasons, 16 episodes" in captured

        # JSON output
        with patch("sys.argv", ["tool_cli.py", "sync-tv", "--domain", "tv", "--dry-run", "--json"]):
            with pytest.raises(SystemExit) as exc:
                main()
            assert exc.value.code == 0
            captured = capsys.readouterr().out
            parsed = json.loads(captured)
            assert parsed["ok"] is True
            assert parsed["data"]["shows_synced"] == 1
