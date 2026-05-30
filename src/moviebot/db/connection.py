import sqlite3
import os
from pathlib import Path
from moviebot.config import settings

# Database Schema
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS library_items (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,          -- 'plex' or 'tautulli'
    rating_key TEXT,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,-- Cleaned, alphanumeric comparison base
    year INTEGER,
    imdb_id TEXT,
    file_path TEXT,
    size_bytes INTEGER,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS search_results (
    id TEXT PRIMARY KEY,
    query_string TEXT NOT NULL,
    indexer TEXT NOT NULL,
    title TEXT NOT NULL,
    size_bytes INTEGER,
    seeders INTEGER,
    magnet_uri_hash TEXT NOT NULL, -- Redacted or cryptographic identifier
    raw_json_payload TEXT,         -- Internal tracking state debug dump
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id TEXT PRIMARY KEY,
    alldebrid_magnet_id TEXT,
    selected_file_name TEXT,
    target_dir TEXT DEFAULT 'F:\\_temp\\movies',
    status TEXT NOT NULL,          -- 'pending', 'downloading', 'completed', 'failed'
    discord_message_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Persistent Key-Value Cache Store
CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS errors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    command_name TEXT,
    user_id TEXT,
    user_name TEXT,
    error_message TEXT,
    stack_trace TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    source TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    entity_type TEXT,
    entity_id TEXT,
    status TEXT,
    severity TEXT NOT NULL DEFAULT 'info',
    occurred_at TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_json TEXT
);
"""


def get_db_connection() -> sqlite3.Connection:
    """Returns a SQLite connection to the configured database, creating directories if needed."""
    db_path = Path(settings.database_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """Bootstraps the SQLite database and tables."""
    with get_db_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        
        # Check if discord_message_id column exists in download_jobs (self-healing migration)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(download_jobs)")
        columns = [row[1] for row in cursor.fetchall()]
        if "discord_message_id" not in columns:
            cursor.execute("ALTER TABLE download_jobs ADD COLUMN discord_message_id TEXT")
            
        conn.commit()
