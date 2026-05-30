import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import discord
from discord import app_commands
from moviebot.config import settings
from moviebot.bot.discord_app import bot, channel_check_predicate, on_app_command_error, slash_events, slash_logs, slash_help
from moviebot.db.repositories import ErrorLogRepository


@pytest.fixture
def mock_db(tmp_path):
    """Sets up a temporary SQLite database for testing."""
    db_file = tmp_path / "test_moviebot.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


@pytest.mark.asyncio
async def test_in_allowed_channel_success():
    with patch("moviebot.config.settings.allowed_discord_channels", "123,456"):
        # Mock interaction
        interaction = MagicMock(spec=discord.Interaction)
        interaction.channel_id = 123
        
        res = await channel_check_predicate(interaction)
        assert res is True


@pytest.mark.asyncio
async def test_in_allowed_channel_fail():
    with patch("moviebot.config.settings.allowed_discord_channels", "123,456"):
        # Mock interaction
        interaction = MagicMock(spec=discord.Interaction)
        interaction.channel_id = 999
        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.response.send_message = AsyncMock()
        
        res = await channel_check_predicate(interaction)
        assert res is False
        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        assert "embed" in kwargs
        assert kwargs["embed"].title == "🚫 Access Restricted"


@pytest.mark.asyncio
async def test_in_allowed_channel_empty():
    with patch("moviebot.config.settings.allowed_discord_channels", ""):
        interaction = MagicMock(spec=discord.Interaction)
        interaction.channel_id = 999
        
        res = await channel_check_predicate(interaction)
        assert res is True


@pytest.mark.asyncio
async def test_on_app_command_error(mock_db):
    with patch("moviebot.config.settings.discord_error_channel_id", 777):
        # Mock interaction
        interaction = MagicMock(spec=discord.Interaction)
        interaction.command = MagicMock()
        interaction.command.name = "search"
        interaction.user = MagicMock()
        interaction.user.id = 111
        interaction.user.name = "john_doe"
        interaction.channel_id = 123
        
        # User response mocks
        interaction.response = MagicMock()
        interaction.response.is_done = MagicMock(return_value=False)
        interaction.response.send_message = AsyncMock()
        
        # Mock channel for admin alerts
        mock_channel = MagicMock()
        mock_channel.send = AsyncMock()
        
        bot.get_channel = MagicMock(return_value=mock_channel)
        
        # Trigger error handler
        test_error = ValueError("Something went wrong with Prowlarr")
        wrapped_error = app_commands.CommandInvokeError(interaction.command, test_error)
        
        await on_app_command_error(interaction, wrapped_error)
        
        # Verify db log
        logs = ErrorLogRepository.get_all()
        assert len(logs) == 1
        assert logs[0]["command_name"] == "search"
        assert logs[0]["user_id"] == "111"
        assert logs[0]["user_name"] == "john_doe"
        assert logs[0]["error_message"] == "Something went wrong with Prowlarr"
        assert "ValueError" in logs[0]["stack_trace"]
        
        # Verify user was notified
        interaction.response.send_message.assert_called_once()
        _, kwargs = interaction.response.send_message.call_args
        assert "embed" in kwargs
        assert kwargs["embed"].title == "❌ Execution Error"
        
        # Verify admin channel was notified
        mock_channel.send.assert_called_once()
        _, admin_kwargs = mock_channel.send.call_args
        assert "embed" in admin_kwargs
        assert admin_kwargs["embed"].title == "⚠️ Command Runtime Exception Logged"
        assert "Something went wrong with Prowlarr" in admin_kwargs["embed"].fields[0].value


def test_error_log_pruning(mock_db):
    # Insert 6 errors
    for i in range(6):
        ErrorLogRepository.insert(
            command_name=f"cmd_{i}",
            user_id="123",
            user_name="user",
            error_message=f"error {i}",
            stack_trace="trace"
        )
    
    # Prune keeping 3
    ErrorLogRepository.prune(max_errors=3)
    
    # Verify only 3 remain (the latest ones)
    logs = ErrorLogRepository.get_all()
    assert len(logs) == 3
    cmd_names = [log["command_name"] for log in logs]
    assert "cmd_5" in cmd_names
    assert "cmd_4" in cmd_names
    assert "cmd_3" in cmd_names
    assert "cmd_0" not in cmd_names


@pytest.mark.asyncio
async def test_slash_events(mock_db):
    from moviebot.db.repositories import EventRepository
    EventRepository.insert(
        event_type="test_event",
        source="unit_test",
        title="Test Title",
        summary="A test event occurred",
        severity="info"
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await slash_events.callback(interaction, limit=5)

    interaction.response.defer.assert_called_once_with(ephemeral=True)
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert embed.title == "🔔 Recent System Events"
    assert "TEST_EVENT" in embed.fields[0].name
    assert "Test Title" in embed.fields[0].value


@pytest.mark.asyncio
async def test_slash_logs(tmp_path):
    log_file = tmp_path / "media-watcher.log"
    lines = [f"Log line {i}" for i in range(150)]
    with open(log_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    import os
    with patch("os.path.exists", return_value=True), \
         patch("os.path.getsize", return_value=os.path.getsize(log_file)), \
         patch("builtins.open", MagicMock(return_value=open(log_file, "r", encoding="utf-8-sig"))):
        
        await slash_logs.callback(interaction, source="watcher", lines=20)


    interaction.response.defer.assert_called_once_with(ephemeral=True)
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "content" in kwargs
    assert "Last 20 lines from `watcher` log" in kwargs["content"]
    assert "Log line 130" in kwargs["content"]
    assert "Log line 149" in kwargs["content"]


@pytest.mark.asyncio
async def test_slash_help_for_manager():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("moviebot.bot.discord_app.is_bot_manager", return_value=True):
        await slash_help.callback(interaction)

    interaction.response.send_message.assert_called_once()
    _, kwargs = interaction.response.send_message.call_args
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert embed.title == "🎬 MovieBot Help & Command Reference"
    field_names = [field.name for field in embed.fields]
    assert "🔧 Bot Manager Commands" in field_names
    assert "👥 User Commands" in field_names


@pytest.mark.asyncio
async def test_slash_help_for_regular_user():
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.send_message = AsyncMock()

    with patch("moviebot.bot.discord_app.is_bot_manager", return_value=False):
        await slash_help.callback(interaction)

    interaction.response.send_message.assert_called_once()
    _, kwargs = interaction.response.send_message.call_args
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert embed.title == "🎬 MovieBot Help & Command Reference"
    field_names = [field.name for field in embed.fields]
    assert "🔧 Bot Manager Commands" not in field_names
    assert "👥 User Commands" in field_names
    assert "Administrative / diagnostic commands are hidden" in embed.footer.text

