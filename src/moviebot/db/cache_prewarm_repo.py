import json
import logging
from typing import Dict, Any, List, Optional
from moviebot.db.connection import get_db_connection
from moviebot.core.dedupe import normalize_title

logger = logging.getLogger(__name__)


class CachePrewarmRepository:
    """
    Repository for storing and retrieving pre-warmed release candidates and AllDebrid cache states.
    Includes scoreboard tracking, progressive frontier management, and dropped RAM cache detection.
    """

    @staticmethod
    def upsert(
        domain: str,
        title: str,
        season: int,
        reference_id: str,
        release_title: str,
        resolution: Optional[str] = None,
        size_bytes: Optional[int] = None,
        formatted_size: Optional[str] = None,
        seeders: int = 0,
        cached: bool = False,
        score: int = 0,
        data: Optional[Dict[str, Any]] = None,
        vector_origin: str = "frontier"
    ) -> None:
        norm = normalize_title(title)
        row_id = f"{domain}:{norm}:{season}"
        data_json = json.dumps(data) if data else None
        cached_int = 1 if cached else 0

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                INSERT INTO prewarmed_cache (
                    id, domain, title, normalized_title, season, reference_id,
                    release_title, resolution, size_bytes, formatted_size,
                    seeders, cached, previously_cached, dropped_at, vector_origin, score, data_json, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    reference_id=excluded.reference_id,
                    release_title=excluded.release_title,
                    resolution=excluded.resolution,
                    size_bytes=excluded.size_bytes,
                    formatted_size=excluded.formatted_size,
                    seeders=excluded.seeders,
                    cached=excluded.cached,
                    previously_cached=CASE WHEN excluded.cached = 1 THEN 1 ELSE prewarmed_cache.previously_cached END,
                    dropped_at=CASE
                        WHEN excluded.cached = 0 AND prewarmed_cache.cached = 1 THEN CURRENT_TIMESTAMP
                        WHEN excluded.cached = 1 THEN NULL
                        ELSE prewarmed_cache.dropped_at
                    END,
                    vector_origin=COALESCE(excluded.vector_origin, prewarmed_cache.vector_origin),
                    score=excluded.score,
                    data_json=excluded.data_json,
                    updated_at=CURRENT_TIMESTAMP
            """, (
                row_id, domain, title, norm, season, reference_id,
                release_title, resolution, size_bytes, formatted_size,
                seeders, cached_int, cached_int, vector_origin, score, data_json
            ))

    @staticmethod
    def get(domain: str, title: str, season: int = 0, max_age_hours: int = 168) -> Optional[Dict[str, Any]]:
        norm = normalize_title(title)
        row_id = f"{domain}:{norm}:{season}"
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT domain, title, season, reference_id, release_title, resolution,
                       size_bytes, formatted_size, seeders, cached, previously_cached, dropped_at,
                       score, data_json, updated_at,
                       (strftime('%s', 'now') - strftime('%s', updated_at)) / 3600.0 as age_hours
                FROM prewarmed_cache
                WHERE id = ?
            """, (row_id,))
            row = c.fetchone()
            if not row:
                return None
            if row["age_hours"] > max_age_hours:
                return None

            data_obj = {}
            if row["data_json"]:
                try:
                    data_obj = json.loads(row["data_json"])
                except Exception:
                    pass

            return {
                "domain": row["domain"],
                "title": row["title"],
                "season": row["season"],
                "reference_id": row["reference_id"],
                "release_title": row["release_title"],
                "resolution": row["resolution"],
                "size_bytes": row["size_bytes"],
                "formatted_size": row["formatted_size"],
                "seeders": row["seeders"],
                "cached": bool(row["cached"]),
                "previously_cached": bool(row["previously_cached"]),
                "dropped_at": row["dropped_at"],
                "score": row["score"],
                "data": data_obj,
                "updated_at": row["updated_at"]
            }

    @staticmethod
    def get_all_for_reverification() -> List[Dict[str, Any]]:
        """Returns all tracked records that have a magnet/reference_id for batch instant check."""
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT id, domain, title, season, reference_id, cached, previously_cached
                FROM prewarmed_cache
                WHERE reference_id IS NOT NULL AND reference_id != ''
            """)
            return [dict(r) for r in c.fetchall()]

    @staticmethod
    def batch_update_cache_status(status_updates: List[Dict[str, Any]]) -> Dict[str, int]:
        """
        Applies batch cache re-verification results in a single transaction.
        Tracks newly dropped items and refreshes active items.
        """
        if not status_updates:
            return {"verified": 0, "cached": 0, "dropped": 0}

        verified_count = 0
        cached_count = 0
        dropped_count = 0

        with get_db_connection() as conn:
            c = conn.cursor()
            for item in status_updates:
                row_id = item["id"]
                is_cached = item["cached"]
                was_cached = item.get("was_cached", False)

                if is_cached:
                    cached_count += 1
                    c.execute("""
                        UPDATE prewarmed_cache
                        SET cached = 1,
                            previously_cached = 1,
                            dropped_at = NULL,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                    """, (row_id,))
                else:
                    if was_cached:
                        dropped_count += 1
                        c.execute("""
                            UPDATE prewarmed_cache
                            SET cached = 0,
                                previously_cached = 1,
                                dropped_at = CURRENT_TIMESTAMP,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (row_id,))
                    else:
                        c.execute("""
                            UPDATE prewarmed_cache
                            SET cached = 0,
                                updated_at = CURRENT_TIMESTAMP
                            WHERE id = ?
                        """, (row_id,))
                verified_count += 1

            conn.commit()

        return {
            "verified": verified_count,
            "cached": cached_count,
            "dropped": dropped_count
        }

    @staticmethod
    def get_items(
        domain: str = "all",
        status: str = "all",
        limit: int = 100
    ) -> List[Dict[str, Any]]:
        """
        Retrieves pre-warmed cache records with domain and status filtering.
        Statuses: 'all', 'cached', 'dropped', 'p2p'.
        """
        conditions = []
        params = []

        if domain and domain != "all":
            db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain
            conditions.append("domain = ?")
            params.append(db_domain)

        if status == "cached":
            conditions.append("cached = 1")
        elif status == "dropped":
            conditions.append("cached = 0 AND previously_cached = 1")
        elif status == "p2p":
            conditions.append("cached = 0 AND previously_cached = 0")

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(f"""
                SELECT id, domain, title, season, reference_id, release_title, resolution,
                       size_bytes, formatted_size, seeders, cached, previously_cached, dropped_at,
                       vector_origin, score, data_json, updated_at
                FROM prewarmed_cache
                {where_clause}
                ORDER BY cached DESC, updated_at DESC
                LIMIT ?
            """, (*params, limit))

            out = []
            for r in c.fetchall():
                out.append({
                    "id": r["id"],
                    "domain": r["domain"],
                    "title": r["title"],
                    "season": r["season"],
                    "reference_id": r["reference_id"],
                    "release_title": r["release_title"],
                    "resolution": r["resolution"],
                    "size_bytes": r["size_bytes"],
                    "formatted_size": r["formatted_size"],
                    "seeders": r["seeders"],
                    "cached": bool(r["cached"]),
                    "previously_cached": bool(r["previously_cached"]),
                    "dropped": bool(not r["cached"] and r["previously_cached"]),
                    "dropped_at": r["dropped_at"],
                    "vector_origin": r["vector_origin"] or "frontier",
                    "score": r["score"],
                    "updated_at": r["updated_at"]
                })
            return out

    @staticmethod
    def get_scoreboard_stats(domain: str = "all", catalog_total: Optional[int] = None) -> Dict[str, Any]:
        """Calculates real-time scoreboard metrics globally or filtered by selected domain."""
        conditions = []
        params = []

        if domain and domain != "all":
            db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain
            conditions.append("domain = ?")
            params.append(db_domain)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Default catalog goals: Movies (40), TV (30), Classic TV (100), All (170)
        if catalog_total is None:
            if domain == "movies":
                catalog_total = 40
            elif domain == "tv":
                catalog_total = 30
            elif domain in ("tv_classic", "classic_tv"):
                catalog_total = 100
            else:
                catalog_total = 170

        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute(f"""
                SELECT
                    COUNT(*) as total_tracked,
                    SUM(CASE WHEN cached = 1 THEN 1 ELSE 0 END) as instant_cached,
                    SUM(CASE WHEN cached = 0 AND previously_cached = 1 THEN 1 ELSE 0 END) as dropped_count,
                    SUM(CASE WHEN cached = 0 AND previously_cached = 0 THEN 1 ELSE 0 END) as p2p_only,
                    MAX(updated_at) as last_updated
                FROM prewarmed_cache
                {where_clause}
            """, tuple(params))
            row = c.fetchone()
            total_tracked = row["total_tracked"] or 0
            instant_cached = row["instant_cached"] or 0
            dropped_count = row["dropped_count"] or 0
            p2p_only = row["p2p_only"] or 0
            last_updated = row["last_updated"]

            # Dynamic Tiered Milestone Leveling
            tier_milestones = {
                "movies": [40, 100, 250, 500, 1000],
                "tv": [30, 75, 150, 300, 600],
                "tv_classic": [100, 250, 500, 1000, 2000],
                "all": [170, 425, 900, 1800, 3600]
            }
            domain_key = "tv_classic" if domain in ("tv_classic", "classic_tv") else (domain or "all")
            tiers = tier_milestones.get(domain_key, tier_milestones["all"])

            tier_level = 1
            if catalog_total is not None:
                effective_catalog_total = catalog_total
            else:
                effective_catalog_total = tiers[0]
                for lvl, target_val in enumerate(tiers, start=1):
                    tier_level = lvl
                    effective_catalog_total = target_val
                    if instant_cached < target_val:
                        break

            c.execute("""
                SELECT domain,
                       COUNT(*) as total,
                       SUM(CASE WHEN cached = 1 THEN 1 ELSE 0 END) as cached,
                       SUM(CASE WHEN cached = 0 AND previously_cached = 1 THEN 1 ELSE 0 END) as dropped
                FROM prewarmed_cache
                GROUP BY domain
            """)
            by_domain = {}
            for r in c.fetchall():
                by_domain[r["domain"]] = {
                    "total": r["total"],
                    "cached": r["cached"] or 0,
                    "dropped": r["dropped"] or 0
                }

            c.execute("""
                SELECT COALESCE(vector_origin, 'frontier') as v_origin, COUNT(*) as cnt
                FROM prewarmed_cache
                GROUP BY vector_origin
            """)
            vector_breakdown = {}
            for r in c.fetchall():
                vector_breakdown[r["v_origin"]] = r["cnt"]

            frontier_to_go = max(0, effective_catalog_total - total_tracked)
            progress_pct = round((instant_cached / max(1, effective_catalog_total)) * 100, 1)

            return {
                "domain": domain,
                "tier_level": tier_level,
                "total_tracked": total_tracked,
                "total_entries": total_tracked,
                "instant_cached": instant_cached,
                "total_cached": instant_cached,
                "dropped_count": dropped_count,
                "p2p_only": p2p_only,
                "frontier_to_go": frontier_to_go,
                "catalog_total": effective_catalog_total,
                "progress_percent": progress_pct,
                "last_updated": last_updated,
                "by_domain": by_domain,
                "vector_breakdown": vector_breakdown
            }

    @staticmethod
    def get_stats() -> Dict[str, Any]:
        """Backwards-compatible alias for scoreboard stats."""
        return CachePrewarmRepository.get_scoreboard_stats()

    @staticmethod
    def prune_expired(max_age_days: int = 7) -> int:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                DELETE FROM prewarmed_cache
                WHERE (strftime('%s', 'now') - strftime('%s', updated_at)) / 86400.0 > ?
            """, (max_age_days,))
            return c.rowcount
