import sqlite3
import os
from pathlib import Path
from typing import Optional
from moviebot.config import settings

CANONICAL_DOMAINS = {"movies", "anime", "tv", "tv_classic"}

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
    brand_tags TEXT,
    franchise_tags TEXT,
    universe_tags TEXT,
    source_property_tags TEXT,
    brand_evidence_json TEXT,
    franchise_evidence_json TEXT,
    universe_evidence_json TEXT,
    source_property_evidence_json TEXT,
    tmdb_id INTEGER,
    poster_url TEXT,
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

CREATE TABLE IF NOT EXISTS prewarmed_cache (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    season INTEGER DEFAULT 0,
    year INTEGER,
    reference_id TEXT NOT NULL,
    release_title TEXT NOT NULL,
    browser_stream_reference_id TEXT,
    browser_stream_release_title TEXT,
    browser_stream_verified_at TIMESTAMP,
    resolution TEXT,
    size_bytes INTEGER,
    formatted_size TEXT,
    seeders INTEGER DEFAULT 0,
    cached BOOLEAN DEFAULT 0,
    previously_cached BOOLEAN DEFAULT 0,
    dropped_at TIMESTAMP,
    vector_origin TEXT DEFAULT 'frontier',
    score INTEGER DEFAULT 0,
    data_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS release_variants (
    variant_id TEXT PRIMARY KEY,
    media_key TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    year INTEGER,
    tmdb_id INTEGER,
    imdb_id TEXT,
    tvdb_id TEXT,
    season INTEGER NOT NULL DEFAULT 0,
    episode INTEGER NOT NULL DEFAULT 0,
    scope_type TEXT NOT NULL,
    release_identity TEXT NOT NULL,
    reference_id TEXT,
    release_title TEXT NOT NULL,
    resolution TEXT,
    source_type TEXT,
    container TEXT,
    video_codec TEXT,
    audio_codec TEXT,
    hdr TEXT,
    channels TEXT,
    subtitle_summary TEXT,
    size_bytes INTEGER,
    formatted_size TEXT,
    seeders INTEGER,
    indexer TEXT,
    source_vector TEXT,
    ad_cache_status TEXT NOT NULL DEFAULT 'unknown',
    ad_checked_at TEXT,
    ad_error_code TEXT,
    ad_error_message TEXT,
    direct_play_status TEXT NOT NULL DEFAULT 'unknown',
    direct_play_verified_at TEXT,
    direct_play_error_code TEXT,
    direct_play_error_message TEXT,
    direct_play_evidence_json TEXT,
    mediaflow_status TEXT NOT NULL DEFAULT 'untested',
    mediaflow_checked_at TEXT,
    mediaflow_error_code TEXT,
    mediaflow_error_message TEXT,
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    last_cache_checked_at TEXT,
    last_observed_cycle_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(media_key, release_identity)
);

CREATE INDEX IF NOT EXISTS idx_release_variants_media
ON release_variants(media_key, last_seen_at DESC);

CREATE INDEX IF NOT EXISTS idx_release_variants_scope
ON release_variants(domain, normalized_title, year, season, episode, scope_type);

CREATE INDEX IF NOT EXISTS idx_release_variants_cache
ON release_variants(media_key, ad_cache_status, ad_checked_at DESC);

CREATE TABLE IF NOT EXISTS release_catalog_checks (
    check_id TEXT PRIMARY KEY,
    media_key TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    year INTEGER,
    tmdb_id INTEGER,
    season INTEGER NOT NULL DEFAULT 0,
    episode INTEGER NOT NULL DEFAULT 0,
    scope_type TEXT NOT NULL,
    status TEXT NOT NULL,
    candidate_count INTEGER NOT NULL DEFAULT 0,
    checked_count INTEGER NOT NULL DEFAULT 0,
    cached_count INTEGER NOT NULL DEFAULT 0,
    unknown_count INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL,
    cycle_id TEXT,
    error_code TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_release_catalog_checks_media
ON release_catalog_checks(media_key, checked_at DESC);

CREATE TABLE IF NOT EXISTS prewarm_runs (
    cycle_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    trigger_source TEXT NOT NULL,
    runtime_id TEXT NOT NULL,
    process_id INTEGER,
    scheduled_at TEXT NOT NULL,
    started_at TEXT,
    heartbeat_at TEXT,
    lease_expires_at TEXT,
    finished_at TEXT,
    next_due_at TEXT,
    interval_hours REAL NOT NULL DEFAULT 6.0,
    phase_counts_json TEXT,
    provider_error_count INTEGER NOT NULL DEFAULT 0,
    stop_reason TEXT,
    error_code TEXT,
    error_message TEXT,
    stats_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prewarm_runs_status_started
ON prewarm_runs(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_prewarm_runs_scheduled
ON prewarm_runs(scheduled_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prewarm_runs_single_running
ON prewarm_runs(status) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS prewarm_runtime_state (
    singleton_id INTEGER PRIMARY KEY CHECK (singleton_id = 1),
    next_due_at TEXT,
    lease_cycle_id TEXT,
    lease_runtime_id TEXT,
    lease_expires_at TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS stream_history (
    id TEXT PRIMARY KEY,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    year INTEGER,
    season INTEGER DEFAULT 0,
    episode INTEGER DEFAULT 0,
    release_title TEXT,
    stream_url TEXT,
    duration_seconds REAL DEFAULT 0,
    progress_seconds REAL DEFAULT 0,
    progress_percent REAL DEFAULT 0,
    completed INTEGER DEFAULT 0,
    player_type TEXT DEFAULT 'web',
    poster_url TEXT,
    last_streamed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS cloud_transfer_intents (
    transfer_id TEXT PRIMARY KEY,
    purpose TEXT NOT NULL,
    domain TEXT NOT NULL,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    year INTEGER,
    season INTEGER DEFAULT 0,
    reference_id TEXT NOT NULL,
    release_title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'queued',
    ready INTEGER NOT NULL DEFAULT 0,
    browser_stream_ready INTEGER NOT NULL DEFAULT 0,
    error_message TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_cloud_transfer_intents_media
ON cloud_transfer_intents(domain, normalized_title, year, season, created_at DESC);

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

CREATE TABLE IF NOT EXISTS user_profiles (
    discord_user_id TEXT PRIMARY KEY,
    plex_username TEXT UNIQUE,
    custom_taste_notes TEXT,
    metadata_json TEXT,         -- Preferences config like notifications, public_visibility, etc.
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL,
    category TEXT NOT NULL,      -- 'like', 'dislike', 'general_preference'
    fact TEXT NOT NULL,
    source TEXT NOT NULL,        -- 'chat_extraction', 'manual_profile', 'plex_sync'
    target_user_id TEXT,         -- For cross-user banter/memories
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(discord_user_id) REFERENCES user_profiles(discord_user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_interaction_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL,
    channel_id TEXT,
    query_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(discord_user_id) REFERENCES user_profiles(discord_user_id) ON DELETE CASCADE
);
"""

# TV Database Schema for tv and tv_classic domains
TV_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS tv_shows (
    id TEXT PRIMARY KEY,
    rating_key TEXT UNIQUE,
    title TEXT NOT NULL,
    normalized_title TEXT NOT NULL,
    year INTEGER,
    imdb_id TEXT,
    tmdb_id INTEGER,
    tvdb_id INTEGER,
    genres TEXT,
    networks TEXT,
    content_rating TEXT,
    tagline TEXT,
    synopsis TEXT,
    total_seasons INTEGER DEFAULT 0,
    total_episodes INTEGER DEFAULT 0,
    poster_url TEXT,
    banner_url TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tv_seasons (
    id TEXT PRIMARY KEY,
    show_id TEXT NOT NULL,
    season_number INTEGER NOT NULL,
    title TEXT,
    episode_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (show_id) REFERENCES tv_shows(id) ON DELETE CASCADE,
    UNIQUE(show_id, season_number)
);

CREATE TABLE IF NOT EXISTS tv_episodes (
    id TEXT PRIMARY KEY,
    show_id TEXT NOT NULL,
    season_number INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    rating_key TEXT,
    title TEXT,
    air_date TEXT,
    synopsis TEXT,
    file_path TEXT,
    size_bytes INTEGER,
    resolution TEXT,
    bitrate_kbps INTEGER,
    duration_ms INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (show_id) REFERENCES tv_shows(id) ON DELETE CASCADE,
    UNIQUE(show_id, season_number, episode_number)
);

CREATE VIRTUAL TABLE IF NOT EXISTS tv_shows_fts USING fts5(
    title,
    genres,
    networks,
    synopsis,
    content='tv_shows',
    content_rowid='rowid'
);

-- Triggers for tv_shows_fts synchronization
CREATE TRIGGER IF NOT EXISTS tv_shows_ai AFTER INSERT ON tv_shows BEGIN
    INSERT INTO tv_shows_fts(rowid, title, genres, networks, synopsis)
    VALUES (new.rowid, new.title, new.genres, new.networks, new.synopsis);
END;

CREATE TRIGGER IF NOT EXISTS tv_shows_ad AFTER DELETE ON tv_shows BEGIN
    INSERT INTO tv_shows_fts(tv_shows_fts, rowid, title, genres, networks, synopsis)
    VALUES ('delete', old.rowid, old.title, old.genres, old.networks, old.synopsis);
END;

CREATE TRIGGER IF NOT EXISTS tv_shows_au AFTER UPDATE ON tv_shows BEGIN
    INSERT INTO tv_shows_fts(tv_shows_fts, rowid, title, genres, networks, synopsis)
    VALUES ('delete', old.rowid, old.title, old.genres, old.networks, old.synopsis);
    INSERT INTO tv_shows_fts(rowid, title, genres, networks, synopsis)
    VALUES (new.rowid, new.title, new.genres, new.networks, new.synopsis);
END;

CREATE INDEX IF NOT EXISTS idx_tv_shows_tmdb_id ON tv_shows(tmdb_id);
CREATE INDEX IF NOT EXISTS idx_tv_shows_imdb_id ON tv_shows(imdb_id);
CREATE INDEX IF NOT EXISTS idx_tv_shows_tvdb_id ON tv_shows(tvdb_id);
CREATE INDEX IF NOT EXISTS idx_tv_shows_title_year ON tv_shows(normalized_title, year);
CREATE INDEX IF NOT EXISTS idx_tv_episodes_show_season ON tv_episodes(show_id, season_number, episode_number);

CREATE TABLE IF NOT EXISTS search_results (
    id TEXT PRIMARY KEY,
    query_string TEXT NOT NULL,
    indexer TEXT NOT NULL,
    title TEXT NOT NULL,
    size_bytes INTEGER,
    seeders INTEGER,
    magnet_uri_hash TEXT NOT NULL,
    raw_json_payload TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS download_jobs (
    id TEXT PRIMARY KEY,
    alldebrid_magnet_id TEXT,
    selected_file_name TEXT,
    target_dir TEXT DEFAULT 'F:\\_temp\\movies',
    status TEXT NOT NULL,
    discord_message_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

CREATE TABLE IF NOT EXISTS user_profiles (
    discord_user_id TEXT PRIMARY KEY,
    plex_username TEXT UNIQUE,
    custom_taste_notes TEXT,
    metadata_json TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL,
    category TEXT NOT NULL,
    fact TEXT NOT NULL,
    source TEXT NOT NULL,
    target_user_id TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(discord_user_id) REFERENCES user_profiles(discord_user_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS user_interaction_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_user_id TEXT NOT NULL,
    channel_id TEXT,
    query_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(discord_user_id) REFERENCES user_profiles(discord_user_id) ON DELETE CASCADE
);
"""



def get_db_connection(domain: Optional[str] = None) -> sqlite3.Connection:
    """Returns a SQLite connection to the configured database, creating directories if needed."""
    from typing import Optional
    if domain is None:
        domain = "movies"
        
    if domain not in CANONICAL_DOMAINS:
        raise ValueError(f"Invalid media domain: '{domain}'")
        
    if domain == "movies":
        db_path_str = settings.database_path
    elif domain == "anime":
        db_path_str = settings.anime_database_path
    elif domain == "tv":
        db_path_str = settings.tv_database_path
    elif domain == "tv_classic":
        db_path_str = settings.tv_classic_database_path
    else:
        raise ValueError(f"Invalid media domain: '{domain}'")
        
    db_path = Path(db_path_str)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    conn = sqlite3.connect(str(db_path), timeout=30.0)
    conn.row_factory = sqlite3.Row
    # Enable WAL mode
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db(domain: Optional[str] = None) -> None:
    """Bootstraps the SQLite database and tables."""
    if domain is None:
        domain = "movies"
        
    if domain not in CANONICAL_DOMAINS:
        raise ValueError(f"Invalid media domain: '{domain}'")
        
    if domain in ("tv", "tv_classic"):
        with get_db_connection(domain) as conn:
            conn.executescript(TV_SCHEMA_SQL)
            conn.commit()
        return

    if domain != "movies":
        with get_db_connection(domain) as conn:
            pass
        return


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

    with get_db_connection(domain) as conn:
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
            ("hard_fact_sources_json", "TEXT"),
            ("brand_tags", "TEXT"),
            ("franchise_tags", "TEXT"),
            ("universe_tags", "TEXT"),
            ("source_property_tags", "TEXT"),
            ("brand_evidence_json", "TEXT"),
            ("franchise_evidence_json", "TEXT"),
            ("universe_evidence_json", "TEXT"),
            ("source_property_evidence_json", "TEXT"),
            ("tmdb_id", "INTEGER"),
            ("poster_url", "TEXT")
        ]
        
        for col_name, col_type in new_cols:
            if col_name not in columns:
                cursor.execute(f"ALTER TABLE library_items ADD COLUMN {col_name} {col_type}")

        cursor.execute("CREATE INDEX IF NOT EXISTS idx_library_items_rating_key ON library_items(rating_key)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_library_items_imdb_id ON library_items(imdb_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_library_items_tmdb_id ON library_items(tmdb_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_library_items_title_year ON library_items(normalized_title, year)")
        
        # Check if discord_message_id column exists in download_jobs (self-healing migration)
        cursor.execute("PRAGMA table_info(download_jobs)")
        dl_columns = [row[1] for row in cursor.fetchall()]
        if "discord_message_id" not in dl_columns:
            cursor.execute("ALTER TABLE download_jobs ADD COLUMN discord_message_id TEXT")

        # Check if previously_cached, dropped_at, and vector_origin exist in prewarmed_cache (self-healing migration)
        cursor.execute("PRAGMA table_info(prewarmed_cache)")
        pw_columns = [row[1] for row in cursor.fetchall()]
        if "previously_cached" not in pw_columns:
            cursor.execute("ALTER TABLE prewarmed_cache ADD COLUMN previously_cached BOOLEAN DEFAULT 0")
        if "dropped_at" not in pw_columns:
            cursor.execute("ALTER TABLE prewarmed_cache ADD COLUMN dropped_at TIMESTAMP")
        if "vector_origin" not in pw_columns:
            cursor.execute("ALTER TABLE prewarmed_cache ADD COLUMN vector_origin TEXT DEFAULT 'frontier'")
        if "year" not in pw_columns:
            cursor.execute("ALTER TABLE prewarmed_cache ADD COLUMN year INTEGER")
        if "browser_stream_reference_id" not in pw_columns:
            cursor.execute("ALTER TABLE prewarmed_cache ADD COLUMN browser_stream_reference_id TEXT")
        if "browser_stream_release_title" not in pw_columns:
            cursor.execute("ALTER TABLE prewarmed_cache ADD COLUMN browser_stream_release_title TEXT")
        if "browser_stream_verified_at" not in pw_columns:
            cursor.execute("ALTER TABLE prewarmed_cache ADD COLUMN browser_stream_verified_at TIMESTAMP")

        # Self-healing creation of stream_history
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stream_history (
                id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                title TEXT NOT NULL,
                year INTEGER,
                season INTEGER DEFAULT 0,
                episode INTEGER DEFAULT 0,
                release_title TEXT,
                stream_url TEXT,
                duration_seconds REAL DEFAULT 0,
                progress_seconds REAL DEFAULT 0,
                progress_percent REAL DEFAULT 0,
                completed INTEGER DEFAULT 0,
                player_type TEXT DEFAULT 'web',
                poster_url TEXT,
                last_streamed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
             )
        """)

        cursor.execute("PRAGMA table_info(stream_history)")
        stream_history_columns = [row[1] for row in cursor.fetchall()]
        if "year" not in stream_history_columns:
            cursor.execute("ALTER TABLE stream_history ADD COLUMN year INTEGER")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS cloud_transfer_intents (
                transfer_id TEXT PRIMARY KEY,
                purpose TEXT NOT NULL,
                domain TEXT NOT NULL,
                title TEXT NOT NULL,
                normalized_title TEXT NOT NULL,
                year INTEGER,
                season INTEGER DEFAULT 0,
                reference_id TEXT NOT NULL,
                release_title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                ready INTEGER NOT NULL DEFAULT 0,
                browser_stream_ready INTEGER NOT NULL DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_cloud_transfer_intents_media
            ON cloud_transfer_intents(domain, normalized_title, year, season, created_at DESC)
        """)
            
        if needs_rebuild:
            cursor.execute("INSERT INTO library_items_fts(library_items_fts) VALUES('rebuild')")
            
        conn.commit()

    # Keep the legacy table readable and migrate only by additive, idempotent
    # catalog upserts. Existing rows are never deleted or rewritten here.
    from moviebot.db.release_variant_repo import ReleaseVariantRepository
    ReleaseVariantRepository.migrate_legacy_prewarmed_cache()
