import datetime as dt
import importlib
import json

import pytest

from moviebot.core.background_prewarmer import prewarm_title
from moviebot.config import settings
from moviebot.core.movie_quality_gate import (
    ELIGIBLE,
    LOW_QUALITY_SOURCE,
    RELEASE_DATE_UNAVAILABLE,
    RELEASE_WINDOW_NOT_ELIGIBLE,
    assess_movie_release,
    evaluate_movie_eligibility,
    filter_movie_releases,
)
from moviebot.db.cache_prewarm_repo import CachePrewarmRepository
from moviebot.db.connection import init_db
from moviebot.db.repositories import SearchResultRepository


def test_movie_release_window_is_inclusive_at_65_days():
    today = dt.date(2026, 8, 27)

    eligible = evaluate_movie_eligibility(
        authoritative_release_date="2026-06-23",
        today=today,
    )
    recent = evaluate_movie_eligibility(
        authoritative_release_date="2026-06-24",
        today=today,
    )

    assert eligible["eligible"] is True
    assert eligible["reason"] == ELIGIBLE
    assert eligible["age_days"] == 65
    assert recent["eligible"] is False
    assert recent["reason"] == RELEASE_WINDOW_NOT_ELIGIBLE
    assert recent["age_days"] == 64


def test_movie_gate_fails_closed_when_authoritative_date_is_missing_or_invalid():
    missing = evaluate_movie_eligibility(
        title="A Known Movie",
        year=2026,
        authoritative_release_date=None,
        provider=object(),
        today=dt.date(2026, 8, 27),
    )
    invalid = evaluate_movie_eligibility(
        authoritative_release_date="not-a-date",
        today=dt.date(2026, 8, 27),
    )

    assert missing["eligible"] is False
    assert missing["reason"] == RELEASE_DATE_UNAVAILABLE
    assert invalid["eligible"] is False
    assert invalid["reason"] == RELEASE_DATE_UNAVAILABLE
    assert missing["actionable"] is False
    assert invalid["actionable"] is False


def test_movie_release_marker_is_a_secondary_quality_defense():
    eligibility = evaluate_movie_eligibility(
        authoritative_release_date="2020-01-01",
        today=dt.date(2026, 8, 27),
    )
    clean = {"title": "The.Movie.2020.1080p.WEB-DL"}
    cam = {"title": "The.Movie.2020.1080p.CAM"}

    clean_decision = assess_movie_release(clean, eligibility)
    cam_decision = assess_movie_release(cam, eligibility)

    assert clean_decision["eligible"] is True
    assert clean_decision["reason"] == ELIGIBLE
    assert cam_decision["eligible"] is False
    assert cam_decision["reason"] == LOW_QUALITY_SOURCE
    assert cam_decision["candidate_title"] == cam["title"]


def test_movie_filter_keeps_only_actionable_releases_and_sanitizes_rejections():
    eligibility = evaluate_movie_eligibility(
        authoritative_release_date="2020-01-01",
        today=dt.date(2026, 8, 27),
    )
    releases = [
        {
            "title": "The.Movie.2020.1080p.WEB-DL",
            "reference_id": "clean-ref",
            "download_url": "magnet:?xt=urn:btih:clean",
            "indexer": "TrackerA",
            "size_bytes": 123,
            "seeders": 12,
        },
        {
            "title": "The.Movie.2020.1080p.HDTS",
            "reference_id": "bad-ref",
            "download_url": "magnet:?xt=urn:btih:bad",
            "indexer": "TrackerB",
            "size_bytes": 456,
            "seeders": 3,
        },
    ]

    accepted, rejected = filter_movie_releases(releases, eligibility)

    assert [item["reference_id"] for item in accepted] == ["clean-ref"]
    assert accepted[0]["quality_gate"]["reason"] == ELIGIBLE
    assert [item["reference_id"] for item in rejected] == ["bad-ref"]
    assert rejected[0]["quality_gate"]["reason"] == LOW_QUALITY_SOURCE
    assert "download_url" not in rejected[0]
    assert rejected[0]["actionable"] is False


@pytest.mark.asyncio
async def test_movie_search_gate_rejects_before_provider_search(monkeypatch):
    search_module = importlib.import_module("moviebot.tools.search_sources_tool")
    provider_calls = []

    class FakeProwlarrClient:
        async def search_movies(self, **kwargs):
            provider_calls.append(kwargs)
            raise AssertionError("rejected movies must not reach Prowlarr")

    rejected = {
        "eligible": False,
        "reason": RELEASE_WINDOW_NOT_ELIGIBLE,
        "release_date": "2026-08-01",
        "age_days": 26,
        "cutoff_date": "2026-06-23",
        "tmdb_id": 123,
        "source": "test",
        "actionable": False,
    }
    monkeypatch.setattr(search_module, "ProwlarrClient", FakeProwlarrClient)
    monkeypatch.setattr(
        search_module,
        "evaluate_movie_eligibility",
        lambda **kwargs: rejected,
    )
    monkeypatch.setattr(
        search_module,
        "_check_library_ownership",
        lambda **kwargs: {"in_library": False, "owned": False},
    )

    result = await search_module.search_sources_tool(
        query="Recent Movie",
        domain="movies",
        year=2026,
    )

    assert result["ok"] is True
    assert result["data"]["results"] == []
    assert result["data"]["eligibility"] == rejected
    assert provider_calls == []


@pytest.mark.asyncio
async def test_rejected_movie_prewarm_does_not_write_cache(monkeypatch):
    rejected = {
        "eligible": False,
        "reason": RELEASE_DATE_UNAVAILABLE,
        "release_date": None,
        "age_days": None,
        "cutoff_date": "2026-06-23",
        "tmdb_id": None,
        "source": None,
        "actionable": False,
    }
    upsert_calls = []

    async def fake_search(**kwargs):
        return {
            "ok": True,
            "data": {
                "results": [
                    {
                        "title": "Unknown.Movie.2026.1080p.WEB-DL",
                        "reference_id": "should-not-be-written",
                        "cached": True,
                    }
                ],
                "eligibility": rejected,
            },
        }

    monkeypatch.setattr(
        "moviebot.core.background_prewarmer.search_sources_tool",
        fake_search,
    )
    monkeypatch.setattr(
        CachePrewarmRepository,
        "upsert",
        lambda **kwargs: upsert_calls.append(kwargs),
    )

    result = await prewarm_title(
        "Unknown Movie",
        domain="movies",
        year=2026,
    )

    assert result["cached"] is False
    assert result["quality_gate"] == rejected
    assert upsert_calls == []


@pytest.mark.asyncio
async def test_direct_reference_enqueue_cannot_bypass_movie_gate(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "movies.sqlite3"))
    init_db("movies")
    SearchResultRepository.insert(
        id="recent-movie-reference",
        query_string="Recent Movie",
        indexer="Tracker",
        title="Recent.Movie.2026.1080p.WEB-DL",
        size_bytes=100,
        seeders=10,
        magnet_uri_hash="recent-hash",
        raw_json_payload=json.dumps({
            "downloadUrl": "magnet:?xt=urn:btih:recent",
        }),
        domain="movies",
    )
    rejected = {
        "eligible": False,
        "reason": RELEASE_WINDOW_NOT_ELIGIBLE,
        "release_date": "2026-08-01",
        "age_days": 26,
        "cutoff_date": "2026-06-23",
        "tmdb_id": None,
        "source": "test",
        "actionable": False,
    }
    enqueue_module = importlib.import_module("moviebot.tools.enqueue_download_tool")
    monkeypatch.setattr(
        enqueue_module,
        "evaluate_movie_eligibility",
        lambda **kwargs: rejected,
    )

    result = await enqueue_module.enqueue_download_tool(
        reference_id="recent-movie-reference",
        domain="movies",
        dry_run=True,
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "MOVIE_QUALITY_GATE_REJECTED"
    assert result["error"]["quality_gate"]["eligible"] is False
    assert result["error"]["quality_gate"]["reason"] == RELEASE_WINDOW_NOT_ELIGIBLE
