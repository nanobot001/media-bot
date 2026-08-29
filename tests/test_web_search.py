import pytest
import respx
import httpx
from datetime import datetime, timezone
from starlette.testclient import TestClient
from moviebot.api.webhook import app
from moviebot.config import settings
from moviebot.db.connection import init_db
from moviebot.core.release_parser import parse_release_details, format_size_bytes, is_browser_stream_compatible
from moviebot.db.cache_prewarm_repo import CachePrewarmRepository
from moviebot.core.availability_service import AvailabilityService
from moviebot.core.provider_cache_outcomes import check_cache_references
from moviebot.db.release_variant_repo import ReleaseVariantRepository
from moviebot.tools.search_sources_tool import search_sources_tool


@pytest.fixture
def search_test_env(monkeypatch, tmp_path):
    """Sets up temporary databases and client for search endpoints testing."""
    movies_db = tmp_path / "search_movies.sqlite3"
    tv_db = tmp_path / "search_tv.sqlite3"
    tv_classic_db = tmp_path / "search_tvclassic.sqlite3"

    monkeypatch.setattr(settings, "database_path", str(movies_db))
    monkeypatch.setattr(settings, "tv_database_path", str(tv_db))
    monkeypatch.setattr(settings, "tv_classic_database_path", str(tv_classic_db))
    monkeypatch.setattr(settings, "prowlarr_url", "https://prowlarr.test")
    monkeypatch.setattr(settings, "prowlarr_api_key", "fake_prowlarr_key")
    monkeypatch.setattr(settings, "alldebrid_api_key", "fake_alldebrid_key")

    async def eligible_movie_gate(**kwargs):
        title = str(kwargs.get("title") or "").lower()
        release_year = 2026 if "scary movie" in title else (2024 if title else 2020)
        return {
            "eligible": True,
            "reason": "ELIGIBLE",
            "release_date": f"{release_year}-01-01",
            "age_days": 0,
            "cutoff_date": "2020-03-06",
            "tmdb_id": kwargs.get("tmdb_id"),
            "source": "test",
            "actionable": True,
        }

    monkeypatch.setattr(
        "moviebot.api.web_routes._evaluate_movie_request",
        eligible_movie_gate,
    )

    init_db("movies")
    init_db("tv")
    init_db("tv_classic")

    client = TestClient(app)
    return client


def test_release_parser_metadata_extraction():
    """Verify release title parser extracts resolution, HDR, audio, codec, and release groups."""
    # 1. 4K UHD Remux with DV and Atmos
    title1 = "The.Batman.2022.2160p.UHD.Remux.HEVC.DV.TrueHD.7.1.Atmos-FraMeSToR"
    p1 = parse_release_details(title1)
    assert p1["resolution"] == "2160p"
    assert p1["source_type"] == "Remux"
    assert p1["quality_label"] == "2160p Remux"
    assert p1["hdr"] == "Dolby Vision"
    assert p1["codec"] == "HEVC (x265)"
    assert p1["audio"] == "Dolby Atmos"
    assert p1["channels"] == "7.1"
    assert p1["release_group"] == "FraMeSToR"

    # 2. 1080p Web-DL with DDP5.1
    title2 = "Reacher.S02E01.1080p.AMZN.WEB-DL.DDP5.1.H.264-FLUX"
    p2 = parse_release_details(title2)
    assert p2["resolution"] == "1080p"
    assert p2["source_type"] == "Web-DL"
    assert p2["quality_label"] == "1080p Web-DL"
    assert p2["codec"] == "x264"
    assert p2["audio"] == "DDP 5.1"
    assert p2["channels"] == "5.1"
    assert p2["release_group"] == "FLUX"

    # 3. 720p HDTV
    title3 = "Cheers.S01.720p.HDTV.x264-MockGroup"
    p3 = parse_release_details(title3)
    assert p3["resolution"] == "720p"
    assert p3["source_type"] == "HDTV"
    assert p3["quality_label"] == "720p HDTV"
    assert p3["codec"] == "x264"
    assert p3["release_group"] == "MockGroup"

    # 4. Format size bytes
    assert format_size_bytes(15000000000) == "13.97 GB"
    assert format_size_bytes(500000000) == "476.8 MB"
    assert format_size_bytes(0) == "0 MB"


def test_browser_stream_compatibility_is_conservative():
    assert is_browser_stream_compatible("Movie.1999.1080p.WEB-DL.H.264.AAC.mp4") is True
    assert is_browser_stream_compatible("Movie.1999.1080p.WEB-DL.H.264.DDP5.1.mkv") is False
    assert is_browser_stream_compatible("Movie.1999.1080p.WEB-DL.H.264.AAC.mkv") is False
    assert is_browser_stream_compatible("Movie.1999.1080p.WEB-DL.HEVC") is False
    assert is_browser_stream_compatible("Movie.1999.1080p.WEB-DL") is False


def test_api_search_does_not_promote_cached_filename_metadata(search_test_env):
    """A cached indexer title is download-ready until its selected file is verified."""
    prowlarr_releases = [
        {
            "title": "Dune.Part.Two.2024.1080p.WEB-DL.H.264.AAC-FLUX.mp4",
            "indexer": "TrackerA",
            "size": 5000000000,
            "seeders": 150,
            "downloadUrl": "magnet:?xt=urn:btih:dunehash1111111111111111111111111111111111&dn=Dune.Part.Two.1080p",
            "guid": "guid-dune-1",
        },
        {
            "title": "Dune.Part.Two.2024.2160p.WEB-DL.DV.HDR.HEVC.Atmos-FLUX",
            "indexer": "TrackerB",
            "size": 18000000000,
            "seeders": 80,
            "downloadUrl": "magnet:?xt=urn:btih:dunehash2222222222222222222222222222222222&dn=Dune.Part.Two.2160p",
            "guid": "guid-dune-2",
        },
        {
            "title": "Dune.Part.Two.2024.720p.HDTV.x264-Mock",
            "indexer": "TrackerC",
            "size": 2000000000,
            "seeders": 20,
            "downloadUrl": "magnet:?xt=urn:btih:dunehash3333333333333333333333333333333333&dn=Dune.Part.Two.720p",
            "guid": "guid-dune-3",
        }
    ]

    with respx.mock:
        respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_releases)
        # Mock AllDebrid: all three are cloud-cached. No selected provider
        # file has been verified yet, so none is browser-ready.
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(
            200,
            json={
                "status": "success",
                "data": {
                    "magnets": [
                        {
                            "magnet": "magnet:?xt=urn:btih:dunehash1111111111111111111111111111111111&dn=Dune.Part.Two.1080p",
                            "hash": "dunehash1111111111111111111111111111111111",
                            "ready": True,
                        },
                        {
                            "magnet": "magnet:?xt=urn:btih:dunehash2222222222222222222222222222222222&dn=Dune.Part.Two.2160p",
                            "hash": "dunehash2222222222222222222222222222222222",
                            "ready": True,
                        },
                        {
                            "magnet": "magnet:?xt=urn:btih:dunehash3333333333333333333333333333333333&dn=Dune.Part.Two.720p",
                            "hash": "dunehash3333333333333333333333333333333333",
                            "ready": True,
                        }
                    ]
                }
            }
        )

        response = search_test_env.get("/api/search?query=Dune%20Part%20Two&domain=movies")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["domain"] == "movies"
        assert data["count"] == 3
        assert data["cached_count"] == 0
        assert data["cloud_cached_count"] == 3
        assert data["external_cached_count"] == 3

        results = data["results"]
        # Cached releases remain available for external/download workflows,
        # but metadata alone cannot earn the browser badge.
        assert results[0]["cached"] is True
        assert results[0]["cache_badge"] == "external"
        assert results[0]["instant_cached"] is False
        assert results[0]["browser_stream_ready"] is False
        assert results[0]["resolution"] == "1080p"
        assert results[0]["stream_reference_id"] == results[0]["reference_id"]

        assert results[1]["cached"] is True
        assert results[1]["instant_cached"] is False
        assert results[1]["cache_badge"] == "external"
        assert results[1]["resolution"] == "2160p"
        assert results[1]["external_stream_ready"] is True

        assert results[2]["cached"] is True
        assert results[2]["instant_cached"] is False
        assert results[2]["cache_badge"] == "external"
        assert results[2]["resolution"] == "720p"


def test_api_search_promotes_only_exact_durable_browser_proof(search_test_env, monkeypatch):
    reference_id = "verified-scary-movie-reference"
    checked_at = datetime.now(timezone.utc).isoformat()

    CachePrewarmRepository.update_browser_stream_candidate(
        domain="movies",
        title="Scary Movie",
        year=2026,
        reference_id=reference_id,
        release_title="Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
        browser_verification={
            "status": "verified_browser_ready",
            "reference_id": reference_id,
            "actual_filename": "Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
            "evidence_source": "actual_filename",
        },
    )
    ReleaseVariantRepository.upsert_variant(
        domain="movies",
        title="Scary Movie",
        year=2026,
        reference_id=reference_id,
        release_title="Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
        ad_cache_status="cached",
        ad_checked_at=checked_at,
        direct_play_status="verified",
        direct_play_verified_at=checked_at,
        direct_play_evidence={"status": "verified_browser_ready", "verified": True},
    )
    projection = AvailabilityService.inspect(
        domain="movies", title="Scary Movie", year=2026
    )
    variant = projection["variants"][0]

    async def fake_search(**kwargs):
        return {
            "ok": True,
            "data": {
                "availability": projection,
                "results": [{
                    "reference_id": reference_id,
                    "title": "Scary.Movie.2026.1080p.WEBRip.x264.AAC.mp4",
                    "cached": True,
                    "seeders": 10,
                    "availability": projection,
                    "availability_state": projection["availability_state"],
                    "availability_tier": projection["availability_tier"],
                    "availability_scope": projection["media"],
                    "availability_coverage": projection["coverage"],
                    "variant_availability": variant,
                    "variant_availability_state": variant["availability_state"],
                    "browser_stream_ready": variant["browser_stream_ready"],
                    "external_stream_ready": variant["external_stream_ready"],
                    "instant_stream_status": variant["instant_stream_status"],
                }],
            },
        }
    monkeypatch.setattr("moviebot.api.web_routes.search_sources_tool", fake_search)

    response = search_test_env.get("/api/search?query=Scary%20Movie&domain=movies")
    result = response.json()["results"][0]
    assert response.status_code == 200
    assert result["browser_stream_ready"] is True
    assert result["cache_badge"] == "lightning"
    assert result["browser_stream_reference_id"] == reference_id


def test_api_search_propagates_library_ownership_to_each_release(search_test_env, monkeypatch):
    async def fake_search(**kwargs):
        return {
            "ok": True,
            "data": {
                "library_status": {
                    "in_library": True,
                    "title": "Star Wars: The Mandalorian and Grogu",
                    "year": 2026,
                },
                "results": [{
                    "reference_id": "owned-release",
                    "title": "The.Mandalorian.and.Grogu.2026.1080p.WEBRip.mp4",
                    "cached": True,
                }],
            },
        }

    monkeypatch.setattr("moviebot.api.web_routes.search_sources_tool", fake_search)

    response = search_test_env.get("/api/search?query=The%20Mandalorian%20and%20Grogu&domain=movies")

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["owned"] is True
    assert result["in_library"] is True


def test_api_search_tv_and_classic_tv(search_test_env):
    """Verify /api/search handles TV and Classic TV queries with season/episode filtering."""
    prowlarr_tv_results = [
        {
            "title": "Reacher.S02E01.1080p.WEB-DL.DDP5.1.Atmos-FLUX",
            "indexer": "TrackerA",
            "size": 3000000000,
            "seeders": 140,
            "downloadUrl": "magnet:?xt=urn:btih:reacherhash1111111111111111111111111111111111&dn=Reacher.S02E01",
            "guid": "guid-reacher-1",
        }
    ]

    with respx.mock:
        route = respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_tv_results)
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(
            200,
            json={
                "status": "success",
                "data": {
                    "magnets": [
                        {
                            "magnet": "magnet:?xt=urn:btih:reacherhash1111111111111111111111111111111111&dn=Reacher.S02E01",
                            "hash": "reacherhash1111111111111111111111111111111111",
                            "ready": True,
                        }
                    ]
                }
            }
        )

        response = search_test_env.get("/api/search?query=Reacher&domain=tv&season=2&episode=1")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert data["domain"] == "tv"
        assert data["season"] == 2
        assert data["episode"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["cached"] is True
        assert data["results"][0]["cloud_cached"] is True
        assert data["results"][0]["instant_cached"] is False
        assert data["results"][0]["cache_badge"] == "external"
        assert data["results"][0]["audio"] == "Dolby Atmos"
        assert "5000" in route.calls.last.request.url.params["categories"]


def test_api_search_graceful_degradation_when_alldebrid_fails(search_test_env):
    """Verify /api/search returns results cleanly even if AllDebrid API fails or times out."""
    prowlarr_releases = [
        {
            "title": "Gladiator.II.2024.1080p.WEB-DL",
            "indexer": "PublicTracker",
            "size": 4000000000,
            "seeders": 95,
            "downloadUrl": "magnet:?xt=urn:btih:gladhash111111111111111111111111111111111111&dn=Gladiator.II",
            "guid": "guid-glad-1",
        }
    ]

    with respx.mock:
        respx.get("https://prowlarr.test/api/v1/search").respond(200, json=prowlarr_releases)
        # AllDebrid returns 500 error
        respx.get(url__regex=r"https://api\.alldebrid\.com/v4\.1/magnet/upload.*").respond(500)

        response = search_test_env.get("/api/search?query=Gladiator%20II&domain=movies")
        assert response.status_code == 200
        data = response.json()
        assert data["ok"] is True
        assert len(data["results"]) == 1
        # Provider failure is non-fatal but remains unknown rather than uncached.
        assert data["results"][0]["cached"] is False
        assert data["results"][0]["cache_badge"] == "unknown"
        assert data["results"][0]["availability_state"] == "unknown"
        assert data["results"][0]["cache_status"] == "provider_error"
        assert data["results"][0]["cache_error"] == {
            "code": "AD_HTTP_ERROR",
            "retryable": True,
        }
        assert data["cache_provider_error_count"] == 1


@pytest.mark.asyncio
async def test_shared_cache_outcomes_distinguish_complete_partial_and_failures():
    refs = ["a" * 40, "b" * 40]

    class CompleteProvider:
        async def instant_check(self, references):
            assert references == refs
            return {
                "magnets": [
                    {"hash": refs[0], "ready": True},
                    {"hash": refs[1], "ready": False},
                ],
                "errors": [],
            }

    complete = await check_cache_references(refs, client=CompleteProvider())
    assert [row["status"] for row in complete["outcomes"]] == ["cached", "not_cached"]
    assert complete["summary"] == {
        "status": "complete",
        "candidate_count": 2,
        "checked_count": 2,
        "cached_count": 1,
        "uncached_count": 1,
        "unknown_count": 0,
        "provider_error_count": 0,
        "unresolvable_count": 0,
    }

    class PartialProvider:
        async def instant_check(self, references):
            return {
                "magnets": [{"hash": references[0], "ready": False}],
                "errors": [{
                    "code": "AD_PARTIAL_RESPONSE",
                    "failed_positions": [0, 1],
                }],
            }

    partial = await check_cache_references(refs, client=PartialProvider())
    assert [row["status"] for row in partial["outcomes"]] == ["not_cached", "unknown"]
    assert partial["summary"]["status"] == "partial"
    assert partial["summary"]["unknown_count"] == 1

    class TimeoutProvider:
        async def instant_check(self, references):
            raise httpx.ReadTimeout("timed out")

    timeout = await check_cache_references(refs, client=TimeoutProvider())
    assert {row["status"] for row in timeout["outcomes"]} == {"provider_error"}
    assert {row["error_code"] for row in timeout["outcomes"]} == {"AD_TIMEOUT"}

    class MalformedProvider:
        async def instant_check(self, references):
            return {"magnets": {"unexpected": True}}

    malformed = await check_cache_references(refs, client=MalformedProvider())
    assert {row["error_code"] for row in malformed["outcomes"]} == {
        "AD_MALFORMED_RESPONSE"
    }
    unresolvable = await check_cache_references(["", "local-reference-token"])
    assert unresolvable["outcomes"] == [
        {
            "status": "unresolvable",
            "error_code": "AD_REFERENCE_UNRESOLVABLE",
        },
        {
            "status": "unresolvable",
            "error_code": "AD_REFERENCE_UNRESOLVABLE",
        },
    ]


@pytest.mark.asyncio
async def test_search_population_retains_exact_variants_across_cycles(
    search_test_env,
    monkeypatch,
):
    releases = [
        {
            "reference_id": "catalog-remux",
            "title": "Catalog.Movie.2020.2160p.BluRay.Remux.HEVC.mkv",
            "size_bytes": 60_000_000_000,
            "seeders": 50,
            "indexer": "A",
            "cached": True,
            "cache_status": "cached",
            "cache_checked": True,
            "cache_error_code": None,
        },
        {
            "reference_id": "catalog-web",
            "title": "Catalog.Movie.2020.1080p.WEB-DL.x264.AAC.mp4",
            "size_bytes": 8_000_000_000,
            "seeders": 100,
            "indexer": "B",
            "cached": False,
            "cache_status": "not_cached",
            "cache_checked": True,
            "cache_error_code": None,
        },
        {
            "reference_id": "catalog-720",
            "title": "Catalog.Movie.2020.720p.WEBRip.x264.mkv",
            "size_bytes": 3_000_000_000,
            "seeders": 20,
            "indexer": "C",
            "cached": False,
            "cache_status": "not_cached",
            "cache_checked": True,
            "cache_error_code": None,
        },
        {
            "reference_id": "making-of",
            "title": "Catalog.Movie.The.Making.Of.2020.1080p.WEBRip.x264.mkv",
            "size_bytes": 2_000_000_000,
            "seeders": 5,
            "indexer": "D",
            "cached": True,
            "cache_status": "cached",
            "cache_checked": True,
            "cache_error_code": None,
        },
    ]
    releases.insert(3, dict(releases[1]))

    async def fake_search_movies(self, **kwargs):
        return [dict(row) for row in releases]

    monkeypatch.setattr(
        "moviebot.adapters.prowlarr_client.ProwlarrClient.search_movies",
        fake_search_movies,
    )
    eligibility = {
        "eligible": True,
        "reason": "ELIGIBLE",
        "release_date": "2020-01-01",
        "tmdb_id": 123,
    }
    first = await search_sources_tool(
        query="Catalog Movie",
        domain="movies",
        year=2020,
        tmdb_id=123,
        movie_eligibility=eligibility,
        cycle_id="cycle-one",
        source_vector="movie_recent",
    )
    assert first["data"]["catalog"]["discovered_count"] == 4
    assert first["data"]["catalog"]["retained_count"] == 3
    assert first["data"]["catalog"]["checked_count"] == 4
    assert first["data"]["catalog"]["cached_count"] == 1
    assert AvailabilityService.inspect(
        domain="movies", title="Catalog Movie", year=2020
    )["availability_state"] == "ad_cached"
    variants = ReleaseVariantRepository.list_variants(
        domain="movies", title="Catalog Movie", year=2020
    )
    assert len(variants) == 3
    first_seen = {row["variant_id"]: row["first_seen_at"] for row in variants}

    second = await search_sources_tool(
        query="Catalog Movie",
        domain="movies",
        year=2020,
        tmdb_id=123,
        movie_eligibility=eligibility,
        cycle_id="cycle-two",
        source_vector="movie_all_time_popular",
    )
    assert second["data"]["catalog"]["retained_count"] == 3
    rerun = ReleaseVariantRepository.list_variants(
        domain="movies", title="Catalog Movie", year=2020
    )
    assert len(rerun) == 3
    assert {row["variant_id"]: row["first_seen_at"] for row in rerun} == first_seen
    assert {row["last_observed_cycle_id"] for row in rerun} == {"cycle-two"}

    for release in releases:
        release["cached"] = False
        release["cache_status"] = "not_cached"
    third = await search_sources_tool(
        query="Catalog Movie",
        domain="movies",
        year=2020,
        tmdb_id=123,
        movie_eligibility=eligibility,
        cycle_id="cycle-three",
        source_vector="movie_recent",
    )
    assert third["data"]["catalog"]["uncached_count"] == 4
    assert AvailabilityService.inspect(
        domain="movies", title="Catalog Movie", year=2020
    )["availability_state"] == "not_cached"


@pytest.mark.asyncio
async def test_partial_search_check_cannot_derive_not_cached(
    search_test_env,
    monkeypatch,
):
    async def fake_search_movies(self, **kwargs):
        return [
            {
                "reference_id": "partial-known",
                "title": "Partial.Movie.2020.1080p.WEB-DL.x264.mkv",
                "cached": False,
                "cache_status": "not_cached",
                "cache_checked": True,
            },
            {
                "reference_id": "partial-missing",
                "title": "Partial.Movie.2020.2160p.WEB-DL.HEVC.mkv",
                "cached": False,
                "cache_status": "unknown",
                "cache_checked": False,
                "cache_error_code": "AD_PARTIAL_RESPONSE",
            },
        ]

    monkeypatch.setattr(
        "moviebot.adapters.prowlarr_client.ProwlarrClient.search_movies",
        fake_search_movies,
    )
    response = await search_sources_tool(
        query="Partial Movie",
        domain="movies",
        year=2020,
        movie_eligibility={
            "eligible": True,
            "release_date": "2020-01-01",
            "tmdb_id": 456,
        },
        cycle_id="partial-cycle",
    )
    assert response["data"]["catalog"]["unknown_count"] == 1
    state = AvailabilityService.inspect(
        domain="movies", title="Partial Movie", year=2020
    )
    assert state["coverage"]["status"] == "partial"
    assert state["availability_state"] == "unknown"
