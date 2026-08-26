import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from moviebot.db.connection import init_db
from moviebot.db.cache_prewarm_repo import CachePrewarmRepository
from moviebot.core.background_prewarmer import (
    prewarm_title,
    run_cache_prewarm_cycle,
    get_recent_movie_frontier_candidates,
    advance_recent_movie_frontier,
    get_all_time_popular_movie_frontier_candidates,
    advance_all_time_popular_movie_frontier,
    MOVIE_RECENT_CURSOR_KEY,
    MOVIE_ALL_TIME_POPULAR_CURSOR_KEY,
)
from moviebot.db.repositories import KeyValueRepository

init_db()


@pytest.mark.asyncio
async def test_cache_prewarm_repo_lifecycle():
    # 1. Upsert a complete series pre-warm record
    CachePrewarmRepository.upsert(
        domain="tv_classic",
        title="Chicago Hope",
        season=0,
        reference_id="magnet:?xt=urn:btih:chicago_hope_test",
        release_title="Chicago.Hope.Complete.Series.720p.HDTV",
        resolution="720p",
        size_bytes=15000000000,
        formatted_size="15.0 GB",
        seeders=12,
        cached=True,
        score=95
    )

    # 2. Retrieve immediately
    item = CachePrewarmRepository.get("tv_classic", "Chicago Hope", season=0, max_age_hours=24)
    assert item is not None
    assert item["title"] == "Chicago Hope"
    assert item["season"] == 0
    assert item["cached"] is True
    assert item["resolution"] == "720p"
    assert item["seeders"] == 12

    # 3. Retrieve stats
    stats = CachePrewarmRepository.get_stats()
    assert stats["total_entries"] >= 1
    assert stats["total_cached"] >= 1
    assert "tv_classic" in stats["by_domain"]


@pytest.mark.asyncio
async def test_prewarm_title_saves_to_repo():
    mock_search = {
        "ok": True,
        "data": {
            "results": [
                {
                    "reference_id": "ref_friends_cached",
                    "title": "Friends.Complete.Series.S01-S10.1080p.BluRay",
                    "resolution": "1080p",
                    "formatted_size": "65.0 GB",
                    "seeders": 150,
                    "cached": True,
                    "_score": 98
                }
            ]
        }
    }

    with patch("moviebot.core.background_prewarmer.search_sources_tool", new_callable=AsyncMock) as mock_src:
        mock_src.return_value = mock_search

        res = await prewarm_title("Friends", domain="tv_classic", season=0)
        assert res is not None
        assert res["title"] == "Friends"
        assert res["cached"] is True

        cached_rec = CachePrewarmRepository.get("tv_classic", "Friends", season=0)
        assert cached_rec is not None
        assert cached_rec["reference_id"] == "ref_friends_cached"
        assert cached_rec["cached"] is True
        assert cached_rec["instant_cached"] is False
        assert cached_rec["external_stream_ready"] is True


@pytest.mark.asyncio
async def test_movie_prewarm_prefers_cached_browser_release_and_keeps_year():
    mock_search = {
        "ok": True,
        "data": {
            "results": [
                {
                    "reference_id": "ref_matrix_hevc",
                    "title": "The.Matrix.1999.2160p.WEB-DL.HEVC",
                    "seeders": 200,
                    "cached": True,
                },
                {
                    "reference_id": "ref_matrix_h264",
                    "title": "The.Matrix.1999.1080p.WEB-DL.H.264.AAC.mp4",
                    "seeders": 50,
                    "cached": True,
                },
            ]
        }
    }

    with patch("moviebot.core.background_prewarmer.search_sources_tool", new_callable=AsyncMock) as mock_src:
        mock_src.return_value = mock_search
        res = await prewarm_title("The Matrix", domain="movies", year=1999)

    assert res["cached"] is True
    assert res["browser_stream_ready"] is True
    cached_rec = CachePrewarmRepository.get("movies", "The Matrix", year=1999)
    assert cached_rec["reference_id"] == "ref_matrix_h264"
    assert cached_rec["year"] == 1999
    assert cached_rec["browser_stream_reference_id"] == "ref_matrix_h264"
    assert cached_rec["stream_reference_id"] == "ref_matrix_h264"
    assert cached_rec["instant_cached"] is True
    assert cached_rec["instant_download_ready"] is True


def test_recent_movie_frontier_starts_current_and_persists_cursor():
    class FakeProvider:
        def discover_movies(self, filters):
            from datetime import date

            current_year = date.today().year
            assert filters["primary_release_date.gte"] == f"{current_year}-01-01"
            assert filters["primary_release_date.lte"] == date.today().isoformat()
            assert filters["vote_count.gte"] == 25
            assert filters["sort_by"] == "popularity.desc"
            return {
                "total_pages": 1,
                "results": [
                    {"id": 2, "title": "Current Hit", "release_date": f"{current_year}-06-01", "popularity": 90, "vote_count": 500},
                    {"id": 1, "title": "Current Favorite", "release_date": f"{current_year}-01-01", "popularity": 50, "vote_count": 1000},
                ],
            }

    KeyValueRepository.delete(MOVIE_RECENT_CURSOR_KEY)
    try:
        candidates = get_recent_movie_frontier_candidates(limit=2, provider=FakeProvider())
        assert [c["title"] for c in candidates] == ["Current Hit", "Current Favorite"]
        advance_recent_movie_frontier(2)
        assert '"item_index": 2' in (KeyValueRepository.get(MOVIE_RECENT_CURSOR_KEY) or "")
    finally:
        KeyValueRepository.delete(MOVIE_RECENT_CURSOR_KEY)


def test_all_time_popular_frontier_uses_tmdb_popularity_and_persists_item_cursor():
    class FakeProvider:
        def discover_movies(self, filters):
            assert filters == {
                "vote_count.gte": 1000,
                "sort_by": "popularity.desc",
                "page": 1,
            }
            return {
                "total_pages": 3,
                "results": [
                    {"id": 2, "title": "Popular Second", "release_date": "1990-01-01", "popularity": 80, "vote_count": 1200},
                    {"id": 1, "title": "Popular First", "release_date": "2000-01-01", "popularity": 120, "vote_count": 5000},
                ],
            }

    KeyValueRepository.delete(MOVIE_ALL_TIME_POPULAR_CURSOR_KEY)
    try:
        candidates = get_all_time_popular_movie_frontier_candidates(limit=1, provider=FakeProvider())
        assert candidates[0]["title"] == "Popular First"
        assert candidates[0]["type"] == "movie_all_time_popular"
        advance_all_time_popular_movie_frontier(consumed_count=1, provider=FakeProvider())
        assert '"item_index": 1' in (KeyValueRepository.get(MOVIE_ALL_TIME_POPULAR_CURSOR_KEY) or "")
    finally:
        KeyValueRepository.delete(MOVIE_ALL_TIME_POPULAR_CURSOR_KEY)


@pytest.mark.asyncio
async def test_scoreboard_and_dropped_detection():
    # 1. Upsert a cached item
    CachePrewarmRepository.upsert(
        domain="tv_classic",
        title="Columbo",
        season=1,
        reference_id="magnet:?xt=urn:btih:columbo_s1",
        release_title="Columbo.S01.1080p",
        cached=True
    )

    # 2. Simulate AllDebrid re-verification where it dropped out of RAM
    updates = [{
        "id": "tv_classic:columbo:1",
        "cached": False,
        "was_cached": True
    }]
    reverify_stats = CachePrewarmRepository.batch_update_cache_status(updates)
    assert reverify_stats["dropped"] == 1

    # 3. Check status filtering
    dropped_items = CachePrewarmRepository.get_items(domain="tv_classic", status="dropped")
    assert any(it["title"] == "Columbo" and it["dropped"] is True for it in dropped_items)

    # 4. Check scoreboard stats
    sb = CachePrewarmRepository.get_scoreboard_stats(catalog_total=120)
    assert sb["total_tracked"] >= 1
    assert sb["dropped_count"] >= 1
    assert sb["frontier_to_go"] <= 120


def test_progressive_frontier_candidates():
    from moviebot.core.background_prewarmer import get_progressive_frontier_candidates
    candidates = get_progressive_frontier_candidates(limit=5)
    assert len(candidates) > 0
    assert "title" in candidates[0]
    assert "season" in candidates[0]
