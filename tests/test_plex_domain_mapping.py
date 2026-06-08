import pytest
import respx
import httpx
from moviebot.adapters.plex_client import PlexClient
from moviebot.config import settings

@pytest.mark.asyncio
async def test_get_section_domain_default_inference():
    plex = PlexClient()
    
    # Standard movie and show types
    assert plex.get_section_domain({"title": "My Movies", "key": "1", "type": "movie"}) == "movies"
    assert plex.get_section_domain({"title": "My TV", "key": "2", "type": "show"}) == "tv"
    
    # Unknown type
    assert plex.get_section_domain({"title": "Photos", "key": "3", "type": "photo"}) is None


@pytest.mark.asyncio
async def test_get_section_domain_explicit_mapping(monkeypatch):
    monkeypatch.setattr(settings, "plex_domain_mapping", "3:anime, My TV Classic:tv_classic, 4:invalid_domain")
    plex = PlexClient()
    
    # Mapped by key
    assert plex.get_section_domain({"title": "Random Title", "key": "3", "type": "movie"}) == "anime"
    
    # Mapped by title (case insensitive)
    assert plex.get_section_domain({"title": "my tv classic", "key": "5", "type": "show"}) == "tv_classic"
    
    # Mapped to invalid domain
    assert plex.get_section_domain({"title": "Some Title", "key": "4", "type": "movie"}) is None


@pytest.mark.asyncio
async def test_get_section_domain_ignored_precedence(monkeypatch):
    monkeypatch.setattr(settings, "ignored_plex_sections", "IgnoredSection, 2")
    monkeypatch.setattr(settings, "plex_domain_mapping", "2:anime, IgnoredSection:movies")
    plex = PlexClient()
    
    # Ignored by key, even if mapped to anime
    assert plex.get_section_domain({"title": "Anime Section", "key": "2", "type": "movie"}) is None
    
    # Ignored by title, even if mapped to movies
    assert plex.get_section_domain({"title": "ignoredsection", "key": "3", "type": "movie"}) is None
    
    # Standard non-ignored, not mapped
    assert plex.get_section_domain({"title": "Movies", "key": "1", "type": "movie"}) == "movies"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_all_movies_routes_only_movies(monkeypatch):
    monkeypatch.setattr(settings, "ignored_plex_sections", "99")
    monkeypatch.setattr(settings, "plex_domain_mapping", "2:anime, 3:movies, 4:tv")
    
    plex = PlexClient()
    plex.url = "http://plex.test"
    plex.token = "fake_token"
    
    sections_mock = {
        "MediaContainer": {
            "Directory": [
                {"title": "Movies 1", "key": "1", "type": "movie"},      # Inferred "movies"
                {"title": "Anime", "key": "2", "type": "movie"},         # Mapped "anime" -> skipped
                {"title": "Explicit Movies", "key": "3", "type": "show"}, # Mapped "movies" -> queried
                {"title": "TV Shows", "key": "4", "type": "show"},       # Mapped "tv" -> skipped
                {"title": "Ignored", "key": "99", "type": "movie"}       # Ignored -> skipped
            ]
        }
    }
    
    respx.get("http://plex.test/library/sections").respond(status_code=200, json=sections_mock)
    
    # We expect HTTP requests for key 1 and key 3, but NOT 2, 4, or 99
    route_sec1 = respx.get("http://plex.test/library/sections/1/all").respond(status_code=200, json={
        "MediaContainer": {"Metadata": [{"ratingKey": "101", "title": "Movie 101"}]}
    })
    route_sec3 = respx.get("http://plex.test/library/sections/3/all").respond(status_code=200, json={
        "MediaContainer": {"Metadata": [{"ratingKey": "301", "title": "Movie 301"}]}
    })
    
    movies = await plex.fetch_all_movies()
    
    assert len(movies) == 2
    assert movies[0]["title"] == "Movie 101"
    assert movies[1]["title"] == "Movie 301"
    
    assert route_sec1.called
    assert route_sec3.called
    
    # Verify that the others were not called
    assert not respx.get("http://plex.test/library/sections/2/all").called
    assert not respx.get("http://plex.test/library/sections/4/all").called
    assert not respx.get("http://plex.test/library/sections/99/all").called


@pytest.mark.asyncio
@respx.mock
async def test_search_movie_routes_only_movies(monkeypatch):
    monkeypatch.setattr(settings, "plex_domain_mapping", "2:anime")
    
    plex = PlexClient()
    plex.url = "http://plex.test"
    plex.token = "fake_token"
    
    sections_mock = {
        "MediaContainer": {
            "Directory": [
                {"title": "Movies 1", "key": "1", "type": "movie"},  # Inferred "movies"
                {"title": "Anime", "key": "2", "type": "movie"}      # Mapped "anime" -> skipped
            ]
        }
    }
    
    respx.get("http://plex.test/library/sections").respond(status_code=200, json=sections_mock)
    route_sec1 = respx.get("http://plex.test/library/sections/1/all?title=Matrix").respond(status_code=200, json={
        "MediaContainer": {"Metadata": [{"ratingKey": "101", "title": "The Matrix"}]}
    })
    
    results = await plex.search_movie("Matrix")
    assert len(results) == 1
    assert results[0]["title"] == "The Matrix"
    assert route_sec1.called
    assert not respx.get("http://plex.test/library/sections/2/all?title=Matrix").called


@pytest.mark.asyncio
@respx.mock
async def test_refresh_movie_sections_routes_only_movies(monkeypatch):
    monkeypatch.setattr(settings, "plex_domain_mapping", "2:anime")
    
    plex = PlexClient()
    plex.url = "http://plex.test"
    plex.token = "fake_token"
    
    sections_mock = {
        "MediaContainer": {
            "Directory": [
                {"title": "Movies 1", "key": "1", "type": "movie"},  # Inferred "movies"
                {"title": "Anime", "key": "2", "type": "movie"}      # Mapped "anime" -> skipped
            ]
        }
    }
    
    respx.get("http://plex.test/library/sections").respond(status_code=200, json=sections_mock)
    route_sec1 = respx.get("http://plex.test/library/sections/1/refresh").respond(status_code=200)
    
    await plex.refresh_movie_sections()
    assert route_sec1.called
    assert not respx.get("http://plex.test/library/sections/2/refresh").called


@pytest.mark.asyncio
@respx.mock
async def test_fetch_sections_preview(monkeypatch):
    monkeypatch.setattr(settings, "ignored_plex_sections", "99")
    monkeypatch.setattr(settings, "plex_domain_mapping", "2:anime")
    
    plex = PlexClient()
    plex.url = "http://plex.test"
    plex.token = "fake_token"
    
    sections_mock = {
        "MediaContainer": {
            "Directory": [
                {"title": "Movies", "key": "1", "type": "movie"},
                {"title": "Anime", "key": "2", "type": "movie"},
                {"title": "Ignored", "key": "99", "type": "movie"}
            ]
        }
    }
    
    respx.get("http://plex.test/library/sections").respond(status_code=200, json=sections_mock)
    
    # Mock items for non-ignored sections to get count
    respx.get("http://plex.test/library/sections/1/all").respond(status_code=200, json={
        "MediaContainer": {"Metadata": [{"ratingKey": "101"}, {"ratingKey": "102"}]}
    })
    respx.get("http://plex.test/library/sections/2/all").respond(status_code=200, json={
        "MediaContainer": {"Metadata": [{"ratingKey": "201"}]}
    })
    
    # For ignored/None domains, we don't count items, so key 99 will not be called
    
    preview = await plex.fetch_sections_preview()
    assert len(preview) == 3
    
    assert preview[0] == {
        "key": "1",
        "title": "Movies",
        "type": "movie",
        "domain": "movies",
        "ignored": False,
        "item_count": 2
    }
    assert preview[1] == {
        "key": "2",
        "title": "Anime",
        "type": "movie",
        "domain": "anime",
        "ignored": False,
        "item_count": 1
    }
    assert preview[2] == {
        "key": "99",
        "title": "Ignored",
        "type": "movie",
        "domain": None,
        "ignored": True,
        "item_count": 0
    }
