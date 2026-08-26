from typing import Any, Dict, List, Optional

from moviebot.core.dedupe import normalize_title
from moviebot.db.connection import get_db_connection


class CloudTransferIntentRepository:
    """Durable user intent for AllDebrid cloud operations.

    AllDebrid's magnet status endpoint is account-wide. This repository is the
    ownership boundary that keeps background cache checks and unrelated account
    history out of Media Bot's Cloud Transfers and Notifications surfaces.
    """

    @staticmethod
    def upsert(
        transfer_id: str,
        purpose: str,
        domain: str,
        title: str,
        reference_id: str,
        release_title: str,
        year: Optional[int] = None,
        season: int = 0,
        status: str = "queued",
        ready: bool = False,
        browser_stream_ready: bool = False,
        error_message: Optional[str] = None,
    ) -> None:
        with get_db_connection() as conn:
            conn.execute(
                """
                INSERT INTO cloud_transfer_intents (
                    transfer_id, purpose, domain, title, normalized_title, year,
                    season, reference_id, release_title, status, ready,
                    browser_stream_ready, error_message, completed_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    CASE WHEN ? = 1 THEN CURRENT_TIMESTAMP ELSE NULL END,
                    CURRENT_TIMESTAMP)
                ON CONFLICT(transfer_id) DO UPDATE SET
                    purpose = excluded.purpose,
                    domain = excluded.domain,
                    title = excluded.title,
                    normalized_title = excluded.normalized_title,
                    year = excluded.year,
                    season = excluded.season,
                    reference_id = excluded.reference_id,
                    release_title = excluded.release_title,
                    status = excluded.status,
                    ready = excluded.ready,
                    browser_stream_ready = excluded.browser_stream_ready,
                    error_message = excluded.error_message,
                    completed_at = CASE
                        WHEN excluded.ready = 1 THEN COALESCE(cloud_transfer_intents.completed_at, CURRENT_TIMESTAMP)
                        ELSE cloud_transfer_intents.completed_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (
                    str(transfer_id),
                    purpose,
                    domain,
                    title,
                    normalize_title(title),
                    year,
                    season,
                    reference_id,
                    release_title,
                    status,
                    1 if ready else 0,
                    1 if browser_stream_ready else 0,
                    error_message,
                    1 if ready else 0,
                ),
            )
            conn.commit()

    @staticmethod
    def update_status(
        transfer_id: str,
        status: str,
        *,
        ready: bool = False,
        browser_stream_ready: bool = False,
        release_title: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> bool:
        with get_db_connection() as conn:
            cursor = conn.execute(
                """
                UPDATE cloud_transfer_intents
                SET status = ?,
                    ready = ?,
                    browser_stream_ready = ?,
                    release_title = COALESCE(?, release_title),
                    error_message = ?,
                    completed_at = CASE
                        WHEN ? = 1 THEN COALESCE(completed_at, CURRENT_TIMESTAMP)
                        ELSE completed_at
                    END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE transfer_id = ?
                """,
                (
                    status,
                    1 if ready else 0,
                    1 if browser_stream_ready else 0,
                    release_title,
                    error_message,
                    1 if ready else 0,
                    str(transfer_id),
                ),
            )
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def get(transfer_id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT * FROM cloud_transfer_intents WHERE transfer_id = ?",
                (str(transfer_id),),
            ).fetchone()
            return CloudTransferIntentRepository._decorate(dict(row)) if row else None

    @staticmethod
    def get_latest_for_media(
        domain: str,
        title: str,
        year: Optional[int] = None,
        season: int = 0,
        purpose: str = "browser_stream",
    ) -> Optional[Dict[str, Any]]:
        params: List[Any] = [domain, normalize_title(title), season, purpose]
        year_clause = ""
        if domain == "movies" and year:
            year_clause = "AND year = ?"
            params.append(year)
        with get_db_connection() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM cloud_transfer_intents
                WHERE domain = ? AND normalized_title = ? AND season = ?
                  AND purpose = ? {year_clause}
                ORDER BY created_at DESC
                LIMIT 1
                """,
                tuple(params),
            ).fetchone()
            return CloudTransferIntentRepository._decorate(dict(row)) if row else None

    @staticmethod
    def list_all(limit: int = 200) -> List[Dict[str, Any]]:
        with get_db_connection() as conn:
            rows = conn.execute(
                """
                SELECT * FROM cloud_transfer_intents
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [CloudTransferIntentRepository._decorate(dict(row)) for row in rows]

    @staticmethod
    def delete(transfer_id: str) -> bool:
        with get_db_connection() as conn:
            cursor = conn.execute(
                "DELETE FROM cloud_transfer_intents WHERE transfer_id = ?",
                (str(transfer_id),),
            )
            conn.commit()
            return cursor.rowcount > 0

    @staticmethod
    def _decorate(row: Dict[str, Any]) -> Dict[str, Any]:
        row["ready"] = bool(row.get("ready"))
        row["browser_stream_ready"] = bool(row.get("browser_stream_ready"))
        return row
