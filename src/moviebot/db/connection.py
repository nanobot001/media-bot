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
    genres TEXT,
    directors TEXT,
    studios TEXT,
    writers TEXT,
    producers TEXT,
    cast TEXT,
    countries TEXT,
    content_rating TEXT,
    audience_rating REAL,
    tagline TEXT,
    originally_available_at TEXT,
    labels TEXT,
    rating REAL,
    runtime INTEGER,
    collections TEXT,
    resolution TEXT,
    bitrate_kbps INTEGER,
    watch_status TEXT,
    watch_count INTEGER DEFAULT 0,
    last_watched_at TEXT,
    synopsis TEXT,
    synopsis_hash TEXT,
    metadata_refreshed_at TEXT,
    synopsis_vector BLOB,
    synopsis_vector_model TEXT,
    synopsis_vector_dim INTEGER,
    synopsis_vector_updated_at TEXT,
    enrichment_json TEXT,
    setting_locations TEXT,
    premise_tags TEXT,
    character_tags TEXT,
    theme_tags TEXT,
    tone_tags TEXT,
    craft_tags TEXT,
    content_warning_tags TEXT,
    content_warnings_json TEXT,
    field_confidence_json TEXT,
    field_evidence_json TEXT,
    enrichment_version TEXT,
    enrichment_model TEXT,
    enrichment_updated_at TEXT,
    story_locations TEXT,
    filming_locations TEXT,
    production_countries TEXT,
    mentioned_locations TEXT,
    event_locations TEXT,
    central_premise_tags TEXT,
    subplot_tags TEXT,
    protagonist_tags TEXT,
    antagonist_tags TEXT,
    supporting_character_tags TEXT,
    central_theme_tags TEXT,
    minor_theme_tags TEXT,
    dominant_tone_tags TEXT,
    secondary_tone_tags TEXT,
    ending_tone_tags TEXT,
    format_tags TEXT,
    visual_style_tags TEXT,
    narrative_structure_tags TEXT,
    music_role_tags TEXT,
    depicted_content_warning_tags TEXT,
    discussed_content_warning_tags TEXT,
    award_tags TEXT,
    award_wins_json TEXT,
    award_nominations_json TEXT,
    acclaim_tags TEXT,
    source_material_tags TEXT,
    adaptation_type_tags TEXT,
    popularity_tags TEXT,
    cultural_impact_tags TEXT,
    box_office_tier TEXT,
    hard_fact_sources_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE VIRTUAL TABLE IF NOT EXISTS library_items_fts USING fts5(
    title,
    genres,
    directors,
    collections,
    synopsis,
    content='library_items',
    content_rowid='rowid'
);

-- Triggers for FTS5 synchronization
CREATE TRIGGER IF NOT EXISTS library_items_ai AFTER INSERT ON library_items BEGIN
    INSERT INTO library_items_fts(rowid, title, genres, directors, collections, synopsis)
    VALUES (new.rowid, new.title, new.genres, new.directors, new.collections, new.synopsis);
END;

CREATE TRIGGER IF NOT EXISTS library_items_ad AFTER DELETE ON library_items BEGIN
    INSERT INTO library_items_fts(library_items_fts, rowid, title, genres, directors, collections, synopsis)
    VALUES ('delete', old.rowid, old.title, old.genres, old.directors, old.collections, old.synopsis);
END;

CREATE TRIGGER IF NOT EXISTS library_items_au AFTER UPDATE ON library_items BEGIN
    INSERT INTO library_items_fts(library_items_fts, rowid, title, genres, directors, collections, synopsis)
    VALUES ('delete', old.rowid, old.title, old.genres, old.directors, old.collections, old.synopsis);
    INSERT INTO library_items_fts(rowid, title, genres, directors, collections, synopsis)
    VALUES (new.rowid, new.title, new.genres, new.directors, new.collections, new.synopsis);
END;

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
    
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Bootstraps the SQLite database and tables."""
    # Check if FTS is empty and needs rebuild before running executescript
    db_path = Path(settings.database_path)
    needs_rebuild = False
    if db_path.exists():
        try:
            with sqlite3.connect(str(db_path), timeout=30.0) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                
                # Check if library_items has rows
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='library_items'")
                if cursor.fetchone():
                    cursor.execute("SELECT COUNT(*) FROM library_items")
                    items_count = cursor.fetchone()[0]
                    
                    if items_count > 0:
                        # Check if FTS table exists
                        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='library_items_fts'")
                        if not cursor.fetchone():
                            needs_rebuild = True
                        else:
                            cursor.execute("SELECT COUNT(*) FROM library_items_fts")
                            fts_count = cursor.fetchone()[0]
                            if fts_count == 0:
                                needs_rebuild = True
        except Exception:
            pass

    with get_db_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        
        # Check if columns exist in library_items (self-healing migration)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(library_items)")
        columns = [row[1] for row in cursor.fetchall()]
        
        new_cols = [
            ("genres", "TEXT"),
            ("directors", "TEXT"),
            ("studios", "TEXT"),
            ("writers", "TEXT"),
            ("producers", "TEXT"),
            ("cast", "TEXT"),
            ("countries", "TEXT"),
            ("content_rating", "TEXT"),
            ("audience_rating", "REAL"),
            ("tagline", "TEXT"),
            ("originally_available_at", "TEXT"),
            ("labels", "TEXT"),
            ("rating", "REAL"),
            ("runtime", "INTEGER"),
            ("collections", "TEXT"),
            ("resolution", "TEXT"),
            ("bitrate_kbps", "INTEGER"),
            ("watch_status", "TEXT"),
            ("watch_count", "INTEGER DEFAULT 0"),
            ("last_watched_at", "TEXT"),
            ("synopsis", "TEXT"),
            ("synopsis_hash", "TEXT"),
            ("metadata_refreshed_at", "TEXT"),
            ("synopsis_vector", "BLOB"),
            ("synopsis_vector_model", "TEXT"),
            ("synopsis_vector_dim", "INTEGER"),
            ("synopsis_vector_updated_at", "TEXT"),
            ("enrichment_json", "TEXT"),
            ("setting_locations", "TEXT"),
            ("premise_tags", "TEXT"),
            ("character_tags", "TEXT"),
            ("theme_tags", "TEXT"),
            ("tone_tags", "TEXT"),
            ("craft_tags", "TEXT"),
            ("content_warning_tags", "TEXT"),
            ("content_warnings_json", "TEXT"),
            ("field_confidence_json", "TEXT"),
            ("field_evidence_json", "TEXT"),
            ("enrichment_version", "TEXT"),
            ("enrichment_model", "TEXT"),
            ("enrichment_updated_at", "TEXT"),
            ("story_locations", "TEXT"),
            ("filming_locations", "TEXT"),
            ("production_countries", "TEXT"),
            ("mentioned_locations", "TEXT"),
            ("event_locations", "TEXT"),
            ("central_premise_tags", "TEXT"),
            ("subplot_tags", "TEXT"),
            ("protagonist_tags", "TEXT"),
            ("antagonist_tags", "TEXT"),
            ("supporting_character_tags", "TEXT"),
            ("central_theme_tags", "TEXT"),
            ("minor_theme_tags", "TEXT"),
            ("dominant_tone_tags", "TEXT"),
            ("secondary_tone_tags", "TEXT"),
            ("ending_tone_tags", "TEXT"),
            ("format_tags", "TEXT"),
            ("visual_style_tags", "TEXT"),
            ("narrative_structure_tags", "TEXT"),
            ("music_role_tags", "TEXT"),
            ("depicted_content_warning_tags", "TEXT"),
            ("discussed_content_warning_tags", "TEXT"),
            ("award_tags", "TEXT"),
            ("award_wins_json", "TEXT"),
            ("award_nominations_json", "TEXT"),
            ("acclaim_tags", "TEXT"),
            ("source_material_tags", "TEXT"),
            ("adaptation_type_tags", "TEXT"),
            ("popularity_tags", "TEXT"),
            ("cultural_impact_tags", "TEXT"),
            ("box_office_tier", "TEXT"),
            ("hard_fact_sources_json", "TEXT")
        ]
        
        for col_name, col_type in new_cols:
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE library_items ADD COLUMN {col_name} {col_type}")
        
        # Check if discord_message_id column exists in download_jobs (self-healing migration)
        cursor.execute("PRAGMA table_info(download_jobs)")
        dl_columns = [row[1] for row in cursor.fetchall()]
        if "discord_message_id" not in dl_columns:
            cursor.execute("ALTER TABLE download_jobs ADD COLUMN discord_message_id TEXT")
            
        if needs_rebuild:
            cursor.execute("INSERT INTO library_items_fts(library_items_fts) VALUES('rebuild')")
            
        conn.commit()
