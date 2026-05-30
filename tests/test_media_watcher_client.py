import json
import pytest
from moviebot.adapters.media_watcher_client import MediaWatcherClient


def test_client_file_not_found(tmp_path):
    state_file = tmp_path / "nonexistent.json"
    client = MediaWatcherClient(state_file)
    
    assert client.get_tracked_files() == []
    assert client.get_last_batch() == {"processed_at": None, "results": []}
    assert client.is_file_tracked("Inception.mkv") is False
    assert client.get_file_status("Inception.mkv") == ("unknown", None)


def test_client_invalid_json(tmp_path):
    state_file = tmp_path / "corrupt.json"
    with open(state_file, "w", encoding="utf-8") as f:
        f.write("{invalid: json")
        
    client = MediaWatcherClient(state_file)
    
    assert client.get_tracked_files() == []
    assert client.get_last_batch() == {"processed_at": None, "results": []}
    assert client.is_file_tracked("Inception.mkv") is False
    assert client.get_file_status("Inception.mkv") == ("unknown", None)


def test_client_status_resolution(tmp_path):
    state_data = {
        "last_scan": "2026-05-30T01:40:00Z",
        "tracked_files": [
            {
                "filename": "Predator.Badlands.2025.mkv",
                "size_bytes": 12345,
                "stable": True,
                "first_seen_at": "2026-05-30T01:30:00Z",
                "stable_at": "2026-05-30T01:35:00Z"
            }
        ],
        "last_batch": {
            "processed_at": "2026-05-30T01:38:00Z",
            "results": [
                {
                    "source_file": "Inception.2010.mkv",
                    "dest_path": "Movies/Inception (2010)/Inception.2010.mkv",
                    "success": True,
                    "error": None
                },
                {
                    "source_file": "Gladiator.II.2024.mkv",
                    "dest_path": None,
                    "success": False,
                    "error": "FileBot error: Access denied"
                }
            ]
        }
    }
    
    state_file = tmp_path / "watcher-state.json"
    with open(state_file, "w", encoding="utf-8") as f:
        json.dump(state_data, f)
        
    client = MediaWatcherClient(state_file)
    
    # Check is_file_tracked
    assert client.is_file_tracked("Predator.Badlands.2025.mkv") is True
    assert client.is_file_tracked("predator.badlands.2025.mkv") is True  # Case insensitive
    assert client.is_file_tracked("Inception.2010.mkv") is False
    
    # Check status resolution
    assert client.get_file_status("Predator.Badlands.2025.mkv") == ("tracking", None)
    assert client.get_file_status("Inception.2010.mkv") == ("processed", None)
    assert client.get_file_status("Gladiator.II.2024.mkv") == ("failed", "FileBot error: Access denied")
    assert client.get_file_status("Unknown.Movie.mkv") == ("unknown", None)
