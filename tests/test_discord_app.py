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
async def test_pipeline_in_plex_posts_auto_enrichment_card_once(mock_db):
    from moviebot.bot.discord_app import post_auto_enrichment_card_for_status
    from moviebot.core.pipeline_status import PipelineStatus, PipelineStage
    from moviebot.core.dedupe import normalize_title
    from moviebot.db.repositories import EventRepository, KeyValueRepository, LibraryItemRepository

    LibraryItemRepository.upsert(
        id="plex_123",
        source="plex",
        rating_key="123",
        title="Inception",
        normalized_title=normalize_title("Inception"),
        year=2010,
        imdb_id="tt1375666",
        file_path="/movies/Inception.mkv",
        size_bytes=1234,
        genres='["Sci-Fi"]',
        studios='["Legendary"]',
        content_rating="PG-13",
        rating=8.8,
        runtime=148,
    )

    status = PipelineStatus(
        job_id="job_123",
        stage=PipelineStage.IN_PLEX,
        status_text="Successfully imported and matched in Plex Library.",
        title="Inception",
        year=2010,
        file_name="Inception.2010.mkv",
    )
    channel = MagicMock()
    channel.send = AsyncMock()
    embed = discord.Embed(title="New Movie Added")

    enrichment = {
        "theme_tags": ["dreams"],
        "tone_tags": ["tense"],
        "premise_tags": ["heist"],
        "setting_locations": [],
        "enrichment_json": {"source": "gemini"},
        "hard_fact_sources_json": {"source": "rules"},
    }

    with patch("moviebot.config.settings.allowed_discord_channels", "456"), \
         patch("moviebot.bot.discord_app.bot.get_channel", return_value=channel), \
         patch("moviebot.core.auto_enrich.auto_enrich_item", new_callable=AsyncMock) as mock_enrich, \
         patch("moviebot.core.auto_enrich.build_new_movie_embed", return_value=embed):
        mock_enrich.return_value = enrichment

        posted = await post_auto_enrichment_card_for_status(status)

    assert posted is True
    channel.send.assert_awaited_once_with(embed=embed)
    assert KeyValueRepository.get("auto_enrichment_posted:plex_123") == "pipeline"
    assert KeyValueRepository.get("pipeline_auto_enrichment_posted:job_123") == "posted"
    events = EventRepository.get_all()
    assert events[0]["event_type"] == "auto_enrichment"
    assert events[0]["source"] == "pipeline"


@pytest.mark.asyncio
async def test_pipeline_auto_enrichment_skips_item_already_posted(mock_db):
    from moviebot.bot.discord_app import post_auto_enrichment_card_for_status
    from moviebot.core.pipeline_status import PipelineStatus, PipelineStage
    from moviebot.core.dedupe import normalize_title
    from moviebot.db.repositories import KeyValueRepository, LibraryItemRepository

    LibraryItemRepository.upsert(
        id="plex_456",
        source="plex",
        rating_key="456",
        title="Aliens",
        normalized_title=normalize_title("Aliens"),
        year=1986,
        imdb_id="tt0090605",
        file_path="/movies/Aliens.mkv",
        size_bytes=5678,
    )
    KeyValueRepository.set("auto_enrichment_posted:plex_456", "webhook")

    status = PipelineStatus(
        job_id="job_456",
        stage=PipelineStage.IN_PLEX,
        status_text="Successfully imported and matched in Plex Library.",
        title="Aliens",
        year=1986,
        file_name="Aliens.1986.mkv",
    )

    with patch("moviebot.core.auto_enrich.auto_enrich_item", new_callable=AsyncMock) as mock_enrich:
        posted = await post_auto_enrichment_card_for_status(status)

    assert posted is False
    mock_enrich.assert_not_called()
    assert KeyValueRepository.get("pipeline_auto_enrichment_posted:job_456") == "skipped:item_already_posted"


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
    field_values = "\n".join(field.value for field in embed.fields)
    assert "Library & Enrichment" in field_names
    assert "/movie <title> [year]" in field_values
    assert "download reaches Plex" in field_values
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
    field_values = "\n".join(field.value for field in embed.fields)
    assert "Library & Enrichment" in field_names
    assert "/movie <title> [year]" in field_values
    assert "🔧 Bot Manager Commands" not in field_names
    assert "👥 User Commands" in field_names
    assert "Administrative / diagnostic commands are hidden" in embed.footer.text


@pytest.mark.asyncio
async def test_slash_status_no_jobs(mock_db):
    from moviebot.bot.discord_app import slash_status
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await slash_status.callback(interaction, title=None)

    interaction.response.defer.assert_called_once_with(ephemeral=False)
    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    content = args[0] if args else kwargs.get("content", "")
    assert "No recent download jobs found" in content


@pytest.mark.asyncio
async def test_slash_status_with_recent_jobs(mock_db):
    from moviebot.bot.discord_app import slash_status
    from moviebot.db.repositories import DownloadJobRepository
    
    # Insert a dummy job using create_job positionally: id, alldebrid_magnet_id, selected_file_name, target_dir, status
    DownloadJobRepository.create_job(
        "job_id_123",
        "magnet_link_123",
        "Inception.2010.mkv",
        "/target",
        "downloading"
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await slash_status.callback(interaction, title=None)

    interaction.response.defer.assert_called_once_with(ephemeral=False)
    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    content = args[0] if args else kwargs.get("content", "")
    assert "Select a job" in content
    assert "view" in kwargs


@pytest.mark.asyncio
async def test_slash_status_search_single_match(mock_db):
    from moviebot.bot.discord_app import slash_status
    from moviebot.db.repositories import DownloadJobRepository
    from moviebot.core.pipeline_status import PipelineStatus
    
    DownloadJobRepository.create_job(
        "job_id_123",
        "magnet_link_123",
        "Inception.2010.mkv",
        "/target",
        "downloading"
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    mock_status = PipelineStatus(
        job_id="job_id_123",
        stage="downloading",
        status_text="Downloading via IDM",
        progress=50.0,
        file_name="Inception.2010.mkv",
        title="Inception.2010.mkv"
    )

    with patch("moviebot.core.pipeline_status.PipelineStatusService.get_status", return_value=mock_status):
        await slash_status.callback(interaction, title="Inception")

    interaction.response.defer.assert_called_once_with(ephemeral=False)
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "embed" in kwargs
    assert "Inception.2010.mkv" in kwargs["embed"].title
    assert "view" in kwargs


@pytest.mark.asyncio
async def test_slash_status_search_multiple_matches(mock_db):
    from moviebot.bot.discord_app import slash_status
    from moviebot.db.repositories import DownloadJobRepository
    
    DownloadJobRepository.create_job(
        "job_id_1",
        "magnet_link_1",
        "Inception.2010.mkv",
        "/target",
        "downloading"
    )
    DownloadJobRepository.create_job(
        "job_id_2",
        "magnet_link_2",
        "Inception.2010.1080p.mkv",
        "/target",
        "completed"
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await slash_status.callback(interaction, title="Inception")

    interaction.response.defer.assert_called_once_with(ephemeral=False)
    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    content = args[0] if args else kwargs.get("content", "")
    assert "Multiple jobs matched" in content
    assert "view" in kwargs


@pytest.mark.asyncio
async def test_slash_status_search_no_match(mock_db):
    from moviebot.bot.discord_app import slash_status
    
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await slash_status.callback(interaction, title="Interstellar")

    interaction.response.defer.assert_called_once_with(ephemeral=False)
    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    content = args[0] if args else kwargs.get("content", "")
    assert "No jobs found matching" in content


@pytest.mark.asyncio
async def test_status_dropdown_callback(mock_db):
    from moviebot.bot.discord_app import StatusDropdown
    from moviebot.core.pipeline_status import PipelineStatus
    
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.edit_original_response = AsyncMock()
    
    dropdown = StatusDropdown(options=[discord.SelectOption(label="Test", value="job_id_123")])
    
    mock_status = PipelineStatus(
        job_id="job_id_123",
        stage="downloading",
        status_text="Downloading via IDM",
        progress=50.0,
        file_name="Inception.2010.mkv",
        title="Inception.2010.mkv"
    )

    from unittest.mock import PropertyMock
    with patch("moviebot.bot.discord_app.StatusDropdown.values", new_callable=PropertyMock, return_value=["job_id_123"]), \
         patch("moviebot.core.pipeline_status.PipelineStatusService.get_status", return_value=mock_status):
        await dropdown.callback(interaction)
        
    interaction.response.defer.assert_called_once()
    interaction.edit_original_response.assert_called_once()
    _, kwargs = interaction.edit_original_response.call_args
    assert "embed" in kwargs
    assert "Inception.2010.mkv" in kwargs["embed"].title
    assert "view" in kwargs


@pytest.mark.asyncio
async def test_slash_library_success():
    from moviebot.bot.discord_app import slash_library
    
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    
    mock_res = {
        "ok": True,
        "timestamp": "2026-05-31T00:00:00Z",
        "tool": "query_library",
        "data": {
            "movies": [
                {
                    "id": 1,
                    "title": "The Matrix",
                    "year": 1999,
                    "resolution": "1080p",
                    "rating": 8.7,
                    "runtime": 136,
                    "watch_status": "unwatched",
                    "similarity_score": 0.95
                }
            ]
        }
    }
    
    with patch("moviebot.bot.discord_app.query_library_tool", return_value=mock_res):
        await slash_library.callback(
            interaction,
            query="Matrix",
            semantic_query=None,
            genre=None,
            director=None,
            resolution=None,
            watch_status=None,
            max_runtime=None,
            min_rating=None,
            limit=10
        )
        
    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert embed.title == "🎬 Library Search Results"
    assert "The Matrix" in embed.description
    assert "95.0% Match" in embed.description
    assert "1080p" in embed.description


def test_build_movie_detail_embed_includes_synopsis():
    from moviebot.bot.discord_app import build_movie_detail_embed

    embed = build_movie_detail_embed({
        "id": "plex_1",
        "rating_key": "1",
        "imdb_id": "tt0133093",
        "title": "The Matrix",
        "year": 1999,
        "synopsis": "A hacker discovers the world is a simulated reality.",
        "genres": '["Action", "Science Fiction"]',
        "directors": '["Lana Wachowski", "Lilly Wachowski"]',
        "cast": '["Keanu Reeves", "Carrie-Anne Moss"]',
        "rating": 8.7,
        "runtime": 136,
        "resolution": "1080",
        "size_bytes": 1024 * 1024 * 1024,
        "brand_tags": '["Warner Bros."]',
        "franchise_tags": '["The Matrix"]',
        "universe_tags": '["The Matrix Universe"]',
        "theme_tags": '["identity"]',
        "tone_tags": '["tense"]',
        "award_tags": '["oscar_winner"]',
        "popularity_tags": '["classic"]',
        "enrichment_model": "moviebot-rule-enricher-v1",
    })

    assert embed.title == "Movie: The Matrix (1999)"
    assert "simulated reality" in embed.description
    field_names = [field.name for field in embed.fields]
    assert "Enrichment" in field_names
    
    enrichment_field = [f for f in embed.fields if f.name == "Enrichment"][0]
    assert "Brand: `Warner Bros.`" in enrichment_field.value
    assert "Franchise: `The Matrix`" in enrichment_field.value
    assert "Universe: `The Matrix Universe`" in enrichment_field.value
    
    assert "Hard Facts" in field_names
    assert "IMDb: tt0133093" in embed.footer.text


@pytest.mark.asyncio
async def test_slash_movie_success(mock_db):
    from moviebot.bot.discord_app import slash_movie
    from moviebot.core.dedupe import normalize_title
    from moviebot.db.repositories import LibraryItemRepository

    LibraryItemRepository.upsert(
        id="plex_matrix",
        source="plex",
        rating_key="42",
        title="The Matrix",
        normalized_title=normalize_title("The Matrix"),
        year=1999,
        imdb_id="tt0133093",
        file_path="/movies/The Matrix.mkv",
        size_bytes=1234,
        synopsis="A hacker discovers the world is a simulated reality.",
        genres='["Action"]',
    )

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await slash_movie.callback(interaction, title="Matrix", year=1999)

    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "embed" in kwargs
    assert kwargs["embed"].title == "Movie: The Matrix (1999)"
    assert "simulated reality" in kwargs["embed"].description


@pytest.mark.asyncio
async def test_slash_movie_no_match(mock_db):
    from moviebot.bot.discord_app import slash_movie

    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()

    await slash_movie.callback(interaction, title="Not A Real Movie", year=None)

    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()
    args, kwargs = interaction.followup.send.call_args
    content = args[0] if args else kwargs.get("content", "")
    assert "No movie found" in content


@pytest.mark.asyncio
async def test_slash_recommend_success():
    from moviebot.bot.discord_app import slash_recommend
    
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    
    mock_res = {
        "ok": True,
        "timestamp": "2026-05-31T00:00:00Z",
        "tool": "recommend_movies",
        "data": {
            "recommendations": [
                {
                    "title": "Inception",
                    "year": 2010,
                    "score": 8.5,
                    "cosine_similarity": 0.8,
                    "genre_score": 0.9,
                    "director_score": 0.7
                }
            ]
        }
    }
    
    with patch("moviebot.bot.discord_app.recommend_movies_tool", return_value=mock_res):
        await slash_recommend.callback(interaction, user="anthony", limit=5)
        
    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert embed.title == "🍿 Recommendations for anthony"
    assert "Inception" in embed.description
    assert "Score: `8.50`" in embed.description


@pytest.mark.asyncio
async def test_slash_audit_success(mock_db):
    from moviebot.bot.discord_app import slash_audit
    
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    
    mock_res = {
        "ok": True,
        "timestamp": "2026-05-31T00:00:00Z",
        "tool": "audit_collections",
        "data": {
            "reports": [
                {
                    "collection": "Toy Story Collection",
                    "owned": [{"title": "Toy Story", "year": 1995, "index": 1}],
                    "missing": [{"title": "Toy Story 2", "year": 1999, "index": 2}]
                }
            ]
        }
    }
    
    with patch("moviebot.bot.discord_app.audit_collections_tool", return_value=mock_res):
        await slash_audit.callback(interaction)
        
    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "embed" in kwargs
    assert "view" in kwargs
    embed = kwargs["embed"]
    assert embed.title == "📋 Collection Gap Audit Results"
    assert "Toy Story Collection" in embed.fields[0].name
    assert "Toy Story 2" in embed.fields[0].value


@pytest.mark.asyncio
async def test_search_missing_button_callback(mock_db):
    from moviebot.bot.discord_app import SearchMissingButton
    
    button = SearchMissingButton(label="Search: Toy Story 2", movie_title="Toy Story 2")
    
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    
    mock_search_res = {
        "ok": True,
        "timestamp": "2026-05-31T00:00:00Z",
        "tool": "search_sources",
        "data": {
            "results": [
                {
                    "reference_id": "ref_123",
                    "title": "Toy Story 2 1080p BluRay",
                    "size_bytes": 4500000000,
                    "seeders": 12,
                    "indexer": "YTS"
                }
            ]
        }
    }
    
    # Mock no database match and mock search sources tool
    with patch("moviebot.bot.discord_app.LibraryItemRepository.search_by_normalized_title", return_value=[]), \
         patch("moviebot.bot.discord_app.search_sources_tool", return_value=mock_search_res):
        await button.callback(interaction)
        
    interaction.response.defer.assert_called_once_with(ephemeral=True)
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "embed" in kwargs
    assert "view" in kwargs
    assert kwargs["ephemeral"] is True
    assert "Indexer Results for: Toy Story 2" in kwargs["embed"].title
    assert "Toy Story 2 1080p" in kwargs["embed"].description


@pytest.mark.asyncio
async def test_slash_library_success():
    from moviebot.bot.discord_app import slash_library
    
    interaction = MagicMock(spec=discord.Interaction)
    interaction.response = MagicMock()
    interaction.response.defer = AsyncMock()
    interaction.followup = MagicMock()
    interaction.followup.send = AsyncMock()
    
    mock_res = {
        "ok": True,
        "timestamp": "2026-06-01T00:00:00Z",
        "tool": "query_library_tool",
        "data": {
            "movies": [
                {
                    "title": "Interstellar",
                    "year": 2014,
                    "resolution": "1080p",
                    "rating": 8.6,
                    "runtime": 169,
                    "watch_status": "watched",
                    "similarity_score": 0.95,
                    "genres": '["Sci-Fi", "Drama"]',
                    "directors": '["Christopher Nolan"]',
                    "brand_tags": '["Legendary Pictures"]',
                    "franchise_tags": '["Interstellar"]',
                    "universe_tags": '["Nolanverse"]',
                    "tagline": "Mankind was born on Earth. It was never meant to die here."
                }
            ],
            "query_routing": {
                "inferred_franchise": "Interstellar",
                "inferred_brand": "Legendary Pictures"
            },
            "semantic_search": {
                "query_model": "gemini-1.5-flash",
                "query_source": "gemini",
                "fallback": False
            }
        }
    }
    
    with patch("moviebot.bot.discord_app.query_library_tool", return_value=mock_res):
        await slash_library.callback(
            interaction,
            query="space",
            semantic_query="romantic movies in space",
            genre="Sci-Fi",
            director="Christopher Nolan"
        )
        
    interaction.response.defer.assert_called_once()
    interaction.followup.send.assert_called_once()
    _, kwargs = interaction.followup.send.call_args
    assert "embed" in kwargs
    embed = kwargs["embed"]
    assert embed.title == "🎬 Library Search Results"
    # Verify active search criteria displayed
    assert '🧠 **Semantic Query:** "romantic movies in space"' in embed.description
    assert '🔍 **Keyword Query:** "space"' in embed.description
    assert '🏷️ **Genre:** Sci-Fi' in embed.description
    assert '🎬 **Director:** Christopher Nolan' in embed.description
    # Verify Inferred Routing Filters are displayed
    assert "**Inferred Routing Filters:**" in embed.description
    assert "• 📦 **Franchise:** Interstellar" in embed.description
    assert "• 🏢 **Brand:** Legendary Pictures" in embed.description
    # Verify rich movie info (genres/directors and match percent)
    assert "Interstellar" in embed.description
    assert "95.0% Match" in embed.description
    assert "Dir: Christopher Nolan" in embed.description
    assert "Genres: Sci-Fi, Drama" in embed.description
    # Verify TMDB tags and tagline are displayed
    assert "Franchise: Interstellar" in embed.description
    assert "Brand: Legendary Pictures" in embed.description
    assert "Universe: Nolanverse" in embed.description
    assert '_"Mankind was born on Earth. It was never meant to die here."_' in embed.description

