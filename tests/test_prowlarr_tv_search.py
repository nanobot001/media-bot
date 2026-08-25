import json
import uuid
import pytest
import respx
import httpx
from pathlib import Path
from unittest.mock import patch, MagicMock

from moviebot.config import settings
from moviebot.db.connection import init_db, get_db_connection
from moviebot.db.repositories import SearchResultRepository
from moviebot.adapters.prowlarr_client import ProwlarrClient
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.cli.tool_cli import cmd_search, cmd_search_tv


@pytest.fixture
def temp_dbs(monkeypatch, tmp_path):
    """Sets up temporary databases for movies, tv, and classic tv."""
    movies_db = tmp_path / "movies.sqlite3"
    tv_db = tmp_path / "tv.sqlite3"
    tv_classic_db = tmp_path / "tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))
    monkeypatch.setattr(settings, "prowlarr_url", "https://prowlarr.test")
    monkeypatch.setattr(settings, "prowlarr_api_key", "fake_prowlarr_key")
    monkeypatch.setattr(settings, "alldebrid_api_key", "fake_alldebrid_key")

    init_db("movies")
    init_db("tv")
    init_db("tv_classic")

    yield {
        "movies": movies_db,
        "tv": tv_db,
        "tv_classic": tv_classic_db,
    }


@pytest.mark.asyncio
async def test_prowlarr_search_tv_query_formatting(temp_dbs):
    """Verify that search_tv generates correct query strings for shows, seasons, and episodes."""
    client = ProwlarrClient()

    with respx.mock(base_url="https://prowlarr.test") as respx_mock:
        # 1. Show only
        route1 = respx_mock.get("/api/v1/search").respond(
            200,
            json=[
                {
                    "title": "Reacher.Complete.Series.1080p",
                    "indexer": "PublicTracker",
                    "size": 50000000000,
                    "seeders": 100,
                    "downloadUrl": "magnet:?xt=urn:btih:aabbccddeeff00112233445566778899aabbccdd&dn=Reacher",
                    "guid": "guid-1",
                }
            ]
        )
        res1 = await client.search_tv(query="Reacher", check_cache=False)
        assert len(res1) == 1
        assert route1.calls.last.request.url.params["query"] == "Reacher"
        assert "5000" in route1.calls.last.request.url.params["categories"]
        assert route1.calls.last.request.url.params["type"] == "search"


        # 2. Season pack
        route2 = respx_mock.get("/api/v1/search").respond(
            200,
            json=[
                {
                    "title": "Reacher.S02.1080p.BluRay",
                    "indexer": "PublicTracker",
                    "size": 25000000000,
                    "seeders": 80,
                    "downloadUrl": "magnet:?xt=urn:btih:112233445566778899aabbccddeeff0011223344&dn=Reacher.S02",
                    "guid": "guid-2",
                }
            ]
        )
        res2 = await client.search_tv(query="Reacher", season=2, check_cache=False)
        assert len(res2) == 1
        assert route2.calls.last.request.url.params["query"] == "Reacher S02"

        # 3. Individual episode
        route3 = respx_mock.get("/api/v1/search").respond(
            200,
            json=[
                {
                    "title": "Reacher.S02E01.1080p.WEB-DL",
                    "indexer": "PublicTracker",
                    "size": 3000000000,
                    "seeders": 150,
                    "downloadUrl": "magnet:?xt=urn:btih:33445566778899aabbccddeeff00112233445566&dn=Reacher.S02E01",
                    "guid": "guid-3",
                }
            ]
        )
        res3 = await client.search_tv(query="Reacher", season=2, episode=1, check_cache=False)
        assert len(res3) == 1
        assert route3.calls.last.request.url.params["query"] == "Reacher S02E01"


@pytest.mark.asyncio
async def test_prowlarr_tv_search_with_instant_cache(temp_dbs):
    """Verify that search results are badged with AllDebrid instant cache status."""
    client = ProwlarrClient()

    prowlarr_results = [
        {
            "title": "Cheers.S01.1080p.BluRay.x264",
            "indexer": "TrackerA",
            "size": 20000000000,
            "seeders": 45,
            "downloadUrl": "magnet:?xt=urn:btih:hash111111111111111111111111111111111111&dn=Cheers.S01",
            "guid": "guid-cheers-1",
        },
        {
            "title": "Cheers.S01.720p.HDTV",
            "indexer": "TrackerB",
            "size": 10000000000,
            "seeders": 10,
            "downloadUrl": "magnet:?xt=urn:btih:hash222222222222222222222222222222222222&dn=Cheers.S01.720p",
            "guid": "guid-cheers-2",
        }
    ]

    with respx.mock:
        respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_results)
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(
            200,
            json={
                "status": "success",
                "data": {
                    "magnets": [
                        {
                            "magnet": "magnet:?xt=urn:btih:hash111111111111111111111111111111111111&dn=Cheers.S01",
                            "hash": "hash111111111111111111111111111111111111",
                            "ready": True,
                        },
                        {
                            "magnet": "magnet:?xt=urn:btih:hash222222222222222222222222222222222222&dn=Cheers.S01.720p",
                            "hash": "hash222222222222222222222222222222222222",
                            "ready": False,
                        }
                    ]
                }
            }
        )

        results = await client.search_tv(query="Cheers", season=1, domain="tv_classic", check_cache=True)
        assert len(results) == 2
        assert results[0]["title"] == "Cheers.S01.1080p.BluRay.x264"
        assert results[0]["cached"] is True
        assert results[1]["title"] == "Cheers.S01.720p.HDTV"
        assert results[1]["cached"] is False

        # Verify token was saved in tv_classic SQLite database
        token_id = results[0]["reference_id"]
        saved = SearchResultRepository.get_by_id(token_id, domain="tv_classic")
        assert saved is not None
        assert saved["title"] == "Cheers.S01.1080p.BluRay.x264"
        assert "hash111111" in saved["raw_json_payload"]


@pytest.mark.asyncio
async def test_search_sources_tool_multi_domain(temp_dbs):
    """Verify search_sources_tool correctly routes to movies, tv, and classic_tv."""
    mock_prowlarr = [
        {
            "title": "Andor.S01.1080p.WEB-DL",
            "indexer": "PublicTracker",
            "size": 15000000000,
            "seeders": 120,
            "downloadUrl": "magnet:?xt=urn:btih:andorhash123456789012345678901234567890&dn=Andor",
            "guid": "andor-guid",
        }
    ]

    with respx.mock:
        respx.get("https://prowlarr.test/api/v1/search").respond(200, json=mock_prowlarr)
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(
            200,
            json={"status": "success", "data": {"magnets": [{"magnet": mock_prowlarr[0]["downloadUrl"], "hash": "andorhash123456789012345678901234567890", "ready": True}]}}
        )

        # Test TV domain
        res_tv = await search_sources_tool(query="Andor", domain="tv", season=1)
        assert res_tv["ok"] is True
        assert res_tv["data"]["domain"] == "tv"
        assert res_tv["data"]["season"] == 1
        assert len(res_tv["data"]["results"]) == 1
        assert res_tv["data"]["results"][0]["cached"] is True

        # Test token resolution in tv DB
        token = res_tv["data"]["results"][0]["reference_id"]
        row = SearchResultRepository.get_by_id(token, domain="tv")
        assert row is not None
        assert row["title"] == "Andor.S01.1080p.WEB-DL"


@pytest.mark.asyncio
async def test_cli_search_tv_command(capsys, temp_dbs):
    """Verify CLI search-tv command formatting and output."""
    mock_results = {
        "ok": True,
        "tool": "search_sources_tool",
        "timestamp": "2026-08-23T00:00:00Z",
        "data": {
            "domain": "tv",
            "query": "Reacher",
            "season": 2,
            "episode": 1,
            "total_results": 1,
            "results": [
                {
                    "reference_id": "tok12345",
                    "title": "Reacher.S02E01.1080p.AMZN.WEB-DL.DDP5.1.H.264",
                    "size_bytes": 2500000000,
                    "seeders": 185,
                    "indexer": "TorrentGalaxy",
                    "published_at": "2023-12-15T00:00:00Z",
                    "cached": True,
                }
            ]
        }
    }

    with patch("moviebot.cli.tool_cli.search_sources_tool", return_value=mock_results):
        args = MagicMock()
        args.query = "Reacher"
        args.domain = "tv"
        args.season = 2
        args.episode = 1
        args.imdb = None
        args.tvdb = None
        args.limit = 10
        args.json = False

        exit_code = await cmd_search_tv(args)
        assert exit_code == 0

        captured = capsys.readouterr().out
        assert "Search Results for 'Reacher' [Domain: TV] [S02E01]" in captured
        assert "Reacher.S02E01.1080p.AMZN.WEB-DL.DDP5.1.H.264 [⚡ CACHED]" in captured
        assert "Token ID: tok12345" in captured
