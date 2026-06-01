import json
from typing import Optional, List, Dict, Any
from moviebot.db.connection import get_db_connection


class LibraryItemRepository:
    @staticmethod
    def upsert(
        id: str,
        source: str,
        rating_key: Optional[str],
        title: str,
        normalized_title: str,
        year: Optional[int],
        imdb_id: Optional[str],
        file_path: Optional[str],
        size_bytes: Optional[int],
        genres: Optional[str] = None,
        directors: Optional[str] = None,
        studios: Optional[str] = None,
        writers: Optional[str] = None,
        producers: Optional[str] = None,
        cast: Optional[str] = None,
        countries: Optional[str] = None,
        content_rating: Optional[str] = None,
        audience_rating: Optional[float] = None,
        tagline: Optional[str] = None,
        originally_available_at: Optional[str] = None,
        labels: Optional[str] = None,
        rating: Optional[float] = None,
        runtime: Optional[int] = None,
        collections: Optional[str] = None,
        resolution: Optional[str] = None,
        bitrate_kbps: Optional[int] = None,
        watch_status: Optional[str] = None,
        watch_count: int = 0,
        last_watched_at: Optional[str] = None,
        synopsis: Optional[str] = None,
        synopsis_hash: Optional[str] = None,
        metadata_refreshed_at: Optional[str] = None,
        synopsis_vector: Optional[bytes] = None,
        synopsis_vector_model: Optional[str] = None,
        synopsis_vector_dim: Optional[int] = None,
        synopsis_vector_updated_at: Optional[str] = None
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO library_items (
                    id, source, rating_key, title, normalized_title, year, imdb_id, file_path, size_bytes,
                    genres, directors, studios, writers, producers, cast, countries, content_rating,
                    audience_rating, tagline, originally_available_at, labels,
                    rating, runtime, collections, resolution, bitrate_kbps,
                    watch_status, watch_count, last_watched_at, synopsis, synopsis_hash, metadata_refreshed_at,
                    synopsis_vector, synopsis_vector_model, synopsis_vector_dim, synopsis_vector_updated_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    source=excluded.source,
                    rating_key=excluded.rating_key,
                    title=excluded.title,
                    normalized_title=excluded.normalized_title,
                    year=excluded.year,
                    imdb_id=excluded.imdb_id,
                    file_path=excluded.file_path,
                    size_bytes=excluded.size_bytes,
                    genres=excluded.genres,
                    directors=excluded.directors,
                    studios=excluded.studios,
                    writers=excluded.writers,
                    producers=excluded.producers,
                    cast=excluded.cast,
                    countries=excluded.countries,
                    content_rating=excluded.content_rating,
                    audience_rating=excluded.audience_rating,
                    tagline=excluded.tagline,
                    originally_available_at=excluded.originally_available_at,
                    labels=excluded.labels,
                    rating=excluded.rating,
                    runtime=excluded.runtime,
                    collections=excluded.collections,
                    resolution=excluded.resolution,
                    bitrate_kbps=excluded.bitrate_kbps,
                    watch_status=excluded.watch_status,
                    watch_count=excluded.watch_count,
                    last_watched_at=excluded.last_watched_at,
                    synopsis=excluded.synopsis,
                    synopsis_hash=excluded.synopsis_hash,
                    metadata_refreshed_at=excluded.metadata_refreshed_at,
                    synopsis_vector=CASE
                        WHEN excluded.synopsis_vector IS NULL
                             AND library_items.synopsis_hash = excluded.synopsis_hash
                        THEN library_items.synopsis_vector
                        ELSE excluded.synopsis_vector
                    END,
                    synopsis_vector_model=CASE
                        WHEN excluded.synopsis_vector_model IS NULL
                             AND library_items.synopsis_hash = excluded.synopsis_hash
                        THEN library_items.synopsis_vector_model
                        ELSE excluded.synopsis_vector_model
                    END,
                    synopsis_vector_dim=CASE
                        WHEN excluded.synopsis_vector_dim IS NULL
                             AND library_items.synopsis_hash = excluded.synopsis_hash
                        THEN library_items.synopsis_vector_dim
                        ELSE excluded.synopsis_vector_dim
                    END,
                    synopsis_vector_updated_at=CASE
                        WHEN excluded.synopsis_vector_updated_at IS NULL
                             AND library_items.synopsis_hash = excluded.synopsis_hash
                        THEN library_items.synopsis_vector_updated_at
                        ELSE excluded.synopsis_vector_updated_at
                    END,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (
                    id, source, rating_key, title, normalized_title, year, imdb_id, file_path, size_bytes,
                    genres, directors, studios, writers, producers, cast, countries, content_rating,
                    audience_rating, tagline, originally_available_at, labels,
                    rating, runtime, collections, resolution, bitrate_kbps,
                    watch_status, watch_count, last_watched_at, synopsis, synopsis_hash, metadata_refreshed_at,
                    synopsis_vector, synopsis_vector_model, synopsis_vector_dim, synopsis_vector_updated_at
                )
            )
            conn.commit()

    @staticmethod
    def get_by_normalized_title_and_year(normalized_title: str, year: int) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM library_items WHERE normalized_title = ? AND year = ?",
                (normalized_title, year)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_by_imdb_id(imdb_id: str) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM library_items WHERE imdb_id = ?",
                (imdb_id,)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def search_by_normalized_title(normalized_title: str) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            # Simple substring matching
            cursor = conn.execute(
                "SELECT * FROM library_items WHERE normalized_title LIKE ?",
                (f"%{normalized_title}%",)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def search_fts(query: str) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute(
                """
                SELECT li.* FROM library_items li
                JOIN library_items_fts fts ON li.rowid = fts.rowid
                WHERE library_items_fts MATCH ?
                """,
                (query,)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def update_enrichment(
        id: str,
        enrichment_json: str,
        setting_locations: str,
        premise_tags: str,
        character_tags: str,
        theme_tags: str,
        tone_tags: str,
        craft_tags: str,
        content_warning_tags: str,
        content_warnings_json: str,
        field_confidence_json: str,
        field_evidence_json: str,
        enrichment_version: str,
        enrichment_model: str,
        enrichment_updated_at: str,
        story_locations: str = "[]",
        filming_locations: str = "[]",
        production_countries: str = "[]",
        mentioned_locations: str = "[]",
        event_locations: str = "[]",
        central_premise_tags: str = "[]",
        subplot_tags: str = "[]",
        protagonist_tags: str = "[]",
        antagonist_tags: str = "[]",
        supporting_character_tags: str = "[]",
        central_theme_tags: str = "[]",
        minor_theme_tags: str = "[]",
        dominant_tone_tags: str = "[]",
        secondary_tone_tags: str = "[]",
        ending_tone_tags: str = "[]",
        format_tags: str = "[]",
        visual_style_tags: str = "[]",
        narrative_structure_tags: str = "[]",
        music_role_tags: str = "[]",
        depicted_content_warning_tags: str = "[]",
        discussed_content_warning_tags: str = "[]",
        award_tags: str = "[]",
        award_wins_json: str = "{}",
        award_nominations_json: str = "{}",
        acclaim_tags: str = "[]",
        source_material_tags: str = "[]",
        adaptation_type_tags: str = "[]",
        popularity_tags: str = "[]",
        cultural_impact_tags: str = "[]",
        box_office_tier: Optional[str] = None,
        hard_fact_sources_json: str = "{}",
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                UPDATE library_items
                SET enrichment_json = ?,
                    setting_locations = ?,
                    premise_tags = ?,
                    character_tags = ?,
                    theme_tags = ?,
                    tone_tags = ?,
                    craft_tags = ?,
                    content_warning_tags = ?,
                    content_warnings_json = ?,
                    field_confidence_json = ?,
                    field_evidence_json = ?,
                    enrichment_version = ?,
                    enrichment_model = ?,
                    enrichment_updated_at = ?,
                    story_locations = ?,
                    filming_locations = ?,
                    production_countries = ?,
                    mentioned_locations = ?,
                    event_locations = ?,
                    central_premise_tags = ?,
                    subplot_tags = ?,
                    protagonist_tags = ?,
                    antagonist_tags = ?,
                    supporting_character_tags = ?,
                    central_theme_tags = ?,
                    minor_theme_tags = ?,
                    dominant_tone_tags = ?,
                    secondary_tone_tags = ?,
                    ending_tone_tags = ?,
                    format_tags = ?,
                    visual_style_tags = ?,
                    narrative_structure_tags = ?,
                    music_role_tags = ?,
                    depicted_content_warning_tags = ?,
                    discussed_content_warning_tags = ?,
                    award_tags = ?,
                    award_wins_json = ?,
                    award_nominations_json = ?,
                    acclaim_tags = ?,
                    source_material_tags = ?,
                    adaptation_type_tags = ?,
                    popularity_tags = ?,
                    cultural_impact_tags = ?,
                    box_office_tier = ?,
                    hard_fact_sources_json = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    enrichment_json, setting_locations, premise_tags, character_tags,
                    theme_tags, tone_tags, craft_tags, content_warning_tags,
                    content_warnings_json, field_confidence_json, field_evidence_json,
                    enrichment_version, enrichment_model, enrichment_updated_at,
                    story_locations, filming_locations, production_countries, mentioned_locations,
                    event_locations, central_premise_tags, subplot_tags, protagonist_tags,
                    antagonist_tags, supporting_character_tags, central_theme_tags, minor_theme_tags,
                    dominant_tone_tags, secondary_tone_tags, ending_tone_tags, format_tags,
                    visual_style_tags, narrative_structure_tags, music_role_tags,
                    depicted_content_warning_tags, discussed_content_warning_tags,
                    award_tags, award_wins_json, award_nominations_json, acclaim_tags,
                    source_material_tags, adaptation_type_tags, popularity_tags,
                    cultural_impact_tags, box_office_tier, hard_fact_sources_json, id
                )
            )
            conn.commit()


class SearchResultRepository:
    @staticmethod
    def insert(
        id: str,
        query_string: str,
        indexer: str,
        title: str,
        size_bytes: Optional[int],
        seeders: Optional[int],
        magnet_uri_hash: str,
        raw_json_payload: str
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO search_results (id, query_string, indexer, title, size_bytes, seeders, magnet_uri_hash, raw_json_payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (id, query_string, indexer, title, size_bytes, seeders, magnet_uri_hash, raw_json_payload)
            )
            conn.commit()

    @staticmethod
    def get_by_id(id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM search_results WHERE id = ?", (id,))
            row = cursor.fetchone()
            return dict(row) if row else None


class DownloadJobRepository:
    @staticmethod
    def create_job(
        id: str,
        alldebrid_magnet_id: Optional[str],
        selected_file_name: Optional[str],
        target_dir: str,
        status: str
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO download_jobs (id, alldebrid_magnet_id, selected_file_name, target_dir, status, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (id, alldebrid_magnet_id, selected_file_name, target_dir, status)
            )
            conn.commit()

    @staticmethod
    def update_status(id: str, status: str) -> None:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE download_jobs SET status = ? WHERE id = ?",
                (status, id)
            )
            conn.commit()

    @staticmethod
    def update_discord_message_id(id: str, discord_message_id: Optional[str]) -> None:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE download_jobs SET discord_message_id = ? WHERE id = ?",
                (discord_message_id, id)
            )
            conn.commit()

    @staticmethod
    def get_job(id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM download_jobs WHERE id = ?", (id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def get_active_jobs() -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM download_jobs WHERE status IN ('pending', 'downloading', 'requires_selection') ORDER BY created_at DESC"
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_all_jobs(limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM download_jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def update_job_details(id: str, status: str, selected_file_name: Optional[str]) -> None:
        with get_db_connection() as conn:
            conn.execute(
                "UPDATE download_jobs SET status = ?, selected_file_name = ? WHERE id = ?",
                (status, selected_file_name, id)
            )
            conn.commit()

    @staticmethod
    def search_by_title(title: str) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "SELECT * FROM download_jobs WHERE selected_file_name LIKE ? ORDER BY created_at DESC",
                (f"%{title}%",)
            )
            return [dict(row) for row in cursor.fetchall()]


class KeyValueRepository:
    @staticmethod
    def set(key: str, value: str) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO kv_store (key, value, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (key, value)
            )
            conn.commit()

    @staticmethod
    def get(key: str, default: Optional[str] = None) -> Optional[str]:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
            row = cursor.fetchone()
            return row["value"] if row else default

    @staticmethod
    def delete(key: str) -> None:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
            conn.commit()


class ErrorLogRepository:
    @staticmethod
    def insert(
        command_name: Optional[str],
        user_id: Optional[str],
        user_name: Optional[str],
        error_message: str,
        stack_trace: str
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO errors (command_name, user_id, user_name, error_message, stack_trace)
                VALUES (?, ?, ?, ?, ?)
                """,
                (command_name, user_id, user_name, error_message, stack_trace)
            )
            conn.commit()

    @staticmethod
    def prune(max_errors: int = 500) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                DELETE FROM errors
                WHERE id NOT IN (
                    SELECT id FROM errors
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (max_errors,)
            )
            conn.commit()

    @staticmethod
    def get_all() -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM errors ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]


class EventRepository:
    @staticmethod
    def insert(
        event_type: str,
        source: str,
        title: Optional[str] = None,
        summary: Optional[str] = None,
        entity_type: Optional[str] = None,
        entity_id: Optional[str] = None,
        status: Optional[str] = None,
        severity: str = "info",
        occurred_at: Optional[str] = None,
        data_json: Optional[str] = None
    ) -> None:
        import datetime
        if not occurred_at:
            occurred_at = datetime.datetime.utcnow().isoformat()
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO events (event_type, source, title, summary, entity_type, entity_id, status, severity, occurred_at, data_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_type, source, title, summary, entity_type, entity_id, status, severity, occurred_at, data_json)
            )
            conn.commit()

    @staticmethod
    def get_all() -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM events ORDER BY created_at DESC")
            return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def get_recent(limit: int = 50) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM events ORDER BY created_at DESC LIMIT ?", (limit,))
            return [dict(row) for row in cursor.fetchall()]


