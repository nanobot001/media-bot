import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from moviebot.db.repositories import BotSettingsRepository, UserInteractionMemoryRepository
from moviebot.tools.get_bot_persona_tool import get_bot_persona_tool
from moviebot.tools.set_bot_persona_tool import set_bot_persona_tool
from moviebot.tools.ask_library_tool import ask_library_tool
from moviebot.core.conversational_rag import query_library_conversational
import discord
from moviebot.bot.discord_app import persona_show, persona_set, persona_reset
import sqlite3
import struct

@pytest.fixture
def mock_db(tmp_path):
    """Sets up a temporary SQLite database for testing settings and memory."""
    db_file = tmp_path / "test_moviebot_settings.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


def test_bot_settings_repository(mock_db):
    # Test setting, getting, and resetting persona in BotSettingsRepository
    assert BotSettingsRepository.get("rag_persona") is None

    BotSettingsRepository.set("rag_persona", "Always talk like a pirate.")
    assert BotSettingsRepository.get("rag_persona") == "Always talk like a pirate."

    BotSettingsRepository.delete("rag_persona")
    assert BotSettingsRepository.get("rag_persona") is None


@pytest.mark.asyncio
async def test_get_and_set_bot_persona_tools(mock_db):
    # Test get_bot_persona_tool initially (should be system default, is_override=False)
    with patch("moviebot.config.settings.rag_persona", "Default default"):
        res = await get_bot_persona_tool()
        assert res["ok"] is True
        assert res["data"]["active_persona"] == "Default default"
        assert res["data"]["is_override"] is False

        # Set new persona override
        res_set = await set_bot_persona_tool(persona="Sarcastic AI")
        assert res_set["ok"] is True
        assert res_set["data"]["action"] == "set"
        assert res_set["data"]["updated_persona"] == "Sarcastic AI"

        # Check get_bot_persona_tool again (should be override, is_override=True)
        res_get2 = await get_bot_persona_tool()
        assert res_get2["ok"] is True
        assert res_get2["data"]["active_persona"] == "Sarcastic AI"
        assert res_get2["data"]["is_override"] is True

        # Reset persona
        res_reset = await set_bot_persona_tool(reset=True)
        assert res_reset["ok"] is True
        assert res_reset["data"]["action"] == "reset"
        assert res_reset["data"]["updated_persona"] == "Default default"

        # Check get again
        res_get3 = await get_bot_persona_tool()
        assert res_get3["data"]["active_persona"] == "Default default"
        assert res_get3["data"]["is_override"] is False


@pytest.mark.asyncio
@patch("moviebot.core.conversational_rag.generate_gemini_content")
@patch("moviebot.core.conversational_rag.get_embedding_result")
@patch("moviebot.core.conversational_rag.get_db_connection")
async def test_rag_persona_override(mock_db_conn, mock_embed, mock_generate, mock_db):
    # Set custom persona in db
    BotSettingsRepository.set("rag_persona", "Custom Persona Inst")

    # Mock RAG dependencies
    mock_emb_res = MagicMock()
    mock_emb_res.vector = [0.1] * 768
    mock_emb_res.model = "mock-hash-v1"
    mock_emb_res.dim = 768
    mock_embed.return_value = mock_emb_res

    # Mock DB connection row / data with full schema
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE library_items (
            id TEXT PRIMARY KEY,
            title TEXT,
            year INTEGER,
            genres TEXT,
            tagline TEXT,
            synopsis TEXT,
            tone_tags TEXT,
            theme_tags TEXT,
            award_tags TEXT,
            studios TEXT,
            directors TEXT,
            synopsis_vector BLOB,
            synopsis_vector_model TEXT,
            synopsis_vector_dim INTEGER
        )
    """)
    mock_vector = [0.1] * 768
    vec_bytes = struct.pack("f" * 768, *mock_vector)
    conn.execute("""
        INSERT INTO library_items (
            id, title, year, genres, tagline, synopsis,
            tone_tags, theme_tags, award_tags, studios, directors,
            synopsis_vector, synopsis_vector_model, synopsis_vector_dim
        ) VALUES (
            'plex_1', 'The Matrix', 1999, '["Action"]', 'Welcome', 'Neo discovers reality',
            '["Dark"]', '["Cyberpunk"]', '[]', 'WB', '["Wachowskis"]',
            ?, 'mock-hash-v1', 768
        )
    """, (vec_bytes,))
    conn.commit()

    mock_context = MagicMock()
    mock_context.__enter__.return_value = conn
    mock_context.__exit__.return_value = False
    mock_db_conn.return_value = mock_context

    mock_generate.return_value = "Custom response"

    # Call query_library_conversational
    res = await query_library_conversational("Show me sci-fi movies")
    assert res["answer"] == "Custom response"

    # Verify that mock_generate was called, and the custom persona was passed as system instruction
    mock_generate.assert_called_once()
    _, kwargs = mock_generate.call_args
    assert "system_instruction" in kwargs
    assert kwargs["system_instruction"] == "Custom Persona Inst"


@pytest.mark.asyncio
@patch("moviebot.tools.ask_library_tool.query_library_conversational")
async def test_ask_library_history_injection(mock_query, mock_db):
    # Enable history logging by inserting history into UserInteractionMemoryRepository
    # First we need user profile to satisfy foreign key constraints
    from moviebot.db.connection import get_db_connection
    with get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profiles (discord_user_id, plex_username) VALUES ('test_user_id', 'test_plex_user')")
        conn.commit()

    # Log interaction
    UserInteractionMemoryRepository.log("test_user_id", "what movies do you have?", "I have Matrix.")
    UserInteractionMemoryRepository.log("test_user_id", "what about Sci-fi?", "I recommend Interstellar.")

    # Mock successful query
    mock_query.return_value = {
        "answer": "Interstellar has a runtime of 169m.",
        "cited_movie_ids": []
    }

    # Call ask_library_tool
    res = await ask_library_tool(question="What is its runtime?", discord_user_id="test_user_id")
    assert res["ok"] is True

    # Check that query_library_conversational was called with history
    mock_query.assert_called_once()
    _, kwargs = mock_query.call_args
    assert "chat_history" in kwargs
    assert kwargs["chat_history"] == [
        {"role": "user", "text": "what movies do you have?"},
        {"role": "model", "text": "I have Matrix."},
        {"role": "user", "text": "what about Sci-fi?"},
        {"role": "model", "text": "I recommend Interstellar."}
    ]


@pytest.mark.asyncio
async def test_discord_persona_commands(mock_db):
    # Mock discord Interaction
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    # 1. Test persona_show initially (should display default)
    with patch("moviebot.config.settings.rag_persona", "Default default"):
        await persona_show.callback(interaction)
        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]
        assert "System Default" in embed.fields[0].value
        assert "Default default" in embed.fields[1].value

    interaction.response.send_message.reset_mock()

    # 2. Test persona_set
    await persona_set.callback(interaction, persona_text="Pirate persona")
    interaction.response.send_message.assert_called_once()
    _, kwargs = interaction.response.send_message.call_args
    embed = kwargs["embed"]
    assert "Pirate persona" in embed.fields[0].value
    assert BotSettingsRepository.get("rag_persona") == "Pirate persona"

    interaction.response.send_message.reset_mock()

    # 3. Test persona_show after override
    with patch("moviebot.config.settings.rag_persona", "Default default"):
        await persona_show.callback(interaction)
        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]
        assert "Database Override" in embed.fields[0].value
        assert "Pirate persona" in embed.fields[1].value

    interaction.response.send_message.reset_mock()

    # 4. Test persona_reset
    with patch("moviebot.config.settings.rag_persona", "Default default"):
        await persona_reset.callback(interaction)
        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        embed = kwargs["embed"]
        assert "Default default" in embed.fields[0].value
        assert BotSettingsRepository.get("rag_persona") is None


def test_user_interaction_memory_pruning(mock_db):
    # Setup test profile
    from moviebot.db.connection import get_db_connection
    with get_db_connection() as conn:
        conn.execute("INSERT OR REPLACE INTO user_profiles (discord_user_id, plex_username) VALUES ('prune_user', 'prune_plex')")
        conn.commit()

    # Log 12 messages
    for i in range(12):
        UserInteractionMemoryRepository.log("prune_user", f"query {i}", f"response {i}")

    # Verify all 12 exist
    recent = UserInteractionMemoryRepository.get_recent("prune_user", limit=100)
    assert len(recent) == 12

    # Prune oldest with limit 5
    UserInteractionMemoryRepository.prune_oldest("prune_user", max_limit=5)

    # Verify only 5 remaining (the most recent ones: 7, 8, 9, 10, 11)
    remaining = UserInteractionMemoryRepository.get_recent("prune_user", limit=100)
    assert len(remaining) == 5
    assert remaining[0]["query_text"] == "query 7"
    assert remaining[-1]["query_text"] == "query 11"

