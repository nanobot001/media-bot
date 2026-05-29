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
        response = client.post(
            "/webhook/tautulli",
            headers={"Authorization": "Bearer test_secret"},
            json={"event": "play", "title": "Inception", "user": "alice"}
        )
        assert response.status_code == 200
        assert response.json() == {"status": "success", "event_logged": "play"}


def test_webhook_authorized_query(mock_db):
    with patch("moviebot.config.settings.tautulli_webhook_secret", "test_secret"):
        response = client.post(
            "/webhook/tautulli?token=test_secret",
            json={"event": "stop", "title": "Inception", "user": "alice"}
        )
        assert response.status_code == 200
        assert response.json() == {"status": "success", "event_logged": "stop"}


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
         patch("moviebot.adapters.plex_client.PlexClient.fetch_movie_details", new_callable=AsyncMock) as mock_fetch:
        
        mock_fetch.return_value = mock_plex_movie
        
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
        
        # Verify Plex client was called
        mock_fetch.assert_called_once_with("12345")
        
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
