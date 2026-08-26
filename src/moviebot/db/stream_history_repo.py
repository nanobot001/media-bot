import logging
import re
from typing import Optional, List, Dict, Any
from moviebot.db.connection import get_db_connection

logger = logging.getLogger(__name__)


class StreamHistoryRepository:
    """
    Repository for managing streaming history, playback progress tracking,
    and cloud preview sessions in SQLite.
    """

    @staticmethod
    def _decorate_record(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Backfill a missing legacy year from the recorded release filename."""
        if not record:
            return record
        if not record.get("year"):
            match = re.search(r"\b((?:19|20)\d{2})\b", record.get("release_title") or "")
            if match:
                record["year"] = int(match.group(1))
        return record

    @staticmethod
    def upsert(
        id: str,
        domain: str,
        title: str,
        year: Optional[int] = None,
        season: int = 0,
        episode: int = 0,
        release_title: Optional[str] = None,
        stream_url: Optional[str] = None,
        duration_seconds: float = 0.0,
        progress_seconds: float = 0.0,
        progress_percent: float = 0.0,
        completed: bool = False,
        player_type: str = "web",
        poster_url: Optional[str] = None
    ) -> None:
        """Inserts or updates a streaming history record."""
        pct = progress_percent
        if not pct and duration_seconds > 0:
            pct = round((progress_seconds / duration_seconds) * 100, 1)

        comp_int = 1 if (completed or pct >= 90.0) else 0

        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO stream_history (
                    id, domain, title, year, season, episode, release_title, stream_url,
                    duration_seconds, progress_seconds, progress_percent, completed,
                    player_type, poster_url, last_streamed_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    domain = excluded.domain,
                    title = excluded.title,
                    year = excluded.year,
                    season = excluded.season,
                    episode = excluded.episode,
                    release_title = COALESCE(excluded.release_title, stream_history.release_title),
                    stream_url = COALESCE(excluded.stream_url, stream_history.stream_url),
                    duration_seconds = CASE WHEN excluded.duration_seconds > 0 THEN excluded.duration_seconds ELSE stream_history.duration_seconds END,
                    progress_seconds = excluded.progress_seconds,
                    progress_percent = excluded.progress_percent,
                    completed = CASE WHEN excluded.completed = 1 THEN 1 ELSE stream_history.completed END,
                    player_type = excluded.player_type,
                    poster_url = COALESCE(excluded.poster_url, stream_history.poster_url),
                    last_streamed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    id,
                    domain,
                    title,
                    year,
                    season,
                    episode,
                    release_title or "",
                    stream_url or "",
                    duration_seconds,
                    progress_seconds,
                    pct,
                    comp_int,
                    player_type,
                    poster_url or ""
                )
            )
            conn.commit()

    @staticmethod
    def update_progress(
        id: str,
        progress_seconds: float,
        duration_seconds: Optional[float] = None,
        completed: Optional[bool] = None
    ) -> Optional[Dict[str, Any]]:
        """Updates playback position and completion status for an active streaming session."""
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM stream_history WHERE id = ?", (id,))
            row = cursor.fetchone()
            if not row:
                return None

            dur = duration_seconds if (duration_seconds and duration_seconds > 0) else (row["duration_seconds"] or 0)
            pct = 0.0
            if dur > 0:
                pct = round((progress_seconds / dur) * 100, 1)

            is_comp = 1 if (completed is True or pct >= 90.0 or row["completed"] == 1) else 0

            conn.execute(
                """
                UPDATE stream_history
                SET progress_seconds = ?,
                    duration_seconds = ?,
                    progress_percent = ?,
                    completed = ?,
                    last_streamed_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (progress_seconds, dur, pct, is_comp, id)
            )
            conn.commit()

            cursor = conn.execute("SELECT * FROM stream_history WHERE id = ?", (id,))
            updated_row = cursor.fetchone()
            return StreamHistoryRepository._decorate_record(dict(updated_row) if updated_row else None)

    @staticmethod
    def get_recent(limit: int = 50, domain: Optional[str] = None) -> List[Dict[str, Any]]:
        """Retrieves recent streaming sessions ordered by last_streamed_at DESC."""
        conditions = []
        params = []
        if domain and domain != "all":
            db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain
            conditions.append("domain = ?")
            params.append(db_domain)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with get_db_connection() as conn:
            cursor = conn.execute(
                f"""
                SELECT * FROM stream_history
                {where_clause}
                ORDER BY last_streamed_at DESC
                LIMIT ?
                """,
                (*params, limit)
            )
            return [StreamHistoryRepository._decorate_record(dict(r)) for r in cursor.fetchall()]

    @staticmethod
    def get_by_id(id: str) -> Optional[Dict[str, Any]]:
        """Retrieves a specific stream session by ID."""
        with get_db_connection() as conn:
            cursor = conn.execute("SELECT * FROM stream_history WHERE id = ?", (id,))
            row = cursor.fetchone()
            return StreamHistoryRepository._decorate_record(dict(row) if row else None)

    @staticmethod
    def delete(id: str) -> bool:
        """Deletes a stream session from history."""
        with get_db_connection() as conn:
            cursor = conn.execute("DELETE FROM stream_history WHERE id = ?", (id,))
            conn.commit()
            return cursor.rowcount > 0
