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
        size_bytes: Optional[int]
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO library_items (id, source, rating_key, title, normalized_title, year, imdb_id, file_path, size_bytes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    source=excluded.source,
                    rating_key=excluded.rating_key,
                    title=excluded.title,
                    normalized_title=excluded.normalized_title,
                    year=excluded.year,
                    imdb_id=excluded.imdb_id,
                    file_path=excluded.file_path,
                    size_bytes=excluded.size_bytes,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (id, source, rating_key, title, normalized_title, year, imdb_id, file_path, size_bytes)
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
    def get_job(id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM download_jobs WHERE id = ?", (id,))
            row = cursor.fetchone()
            return dict(row) if row else None


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
