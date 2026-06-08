import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient
from moviebot.config import settings
from moviebot.api.webhook import app
from moviebot.db.repositories import EventRepository, LibraryItemRepository

client = TestClient(app)

@pytest.fixture
def mock_db(tmp_path):
    """Sets up a temporary SQLite database for testing."""
    db_file = tmp_path / "test_moviebot_webhook.sqlite3"
    with patch("moviebot.config.settings.database_path", str(db_file)):
        from moviebot.db.connection import init_db
        init_db()
        yield db_file


def test_webhook_unauthorized():
    response = client.post("/webhook/tautulli", json={"event": "play"})
    assert response.status_code == 401
    
    response = client.post("/webhook/tautulli?token=wrong", json={"event": "play"})
    assert response.status_code == 401
    
    response = client.post(
        "/webhook/tautulli",
        headers={"Authorization": "Bearer wrong"},
        json={"event": "play"}
    )
    assert response.status_code == 401


def test_webhook_authorized_header(mock_db):
    with patch("moviebot.config.settings.tautulli_webhook_secret", "test_secret"):
        with patch("moviebot.api.webhook._post_or_update_playback_notification", new_callable=AsyncMock) as mock_notify:
            response = client.post(
                "/webhook/tautulli",
                headers={"Authorization": "Bearer test_secret"},
                json={"event": "play", "title": "Inception", "user": "alice"}
            )
        assert response.status_code == 200
        assert response.json() == {"status": "success", "event_logged": "play"}
        mock_notify.assert_called_once()


def test_webhook_authorized_query(mock_db):
    with patch("moviebot.config.settings.tautulli_webhook_secret", "test_secret"):
        with patch("moviebot.api.webhook._post_or_update_playback_notification", new_callable=AsyncMock) as mock_notify:
            response = client.post(
                "/webhook/tautulli?token=test_secret",
                json={"event": "stop", "title": "Inception", "user": "alice"}
            )
        assert response.status_code == 200
        assert response.json() == {"status": "success", "event_logged": "stop"}
        mock_notify.assert_called_once()


def test_webhook_playback_payload_accepts_rich_fields(mock_db):
    with patch("moviebot.config.settings.tautulli_webhook_secret", "test_secret"), \
         patch("moviebot.api.webhook._post_or_update_playback_notification", new_callable=AsyncMock) as mock_notify:
        response = client.post(
            "/webhook/tautulli?token=test_secret",
            json={
                "event": "play",
                "rating_key": "12345",
                "title": "Boys' Night",
                "grandparent_title": "Modern Family",
                "parent_title": "Season 3",
                "media_type": "episode",
                "user": "dorothyfung",
                "player": "AFTSSS",
                "session_key": "abc123",
                "season_num": 3,
                "episode_num": 18,
                "progress_percent": 0,
                "duration": 1320,
                "stream_video_resolution": "1080p",
                "stream_container_decision": "direct_play",
                "poster_url": "https://example.invalid/poster.jpg"
            }
        )

    assert response.status_code == 200
    payload = mock_notify.call_args[0][0]
    assert payload.session_key == "abc123"
    assert payload.grandparent_title == "Modern Family"
    assert payload.season_num == 3


def test_webhook_watched_sync(mock_db):
    mock_plex_movie = {
        "id": "plex_12345",
        "source": "plex",
        "rating_key": "12345",
        "title": "The Matrix",
        "year": 1999,
        "imdb_id": "tt0133093",
        "file_path": "/movies/The Matrix (1999).mp4",
        "size_bytes": 1024000
    }

    with patch("moviebot.config.settings.tautulli_webhook_secret", "test_secret"), \
         patch("moviebot.api.webhook._post_or_update_playback_notification", new_callable=AsyncMock), \
         patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch, \
         patch("moviebot.core.mismatch_guard.MismatchGuard.audit_plex_item", new_callable=AsyncMock) as mock_audit:
        
        mock_fetch.return_value = mock_plex_movie
        mock_audit.return_value = {"status": "correct", "similarity": 100.0}
        
        response = client.post(
            "/webhook/tautulli?token=test_secret",
            json={
                "event": "watched",
                "rating_key": "12345",
                "title": "The Matrix",
                "user": "bob"
            }
        )
        assert response.status_code == 200
        assert response.json() == {"status": "success", "event_logged": "watched"}
        
        # Verify Plex client was called for sync
        mock_fetch.assert_called_with("12345")
        
        # Verify MismatchGuard audit was triggered
        mock_audit.assert_called_once_with("12345")
        
        # Verify db contains the synced item
        items = LibraryItemRepository.get_by_normalized_title_and_year("matrix", 1999)
        assert len(items) == 1
        assert items[0]["rating_key"] == "12345"
        assert items[0]["imdb_id"] == "tt0133093"
        assert items[0]["file_path"] == "/movies/The Matrix (1999).mp4"
        
        # Verify events table logged the entries
        events = EventRepository.get_all()
        assert len(events) == 2
        event_types = [e["event_type"] for e in events]
        assert "watched" in event_types


def test_webhook_added_triggers_auto_enrich(mock_db):
    """Verify that 'added' events trigger the auto-enrich background task."""
    import json

    mock_plex_movie = {
        "id": "plex_99999",
        "source": "plex",
        "rating_key": "99999",
        "title": "Anne of Green Gables",
        "year": 1985,
        "imdb_id": "tt0088727",
        "file_path": "/movies/Anne of Green Gables (1985).mkv",
        "size_bytes": 2048000,
        "genres": json.dumps(["Drama", "Family"]),
        "studios": json.dumps(["CBC"]),
        "content_rating": "G",
        "rating": 8.5,
        "synopsis": "An orphan girl is sent to live on Prince Edward Island.",
        "synopsis_hash": "abc123",
    }

    with patch("moviebot.config.settings.tautulli_webhook_secret", "test_secret"), \
         patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch, \
         patch("moviebot.core.mismatch_guard.MismatchGuard.audit_plex_item", new_callable=AsyncMock) as mock_audit, \
         patch("moviebot.api.webhook._auto_enrich_and_notify", new_callable=AsyncMock) as mock_enrich:

        mock_fetch.return_value = mock_plex_movie
        mock_audit.return_value = {"status": "correct", "similarity": 100.0}

        response = client.post(
            "/webhook/tautulli?token=test_secret",
            json={
                "event": "added",
                "rating_key": "99999",
                "title": "Anne of Green Gables",
                "user": "system"
            }
        )
        assert response.status_code == 200

        # Verify auto-enrich was scheduled
        mock_enrich.assert_called_once()
        call_args = mock_enrich.call_args[0][0]
        assert call_args["title"] == "Anne of Green Gables"


def test_build_new_movie_embed():
    """Verify the embed builder produces a valid embed with all enrichment fields."""
    from moviebot.core.auto_enrich import build_new_movie_embed
    import json

    item = {
        "title": "Anne of Green Gables",
        "year": 1985,
        "genres": json.dumps(["Drama", "Family"]),
        "studios": json.dumps(["CBC"]),
        "content_rating": "G",
        "rating": 8.5,
        "runtime": 195,
    }

    enrichment = {
        "theme_tags": ["coming of age", "family", "imagination"],
        "tone_tags": ["warm", "nostalgic"],
        "premise_tags": ["orphan", "new home"],
        "setting_locations": ["Prince Edward Island"],
        "award_tags": ["emmy_winner"],
        "source_material_tags": ["based_on_book"],
        "popularity_tags": ["classic"],
        "cultural_impact_tags": ["classic", "canadian icon"],
        "content_warning_tags": [],
        "enrichment_json": {"source": "gemini"},
        "hard_fact_sources_json": {"source": "plex_curation"},
    }

    embed = build_new_movie_embed(item, enrichment)

    assert "Anne of Green Gables" in embed.title
    assert "1985" in embed.title
    assert embed.color.value == 0x1abc9c  # discord.Color.teal()
    assert len(embed.fields) >= 4  # themes, tone, premise, setting at minimum
    assert "Enrichment: gemini" in embed.footer.text

