import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from moviebot.core.playback_notifications import (
    build_playback_embed,
    build_playback_state_key,
    _fetch_plex_thumbnail,
    post_or_update_playback_notification,
)
from moviebot.db.repositories import EventRepository, KeyValueRepository


@pytest.fixture
def mock_db(tmp_path):
    db_file = tmp_path / "test_playback_notifications.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


def test_build_playback_embed_episode_context():
    payload = {
        "event": "play",
        "rating_key": "12345",
        "session_key": "sess-1",
        "title": "Boys' Night",
        "grandparent_title": "Modern Family",
        "parent_title": "Season 3",
        "media_type": "episode",
        "user": "dorothyfung",
        "player": "AFTSSS",
        "season_num": 3,
        "episode_num": 18,
        "progress_percent": 12,
        "duration": 1320,
        "stream_video_resolution": "1080p",
        "stream_container_decision": "direct_play",
        "poster_url": "https://example.invalid/poster.jpg",
    }

    embed = build_playback_embed(payload)

    assert embed.title == "Now Playing"
    assert "**dorothyfung** is watching **Modern Family**" in embed.description
    assert "AFTSSS" in embed.description
    assert "12% complete" in embed.description
    assert "22m elapsed" in embed.description
    assert "1080p / Direct Play" in embed.description
    fields = {field.name: field.value for field in embed.fields}
    assert fields["Media"] == "S03E18 - Boys' Night"


def test_build_playback_state_key_prefers_session_key():
    payload = {
        "session_key": "sess-1",
        "rating_key": "12345",
        "user": "alice",
        "player": "Plex Web",
    }

    assert build_playback_state_key(payload) == "tautulli_playback_session:sess-1"


@pytest.mark.asyncio
async def test_post_start_stores_message_state_and_event(mock_db):
    payload = {
        "event": "play",
        "session_key": "sess-1",
        "rating_key": "12345",
        "title": "Inception",
        "user": "alice",
        "player": "Plex Web",
    }
    bot, channel, _message = _fake_bot()

    with patch("moviebot.config.settings.discord_playback_channel_id", 999), \
         patch("moviebot.config.settings.plex_token", ""):
        result = await post_or_update_playback_notification(payload, bot)

    assert result == "posted"
    channel.send.assert_awaited_once()
    stored = json.loads(KeyValueRepository.get("tautulli_playback_session:sess-1"))
    assert stored == {"channel_id": "999", "message_id": "555"}
    events = EventRepository.get_all()
    assert any(event["event_type"] == "playback_notification" and event["status"] == "posted" for event in events)


@pytest.mark.asyncio
async def test_post_start_uploads_plex_thumbnail_attachment(mock_db):
    payload = {
        "event": "play",
        "session_key": "sess-thumb",
        "rating_key": "12345",
        "title": "Inception",
        "user": "alice",
        "player": "Plex Web",
    }
    bot, channel, _message = _fake_bot()

    with patch("moviebot.config.settings.discord_playback_channel_id", 999), \
         patch("moviebot.core.playback_notifications._fetch_plex_thumbnail", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = b"fake-image-bytes"
        result = await post_or_update_playback_notification(payload, bot)

    assert result == "posted"
    channel.send.assert_awaited_once()
    kwargs = channel.send.call_args.kwargs
    assert kwargs["embed"].thumbnail.url == "attachment://media-thumb.jpg"
    assert kwargs["file"].filename == "media-thumb.jpg"
    stored = json.loads(KeyValueRepository.get("tautulli_playback_session:sess-thumb"))
    assert stored["thumbnail_url"] == "attachment://media-thumb.jpg"


@pytest.mark.asyncio
async def test_terminal_event_edits_existing_message(mock_db):
    KeyValueRepository.set(
        "tautulli_playback_session:sess-1",
        json.dumps({"channel_id": "999", "message_id": "555"}),
    )
    payload = {
        "event": "watched",
        "session_key": "sess-1",
        "rating_key": "12345",
        "title": "Inception",
        "user": "alice",
        "player": "Plex Web",
    }
    bot, channel, message = _fake_bot()

    result = await post_or_update_playback_notification(payload, bot)

    assert result == "updated"
    channel.fetch_message.assert_awaited_once_with(555)
    message.edit.assert_awaited_once()
    assert KeyValueRepository.get("tautulli_playback_session:sess-1") is None
    events = EventRepository.get_all()
    assert any(event["event_type"] == "playback_notification" and event["status"] == "updated" for event in events)


@pytest.mark.asyncio
async def test_terminal_event_preserves_attachment_thumbnail(mock_db):
    KeyValueRepository.set(
        "tautulli_playback_session:sess-thumb",
        json.dumps(
            {
                "channel_id": "999",
                "message_id": "555",
                "thumbnail_url": "attachment://media-thumb.jpg",
            }
        ),
    )
    payload = {
        "event": "stop",
        "session_key": "sess-thumb",
        "rating_key": "12345",
        "title": "Inception",
        "user": "alice",
        "player": "Plex Web",
    }
    bot, _channel, message = _fake_bot()

    result = await post_or_update_playback_notification(payload, bot)

    assert result == "updated"
    edited_embed = message.edit.call_args.kwargs["embed"]
    assert edited_embed.thumbnail.url == "attachment://media-thumb.jpg"


@pytest.mark.asyncio
async def test_terminal_event_without_state_is_silent_fallback(mock_db):
    payload = {
        "event": "stop",
        "session_key": "sess-missing",
        "rating_key": "12345",
        "title": "Inception",
        "user": "alice",
        "player": "Plex Web",
    }
    bot, channel, _message = _fake_bot()

    result = await post_or_update_playback_notification(payload, bot)

    assert result == "skipped_no_state"
    channel.send.assert_not_called()
    events = EventRepository.get_all()
    assert any(event["event_type"] == "playback_notification" and event["status"] == "skipped_no_state" for event in events)


@pytest.mark.asyncio
async def test_fetch_plex_thumbnail_uses_rating_key_without_exposing_token():
    class FakeResponse:
        headers = {"content-type": "image/jpeg"}
        content = b"image"

        def raise_for_status(self):
            return None

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def get(self, endpoint, params, timeout):
            self.endpoint = endpoint
            self.params = params
            self.timeout = timeout
            return FakeResponse()

    fake_client = FakeClient()
    with patch("moviebot.config.settings.plex_url", "http://plex.local:32400"), \
         patch("moviebot.config.settings.plex_token", "secret-token"), \
         patch("moviebot.core.playback_notifications.httpx.AsyncClient", return_value=fake_client):
        image = await _fetch_plex_thumbnail("12345")

    assert image == b"image"
    assert fake_client.endpoint == "http://plex.local:32400/library/metadata/12345/thumb"
    assert fake_client.params == {"X-Plex-Token": "secret-token"}


def _fake_bot():
    message = MagicMock()
    message.id = 555
    message.edit = AsyncMock()

    channel = MagicMock()
    channel.id = 999
    channel.send = AsyncMock(return_value=message)
    channel.fetch_message = AsyncMock(return_value=message)

    bot = MagicMock()
    bot.get_channel.return_value = channel
    bot.fetch_channel = AsyncMock(return_value=channel)
    return bot, channel, message
