import json
import uuid
import pytest
import respx
import httpx
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from moviebot.config import settings
from moviebot.db.connection import init_db, get_db_connection
from moviebot.db.repositories import SearchResultRepository, DownloadJobRepository, TVLibraryRepository
from moviebot.adapters.alldebrid_client import AllDebridClient
from moviebot.adapters.idm_adapter import IdmAdapter
from moviebot.core.tv_file_selection import parse_tv_torrent_files, filter_unowned_episodes, extract_season_episode
from moviebot.tools.enqueue_download_tool import enqueue_download_tool, _jit_enrich_tv_show
from moviebot.cli.tool_cli import cmd_download


@pytest.fixture
def temp_dbs(monkeypatch, tmp_path):
    """Sets up temporary databases for movies, tv, and classic tv."""
    movies_db = tmp_path / "movies.sqlite3"
    tv_db = tmp_path / "tv.sqlite3"
    tv_classic_db = tmp_path / "tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))
    monkeypatch.setattr(settings, "output_dir", r"F:\_temp\movies")
    monkeypatch.setattr(settings, "tv_output_dir", r"F:\_temp\tv")
    monkeypatch.setattr(settings, "tv_classic_output_dir", r"F:\temp\Classic Tv")
    monkeypatch.setattr(settings, "alldebrid_api_key", "fake_alldebrid_key")

    init_db("movies")
    init_db("tv")
    init_db("tv_classic")

    yield {
        "movies": movies_db,
        "tv": tv_db,
        "tv_classic": tv_classic_db,
    }


def test_tv_file_selection_regex_parsing():
    """Verify SxxExx extraction across various scene and p2p release naming patterns."""
    assert extract_season_episode("Reacher.S02E01.1080p.mkv") == (2, 1)
    assert extract_season_episode("reacher.s02e08.720p.mkv") == (2, 8)
    assert extract_season_episode("Cheers.1x05.The.Coachs.Daughter.avi") == (1, 5)
    assert extract_season_episode("Season 3 Episode 12.mp4") == (3, 12)
    assert extract_season_episode("Episode 04.mkv", path="Shogun/Season 01") == (1, 4)
    assert extract_season_episode("02.mkv", path="Shogun/S02") == (2, 2)


def test_parse_tv_torrent_files_junk_pruning():
    """Verify that junk files (samples, nfo, trailers, extras) are cleanly pruned."""
    raw_files = [
        {"id": 1, "name": "Reacher.S02E01.1080p.mkv", "size": 2500000000, "link": "https://debrid/1"},
        {"id": 2, "name": "Reacher.S02E02.1080p.mkv", "size": 2600000000, "link": "https://debrid/2"},
        {"id": 3, "name": "Reacher.S02E01.sample.mkv", "size": 50000000, "link": "https://debrid/3"},
        {"id": 4, "name": "Reacher.S02.trailer.mp4", "size": 80000000, "link": "https://debrid/4"},
        {"id": 5, "name": "Reacher.S02.featurette.mkv", "size": 120000000, "link": "https://debrid/5"},
        {"id": 6, "name": "reacher.s02.nfo", "size": 4000, "link": "https://debrid/6"},
        {"id": 7, "name": "reacher.s02.txt", "size": 2000, "link": "https://debrid/7"},
        {"id": 8, "name": "poster.jpg", "size": 500000, "link": "https://debrid/8"},
    ]

    parsed = parse_tv_torrent_files(raw_files)
    assert len(parsed) == 2
    assert parsed[0]["episode"] == 1
    assert parsed[0]["name"] == "Reacher.S02E01.1080p.mkv"
    assert parsed[1]["episode"] == 2
    assert parsed[1]["name"] == "Reacher.S02E02.1080p.mkv"


def test_filter_unowned_episodes():
    """Verify that owned episodes are filtered out."""
    episodes = [
        {"season": 1, "episode": 1, "name": "E01.mkv"},
        {"season": 1, "episode": 2, "name": "E02.mkv"},
        {"season": 1, "episode": 3, "name": "E03.mkv"},
    ]
    owned = {(1, 1), (1, 2)}
    unowned = filter_unowned_episodes(episodes, owned)
    assert len(unowned) == 1
    assert unowned[0]["episode"] == 3


@pytest.mark.asyncio
async def test_alldebrid_batch_unlock(temp_dbs):
    """Verify AllDebridClient.unlock_links handles batch unlocking."""
    client = AllDebridClient()
    links = ["https://debrid.com/l1", "https://debrid.com/l2"]

    with respx.mock(base_url="https://api.alldebrid.com/v4.1") as respx_mock:
        respx_mock.get("/link/unlock", params={"agent": "moviebot", "apikey": "fake_alldebrid_key", "link": "https://debrid.com/l1"}).respond(
            200, json={"status": "success", "data": {"link": "https://stream.alldebrid.com/stream1"}}
        )
        respx_mock.get("/link/unlock", params={"agent": "moviebot", "apikey": "fake_alldebrid_key", "link": "https://debrid.com/l2"}).respond(
            200, json={"status": "success", "data": {"link": "https://stream.alldebrid.com/stream2"}}
        )

        unlocked = await client.unlock_links(links)
        assert len(unlocked) == 2
        assert unlocked[0] == "https://stream.alldebrid.com/stream1"
        assert unlocked[1] == "https://stream.alldebrid.com/stream2"


@pytest.mark.asyncio
async def test_idm_adapter_send_batch():
    """Verify IdmAdapter.send_batch_to_idm formats and dry-runs batch requests."""
    adapter = IdmAdapter()
    downloads = [
        {"download_url": "https://stream1", "output_folder": r"F:\_temp\tv", "file_name": "E01.mkv"},
        {"download_url": "https://stream2", "output_folder": r"F:\_temp\tv", "file_name": "E02.mkv"},
    ]

    results = await adapter.send_batch_to_idm(downloads, dry_run=True)
    assert len(results) == 2
    assert results[0]["output_folder"] == r"F:\_temp\tv"
    assert results[0]["file_name"] == "E01.mkv"
    assert results[0]["routing"]["status"] in ("dry_run", "success")



@pytest.mark.asyncio
async def test_enqueue_download_tv_season_pack(temp_dbs):
    """Verify full TV download pipeline routes to F:\\_temp\\tv and creates per-episode download jobs."""
    # Seed search record in tv domain
    token_id = "token-reacher-s02"
    SearchResultRepository.insert(
        id=token_id,
        query_string="Reacher S02",
        indexer="ThePirateBay",
        title="Reacher.S02.1080p.WEB-DL",
        size_bytes=10000000000,
        seeders=150,
        magnet_uri_hash="hash123",
        raw_json_payload=json.dumps({"downloadUrl": "magnet:?xt=urn:btih:hash123&dn=Reacher.S02"}),
        domain="tv"
    )

    res = await enqueue_download_tool(
        reference_id=token_id,
        domain="tv",
        dry_run=True,
    )

    assert res["ok"] is True
    assert res["data"]["domain"] == "tv"
    assert res["data"]["target_dir"] == r"F:\_temp\tv"
    assert res["data"]["enqueued_count"] == 2
    assert len(res["data"]["jobs"]) == 2

    # Verify download_jobs rows in tv database
    jobs = DownloadJobRepository.get_all_jobs(domain="tv")
    assert len(jobs) == 2
    assert any("S01E01" in j["selected_file_name"] for j in jobs)
    assert any("S01E02" in j["selected_file_name"] for j in jobs)
    assert jobs[0]["target_dir"] == r"F:\_temp\tv"


@pytest.mark.asyncio
async def test_enqueue_download_classic_tv(temp_dbs):
    """Verify Classic TV download pipeline routes to F:\\temp\\Classic Tv."""
    token_id = "token-cheers-s01"
    SearchResultRepository.insert(
        id=token_id,
        query_string="Cheers S01",
        indexer="ThePirateBay",
        title="Cheers.S01.1080p.BluRay",
        size_bytes=20000000000,
        seeders=50,
        magnet_uri_hash="hashcheers",
        raw_json_payload=json.dumps({"downloadUrl": "magnet:?xt=urn:btih:hashcheers&dn=Cheers.S01"}),
        domain="tv_classic"
    )

    res = await enqueue_download_tool(
        reference_id=token_id,
        domain="tv_classic",
        dry_run=True,
    )

    assert res["ok"] is True
    assert res["data"]["target_dir"] == r"F:\temp\Classic Tv"
    assert res["data"]["enqueued_count"] == 2

    jobs = DownloadJobRepository.get_all_jobs(domain="tv_classic")
    assert len(jobs) == 2
    assert jobs[0]["target_dir"] == r"F:\temp\Classic Tv"


@pytest.mark.asyncio
async def test_enqueue_download_movies_backward_compatibility(temp_dbs):
    """Verify movie downloads continue to route to F:\\_temp\\movies with single job."""
    token_id = "token-dune-movie"
    SearchResultRepository.insert(
        id=token_id,
        query_string="Dune",
        indexer="YTS",
        title="Dune (2021) 1080p BluRay",
        size_bytes=2500000000,
        seeders=200,
        magnet_uri_hash="hashdune",
        raw_json_payload=json.dumps({"downloadUrl": "magnet:?xt=urn:btih:hashdune&dn=Dune"}),
        domain="movies"
    )

    res = await enqueue_download_tool(
        reference_id=token_id,
        domain="movies",
        dry_run=True,
    )

    assert res["ok"] is True
    assert res["data"]["target_dir"] == r"F:\_temp\movies"
    assert res["data"]["selected_file"] == "Dune (2021) 1080p BluRay.mkv"

    jobs = DownloadJobRepository.get_all_jobs(domain="movies")
    assert len(jobs) == 1
    assert jobs[0]["target_dir"] == r"F:\_temp\movies"


@pytest.mark.asyncio
async def test_cli_download_command_execution(capsys, temp_dbs):
    """Verify CLI download command with domain and dry-run parameters."""
    token_id = "cli-test-token"
    SearchResultRepository.insert(
        id=token_id,
        query_string="Reacher",
        indexer="TorrentGalaxy",
        title="Reacher.S01.1080p",
        size_bytes=5000000000,
        seeders=80,
        magnet_uri_hash="hashcli",
        raw_json_payload=json.dumps({"downloadUrl": "magnet:?xt=urn:btih:hashcli&dn=Reacher"}),
        domain="tv"
    )

    args = MagicMock()
    args.id = token_id
    args.domain = "tv"
    args.dry_run = True
    args.file_id = None
    args.file_ids = None

    exit_code = await cmd_download(args)
    assert exit_code == 0
    captured = capsys.readouterr().out
    assert "Enqueuing download for reference ID: cli-test-token" in captured
    assert "F:\\\\_temp\\\\tv" in captured or "F:\\_temp\\tv" in captured
