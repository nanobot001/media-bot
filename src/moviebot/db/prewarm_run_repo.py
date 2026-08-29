"""Durable lifecycle and singleton-lease state for passive pre-warm cycles."""

from __future__ import annotations

import datetime as dt
import json
import re
import uuid
from typing import Any, Dict, List, Optional

from moviebot.db.connection import get_db_connection


UTC = dt.timezone.utc
PHASE_COUNT_KEYS = (
    "reverified_count",
    "dropped_count",
    "frontier_scanned",
    "classic_tv_scanned",
    "tv_scanned",
    "movies_scanned",
    "recent_movies_scanned",
    "all_time_popular_movies_scanned",
    "cached_count",
    "cloud_cached_count",
    "catalog_discovered_count",
    "catalog_retained_count",
    "catalog_checked_count",
    "catalog_cached_count",
    "catalog_uncached_count",
    "catalog_unknown_count",
    "catalog_provider_error_count",
)


def _utc_now(value: Optional[dt.datetime] = None) -> dt.datetime:
    value = value or dt.datetime.now(UTC)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _iso(value: dt.datetime) -> str:
    return _utc_now(value).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse(value: Optional[str]) -> Optional[dt.datetime]:
    if not value:
        return None
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _utc_now(parsed)


def _safe_text(value: Optional[str], limit: int = 500) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    text = re.sub(r"magnet:\?\S+", "[redacted-magnet]", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", "[redacted-url]", text, flags=re.IGNORECASE)
    text = re.sub(r"(?:[A-Za-z]:\\|\\\\)[^\s]+", "[redacted-path]", text)
    return text[:limit]


class PrewarmRunRepository:
    """Owns the global pre-warm run ledger in the primary movies database."""

    @staticmethod
    def _decode(row: Any) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        record = dict(row)
        for source, target in (("phase_counts_json", "phase_counts"), ("stats_json", "stats")):
            raw = record.pop(source, None)
            try:
                record[target] = json.loads(raw) if raw else {}
            except (TypeError, json.JSONDecodeError):
                record[target] = {}
        return record

    @staticmethod
    def _public(record: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if record is None:
            return None
        return {
            key: value
            for key, value in record.items()
            if key not in {"runtime_id", "process_id"}
        }

    @staticmethod
    def _reconcile_stale_in_connection(conn: Any, now: dt.datetime) -> List[str]:
        now_iso = _iso(now)
        stale_ids: List[str] = []
        rows = conn.execute(
            "SELECT cycle_id, lease_expires_at FROM prewarm_runs WHERE status = 'running'"
        ).fetchall()
        for row in rows:
            expires_at = _parse(row["lease_expires_at"])
            if expires_at is None or expires_at <= now:
                cycle_id = row["cycle_id"]
                stale_ids.append(cycle_id)
                conn.execute(
                    """
                    UPDATE prewarm_runs
                    SET status = 'interrupted', finished_at = ?, next_due_at = ?,
                        stop_reason = 'lease_expired', error_code = 'PREWARM_LEASE_EXPIRED',
                        error_message = 'The owning runtime stopped renewing its lease.',
                        updated_at = ?
                    WHERE cycle_id = ? AND status = 'running'
                    """,
                    (now_iso, now_iso, now_iso, cycle_id),
                )
        if stale_ids:
            placeholders = ",".join("?" for _ in stale_ids)
            conn.execute(
                f"""
                UPDATE prewarm_runtime_state
                SET next_due_at = ?, lease_cycle_id = NULL, lease_runtime_id = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE singleton_id = 1 AND lease_cycle_id IN ({placeholders})
                """,
                (now_iso, now_iso, *stale_ids),
            )
        return stale_ids

    @classmethod
    def reconcile_stale(cls, now: Optional[dt.datetime] = None) -> List[str]:
        effective_now = _utc_now(now)
        with get_db_connection("movies") as conn:
            conn.execute("BEGIN IMMEDIATE")
            stale_ids = cls._reconcile_stale_in_connection(conn, effective_now)
            conn.commit()
        return stale_ids

    @classmethod
    def acquire(
        cls,
        *,
        trigger_source: str,
        runtime_id: str,
        process_id: int,
        interval_hours: float,
        lease_seconds: int,
        now: Optional[dt.datetime] = None,
    ) -> Dict[str, Any]:
        effective_now = _utc_now(now)
        now_iso = _iso(effective_now)
        cycle_id = uuid.uuid4().hex
        lease_expires_at = _iso(effective_now + dt.timedelta(seconds=lease_seconds))

        with get_db_connection("movies") as conn:
            conn.execute("BEGIN IMMEDIATE")
            cls._reconcile_stale_in_connection(conn, effective_now)
            conn.execute(
                """
                INSERT INTO prewarm_runs (
                    cycle_id, status, trigger_source, runtime_id, process_id,
                    scheduled_at, interval_hours, created_at, updated_at
                ) VALUES (?, 'scheduled', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    cycle_id,
                    trigger_source,
                    runtime_id,
                    process_id,
                    now_iso,
                    float(interval_hours),
                    now_iso,
                    now_iso,
                ),
            )
            active = conn.execute(
                "SELECT cycle_id FROM prewarm_runs WHERE status = 'running' LIMIT 1"
            ).fetchone()
            if active:
                active_cycle_id = active["cycle_id"]
                conn.execute(
                    """
                    UPDATE prewarm_runs
                    SET status = 'skipped', finished_at = ?, stop_reason = 'busy',
                        error_code = 'PREWARM_BUSY',
                        error_message = 'Another pre-warm cycle already owns the lease.',
                        updated_at = ?
                    WHERE cycle_id = ?
                    """,
                    (now_iso, now_iso, cycle_id),
                )
                conn.commit()
                return {
                    "accepted": False,
                    "cycle_id": cycle_id,
                    "status": "skipped",
                    "error_code": "PREWARM_BUSY",
                    "active_cycle_id": active_cycle_id,
                }

            conn.execute(
                """
                UPDATE prewarm_runs
                SET status = 'running', started_at = ?, heartbeat_at = ?,
                    lease_expires_at = ?, updated_at = ?
                WHERE cycle_id = ?
                """,
                (now_iso, now_iso, lease_expires_at, now_iso, cycle_id),
            )
            conn.execute(
                """
                INSERT INTO prewarm_runtime_state (
                    singleton_id, next_due_at, lease_cycle_id, lease_runtime_id,
                    lease_expires_at, updated_at
                ) VALUES (1, NULL, ?, ?, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    next_due_at = NULL,
                    lease_cycle_id = excluded.lease_cycle_id,
                    lease_runtime_id = excluded.lease_runtime_id,
                    lease_expires_at = excluded.lease_expires_at,
                    updated_at = excluded.updated_at
                """,
                (cycle_id, runtime_id, lease_expires_at, now_iso),
            )
            conn.commit()

        return {"accepted": True, "cycle_id": cycle_id, "status": "running"}

    @classmethod
    def heartbeat(
        cls,
        cycle_id: str,
        runtime_id: str,
        *,
        lease_seconds: int,
        now: Optional[dt.datetime] = None,
    ) -> bool:
        effective_now = _utc_now(now)
        now_iso = _iso(effective_now)
        expires_iso = _iso(effective_now + dt.timedelta(seconds=lease_seconds))
        with get_db_connection("movies") as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE prewarm_runs
                SET heartbeat_at = ?, lease_expires_at = ?, updated_at = ?
                WHERE cycle_id = ? AND runtime_id = ? AND status = 'running'
                """,
                (now_iso, expires_iso, now_iso, cycle_id, runtime_id),
            )
            if cursor.rowcount:
                conn.execute(
                    """
                    UPDATE prewarm_runtime_state
                    SET lease_expires_at = ?, updated_at = ?
                    WHERE singleton_id = 1 AND lease_cycle_id = ? AND lease_runtime_id = ?
                    """,
                    (expires_iso, now_iso, cycle_id, runtime_id),
                )
            conn.commit()
            return bool(cursor.rowcount)

    @classmethod
    def finish(
        cls,
        cycle_id: str,
        runtime_id: str,
        *,
        status: str,
        interval_hours: float,
        stats: Optional[Dict[str, Any]] = None,
        stop_reason: Optional[str] = None,
        error_code: Optional[str] = None,
        error_message: Optional[str] = None,
        now: Optional[dt.datetime] = None,
    ) -> Optional[Dict[str, Any]]:
        if status not in {"completed", "failed", "interrupted"}:
            raise ValueError(f"Unsupported terminal pre-warm status: {status}")
        effective_now = _utc_now(now)
        now_iso = _iso(effective_now)
        if status == "interrupted":
            next_due = effective_now
        else:
            next_due = effective_now + dt.timedelta(hours=float(interval_hours))
        next_due_iso = _iso(next_due)
        safe_stats = stats or {}
        phase_counts = {
            key: int(safe_stats.get(key, 0) or 0)
            for key in PHASE_COUNT_KEYS
        }
        provider_errors = int(safe_stats.get("provider_error_count", 0) or 0)

        with get_db_connection("movies") as conn:
            conn.execute("BEGIN IMMEDIATE")
            cursor = conn.execute(
                """
                UPDATE prewarm_runs
                SET status = ?, finished_at = ?, next_due_at = ?,
                    phase_counts_json = ?, provider_error_count = ?, stop_reason = ?,
                    error_code = ?, error_message = ?, stats_json = ?, updated_at = ?
                WHERE cycle_id = ? AND runtime_id = ? AND status = 'running'
                """,
                (
                    status,
                    now_iso,
                    next_due_iso,
                    json.dumps(phase_counts, sort_keys=True),
                    provider_errors,
                    _safe_text(stop_reason),
                    _safe_text(error_code, 100),
                    _safe_text(error_message),
                    json.dumps(safe_stats, sort_keys=True, default=str),
                    now_iso,
                    cycle_id,
                    runtime_id,
                ),
            )
            if cursor.rowcount:
                conn.execute(
                    """
                    INSERT INTO prewarm_runtime_state (
                        singleton_id, next_due_at, lease_cycle_id, lease_runtime_id,
                        lease_expires_at, updated_at
                    ) VALUES (1, ?, NULL, NULL, NULL, ?)
                    ON CONFLICT(singleton_id) DO UPDATE SET
                        next_due_at = excluded.next_due_at,
                        lease_cycle_id = NULL,
                        lease_runtime_id = NULL,
                        lease_expires_at = NULL,
                        updated_at = excluded.updated_at
                    WHERE prewarm_runtime_state.lease_cycle_id = ?
                       OR prewarm_runtime_state.lease_cycle_id IS NULL
                    """,
                    (next_due_iso, now_iso, cycle_id),
                )
            conn.commit()
        return cls.get(cycle_id)

    @staticmethod
    def set_next_due(next_due: dt.datetime, now: Optional[dt.datetime] = None) -> str:
        next_due_iso = _iso(next_due)
        now_iso = _iso(_utc_now(now))
        with get_db_connection("movies") as conn:
            conn.execute(
                """
                INSERT INTO prewarm_runtime_state (singleton_id, next_due_at, updated_at)
                VALUES (1, ?, ?)
                ON CONFLICT(singleton_id) DO UPDATE SET
                    next_due_at = excluded.next_due_at,
                    updated_at = excluded.updated_at
                """,
                (next_due_iso, now_iso),
            )
            conn.commit()
        return next_due_iso

    @staticmethod
    def get_runtime_state() -> Dict[str, Any]:
        with get_db_connection("movies") as conn:
            row = conn.execute(
                "SELECT * FROM prewarm_runtime_state WHERE singleton_id = 1"
            ).fetchone()
        return dict(row) if row else {}

    @classmethod
    def get(cls, cycle_id: str) -> Optional[Dict[str, Any]]:
        with get_db_connection("movies") as conn:
            row = conn.execute(
                "SELECT * FROM prewarm_runs WHERE cycle_id = ?",
                (cycle_id,),
            ).fetchone()
        return cls._decode(row)

    @classmethod
    def recent(cls, limit: int = 10, offset: int = 0) -> List[Dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        bounded_offset = max(0, int(offset))
        with get_db_connection("movies") as conn:
            rows = conn.execute(
                "SELECT * FROM prewarm_runs ORDER BY scheduled_at DESC LIMIT ? OFFSET ?",
                (bounded_limit, bounded_offset),
            ).fetchall()
        return [cls._decode(row) or {} for row in rows]

    @classmethod
    def status(cls, limit: int = 10, offset: int = 0) -> Dict[str, Any]:
        state = cls.get_runtime_state()
        runs = cls.recent(limit=limit, offset=offset)
        with get_db_connection("movies") as conn:
            active_row = conn.execute(
                "SELECT * FROM prewarm_runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            last_row = conn.execute(
                """
                SELECT * FROM prewarm_runs
                WHERE status IN ('completed', 'failed', 'interrupted')
                ORDER BY COALESCE(finished_at, scheduled_at) DESC LIMIT 1
                """
            ).fetchone()
            total_runs = int(conn.execute("SELECT COUNT(*) FROM prewarm_runs").fetchone()[0])
        active = cls._decode(active_row)
        last = cls._decode(last_row)
        last_stats = (last or {}).get("stats") or {}
        return {
            "is_prewarming": active is not None,
            "active_cycle": cls._public(active),
            "last_cycle": cls._public(last),
            "next_due_at": state.get("next_due_at"),
            "last_stats": last_stats or None,
            "recent_cycles": [cls._public(row) for row in runs],
            "cycle_history_total": total_runs,
            "cycle_history_offset": max(0, int(offset)),
        }
