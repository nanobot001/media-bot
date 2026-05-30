import pytest
import respx
import httpx
from moviebot.adapters.plex_client import PlexClient

@pytest.mark.asyncio
@respx.mock
async def test_unmatch_item_success():
    plex = PlexClient()
    plex.url = "http://plex.test"
    plex.token = "fake_token"

    route = respx.put("http://plex.test/library/metadata/12345/unmatch").respond(status_code=200)
    
    res = await plex.unmatch_item("12345")
    assert res is True
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_unmatch_item_failure():
    plex = PlexClient()
    plex.url = "http://plex.test"
    plex.token = "fake_token"

    route = respx.put("http://plex.test/library/metadata/12345/unmatch").respond(status_code=500)
    
    res = await plex.unmatch_item("12345")
    assert res is False
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_get_matches_success():
    plex = PlexClient()
    plex.url = "http://plex.test"
    plex.token = "fake_token"

    mock_response = {
        "MediaContainer": {
            "SearchResult": [
                {
                    "guid": "plex://movie/predator",
                    "name": "Predator",
                    "year": 1987,
                    "score": 99
                },
                {
                    "guid": "plex://movie/predator-2",
                    "name": "Predator 2",
                    "year": 1990,
                    "score": 85
                }
            ]
        }
    }

    route = respx.get("http://plex.test/library/metadata/12345/matches").respond(
        status_code=200,
        json=mock_response
    )
    
    candidates = await plex.get_matches("12345")
    assert len(candidates) == 2
    assert candidates[0]["name"] == "Predator"
    assert candidates[0]["guid"] == "plex://movie/predator"
    assert candidates[0]["year"] == 1987
    assert candidates[0]["score"] == 99
    assert route.called


@pytest.mark.asyncio
@respx.mock
async def test_match_item_success():
    plex = PlexClient()
    plex.url = "http://plex.test"
    plex.token = "fake_token"

    route = respx.put(
        "http://plex.test/library/metadata/12345/match?guid=plex%3A%2F%2Fmovie%2Fpredator&name=Predator"
    ).respond(status_code=200)
    
    res = await plex.match_item("12345", "plex://movie/predator", "Predator")
    assert res is True
    assert route.called
