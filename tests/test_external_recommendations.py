import json
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest

from moviebot.config import settings
from moviebot.core.external_recommendations import (
    filter_external_recommendations,
    is_media_domain_question,
    parse_external_recommendations,
    sanitize_external_title,
)
from moviebot.db.connection import init_db
from moviebot.db.repositories import UserProfileRepository


@pytest.fixture
def temp_db(monkeypatch):
    db_dir = Path("scratch") / "external-recommendation-tests"
    db_dir.mkdir(parents=True, exist_ok=True)
    db_file = db_dir / f"test_moviebot_{uuid.uuid4().hex}.sqlite3"
    monkeypatch.setattr(settings, "database_path", str(db_file))
    init_db()
    return db_file


def test_parse_and_sanitize_external_recommendations():
    answer = (
        "Try [External Recommendation: Predator: Badlands (2025)] and "
        "[External Recommendation: Wall-E (2008)]."
    )

    recs = parse_external_recommendations(answer)

    assert recs == [
        {"title": "Predator: Badlands", "year": 2025, "sanitized_query": "Predator Badlands"},
        {"title": "Wall-E", "year": 2008, "sanitized_query": "Wall E"},
    ]
    assert sanitize_external_title("Alien; rm -rf / 1979!!") == "Alien rm rf 1979"


def test_non_media_domain_lock():
    assert is_media_domain_question("What movie should I add next?") is True
    assert is_media_domain_question("What is the weather tomorrow?") is False


def test_external_content_gate_filters_profile_rating_and_genres(temp_db):
    UserProfileRepository.upsert(
        discord_user_id="123",
        metadata_json=json.dumps({"max_content_rating": "PG-13", "excluded_genres": ["Horror"]}),
    )
    provider = MagicMock()
    provider.get_facts.side_effect = [
        {"tmdb_id": 1, "content_rating": "R", "genres": ["Action"]},
        {"tmdb_id": 2, "content_rating": "PG", "genres": ["Horror"]},
        {"tmdb_id": 3, "content_rating": "PG", "genres": ["Adventure"]},
    ]

    allowed = filter_external_recommendations(
        [
            {"title": "Too Mature", "year": 2024, "sanitized_query": "Too Mature"},
            {"title": "Wrong Genre", "year": 2023, "sanitized_query": "Wrong Genre"},
            {"title": "Safe Pick", "year": 2022, "sanitized_query": "Safe Pick"},
        ],
        discord_user_id="123",
        tmdb_provider=provider,
    )

    assert [rec.title for rec in allowed] == ["Safe Pick"]
    assert allowed[0].content_rating == "PG"


@pytest.mark.asyncio
async def test_external_search_add_button_requires_confirmation():
    from moviebot.bot.discord_app import ExternalSearchAddButton, ExternalSearchConfirmView

    button = ExternalSearchAddButton(title="Alien; drop table", year=1979)
    assert button.title == "Alien drop table"
    assert button.label == "Search & Add: Alien drop table (1979)"

    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = 42
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("moviebot.bot.discord_app.search_sources_tool", new_callable=AsyncMock) as mock_search:
        await button.callback(interaction)

    mock_search.assert_not_called()
    interaction.response.send_message.assert_awaited_once()
    _, kwargs = interaction.response.send_message.call_args
    assert kwargs["ephemeral"] is True
    assert isinstance(kwargs["view"], ExternalSearchConfirmView)


@pytest.mark.asyncio
async def test_external_confirm_triggers_sanitized_search():
    from moviebot.bot.discord_app import ExternalSearchConfirmView

    view = ExternalSearchConfirmView(title="Alien; drop table", year=1979, original_user_id=42)
    interaction = MagicMock(spec=discord.Interaction)
    interaction.user = MagicMock()
    interaction.user.id = 42
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    mock_search_res = {
        "ok": True,
        "data": {
            "results": [
                {
                    "reference_id": "ref_1",
                    "title": "Alien 1979 1080p",
                    "size_bytes": 4_000_000_000,
                    "seeders": 10,
                    "indexer": "UnitTest",
                }
            ]
        },
    }

    with patch("moviebot.bot.discord_app.LibraryItemRepository.search_by_normalized_title", return_value=[]), \
         patch("moviebot.bot.discord_app.search_sources_tool", new_callable=AsyncMock, return_value=mock_search_res) as mock_search:
        await view.confirm.callback(interaction)

    interaction.response.defer.assert_awaited_once_with(ephemeral=True)
    mock_search.assert_awaited_once_with(query="Alien drop table 1979")
    interaction.followup.send.assert_awaited_once()
    _, kwargs = interaction.followup.send.call_args
    assert kwargs["ephemeral"] is False
    assert "embed" in kwargs
    assert "Alien 1979 1080p" in kwargs["embed"].description


@pytest.mark.asyncio
async def test_slash_ask_adds_external_recommendation_view(temp_db):
    from moviebot.bot.discord_app import ExternalSearchAddButton, slash_ask

    interaction = MagicMock(spec=discord.Interaction)
    interaction.guild = None
    interaction.user = MagicMock()
    interaction.user.id = 42
    interaction.user.display_name = "Tester"
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock(return_value=AsyncMock())

    mock_res = {
        "ok": True,
        "data": {
            "answer": "Add [External Recommendation: Alien (1979)].",
            "cited_movie_ids": [],
            "external_recommendations": [
                {"title": "Alien", "year": 1979, "sanitized_query": "Alien", "content_rating": "R"}
            ],
        },
    }

    with patch("moviebot.bot.discord_app.ask_library_tool", new_callable=AsyncMock, return_value=mock_res):
        await slash_ask.callback(interaction, question="What should I add next?")

    _, kwargs = interaction.followup.send.call_args
    assert "view" in kwargs
    assert isinstance(kwargs["view"].children[0], ExternalSearchAddButton)
