import asyncio
import logging
import json
import time
import re
from typing import Dict, Any, List, Optional
from moviebot.tools.tmdb_fact_provider import TMDbFactProvider
from moviebot.tools.search_sources_tool import search_sources_tool
from moviebot.core.release_parser import extract_tv_spec, score_and_rank_releases
from moviebot.db.cache_prewarm_repo import CachePrewarmRepository
from moviebot.db.repositories import KeyValueRepository
from moviebot.core.dedupe import normalize_title

from moviebot.adapters.alldebrid_client import AllDebridClient

logger = logging.getLogger(__name__)

_is_prewarming = False
_last_prewarm_stats: Dict[str, Any] = {}

# Master Curated Classic TV Frontier Catalog (100+ Acclaimed & Finished Series)
MASTER_CLASSIC_TV_CATALOG: List[str] = [
    "Friends", "Frasier", "Cheers", "The Sopranos", "Breaking Bad", "The Wire",
    "The X-Files", "Seinfeld", "Chicago Hope", "NYPD Blue", "ER", "Twin Peaks",
    "The Twilight Zone", "Star Trek: The Next Generation", "Buffy the Vampire Slayer",
    "Mad Men", "Lost", "Curb Your Enthusiasm", "The West Wing", "3rd Rock from the Sun",
    "M*A*S*H", "Columbo", "Miami Vice", "The Shield", "Deadwood", "Six Feet Under",
    "The Office", "House", "Battlestar Galactica", "Dexter", "Justified", "24",
    "Stargate SG-1", "Boardwalk Empire", "Boston Legal", "Monk", "Psych", "Gilmore Girls",
    "Quantum Leap", "Babylon 5", "Fawlty Towers", "Doctor Who", "Arrested Development",
    "Parks and Recreation", "Community", "30 Rock", "The Larry Sanders Show", "NewsRadio",
    "Scrubs", "That '70s Show", "The King of Queens", "Everybody Loves Raymond",
    "Married... with Children", "Night Court", "Taxi", "Barney Miller", "All in the Family",
    "The Golden Girls", "I Love Lucy", "The Honeymooners", "The Dick Van Dyke Show",
    "The Fugitive", "The Prisoner", "Mission: Impossible", "Star Trek: Deep Space Nine",
    "Star Trek: Voyager", "Firefly", "The Americans", "Rome", "Sons of Anarchy",
    "Homeland", "The Good Wife", "Prison Break", "Person of Interest", "Fringe",
    "Supernatural", "Smallville", "Chuck", "Castle", "White Collar", "Burn Notice",
    "Suits", "Silicon Valley", "Veep", "Schitt's Creek", "Fleabag", "Blackadder",
    "Red Dwarf", "The IT Crowd", "Spaced", "Father Ted", "Peep Show", "Black Books",
    "Mr. Bean", "Luther", "Broadchurch", "Sherlock", "Fargo", "True Detective",
    "Better Call Saul", "Spartacus", "Banshee", "Hell on Wheels", "Ray Donovan"
]


async def prewarm_title(
    title: str,
    domain: str = "tv_classic",
    season: int = 0,
    vector_origin: str = "frontier"
) -> Optional[Dict[str, Any]]:
    """
    Searches indexers for the best release for a given title/season, evaluates cache status,
    and updates SQLite prewarmed_cache repository.
    """
    try:
        db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain
        raw_candidates = []
        seen_refs = set()

        if db_domain in ("tv", "tv_classic") and season == 0:
            queries = [f"{title} Complete Series", f"{title} Complete", f"{title} S01-"]
            for q in queries:
                res = await search_sources_tool(query=q, domain=db_domain, limit=15, check_cache=True)
                for r in res.get("data", {}).get("results", []):
                    ref = r.get("reference_id")
                    if ref and ref not in seen_refs:
                        seen_refs.add(ref)
                        raw_candidates.append(r)
        elif db_domain in ("tv", "tv_classic") and season > 0:
            res = await search_sources_tool(query=f"{title} S{season:02d}", domain=db_domain, limit=20, check_cache=True)
            for r in res.get("data", {}).get("results", []):
                ref = r.get("reference_id")
                if ref and ref not in seen_refs:
                    seen_refs.add(ref)
                    raw_candidates.append(r)
        else:
            # Movies
            res = await search_sources_tool(query=title, domain="movies", limit=20, check_cache=True)
            raw_candidates = res.get("data", {}).get("results", [])

        if not raw_candidates:
            return None

        target_s = None if season == 0 else season
        ranked = score_and_rank_releases(raw_candidates, target_title=title, target_season=target_s)
        valid = [r for r in ranked if not r.get("_mismatch")]

        if not valid:
            return None

        cached_list = [r for r in valid if r.get("cached")]
        winner = cached_list[0] if cached_list else valid[0]

        spec = extract_tv_spec(winner.get("title", "")) if db_domain in ("tv", "tv_classic") else {}
        is_cached = bool(winner.get("cached"))

        CachePrewarmRepository.upsert(
            domain=db_domain,
            title=title,
            season=season,
            reference_id=winner.get("reference_id", ""),
            release_title=winner.get("title", ""),
            resolution=winner.get("resolution") or spec.get("resolution") or "1080p",
            size_bytes=winner.get("size_bytes"),
            formatted_size=winner.get("formatted_size"),
            seeders=winner.get("seeders", 0),
            cached=is_cached,
            score=winner.get("_score", 0),
            data=winner,
            vector_origin=vector_origin
        )

        return {
            "title": title,
            "season": season,
            "cached": is_cached,
            "release": winner.get("title"),
            "vector_origin": vector_origin
        }
    except Exception as e:
        logger.debug("Error pre-warming title '%s' (s=%s): %s", title, season, e)
        return None


def resolve_magnet_uri(ref_id: str, domain: Optional[str] = None) -> str:
    """Resolves raw magnet link from internal reference_id / search_results row."""
    if not ref_id:
        return ""
    if ref_id.startswith("magnet:"):
        return ref_id
    from moviebot.db.repositories import SearchResultRepository
    sr = SearchResultRepository.get_by_id(ref_id, domain=domain)
    if sr and sr.get("raw_json_payload"):
        try:
            raw = json.loads(sr["raw_json_payload"])
            dl = raw.get("downloadUrl") or raw.get("guid") or ""
            if dl.startswith("magnet:"):
                return dl
            if raw.get("infoHash"):
                return f"magnet:?xt=urn:btih:{raw['infoHash']}"
            if dl:
                return dl
        except Exception:
            pass
    return ref_id


async def batch_reverify_existing() -> Dict[str, int]:
    """
    Phase 1: Sub-second AllDebrid RAM check of all existing tracked records.
    Resolves real magnet URIs and infohashes, batching in safe 15-hash chunks.
    """
    records = CachePrewarmRepository.get_all_for_reverification()
    if not records:
        return {"verified": 0, "cached": 0, "dropped": 0}

    ad_client = AllDebridClient()
    updates = []

    # Resolve magnets and clean infohashes
    resolved_records = []
    for r in records:
        real_mag = resolve_magnet_uri(r.get("reference_id", ""), domain=r.get("domain"))
        clean_hash = ""
        if real_mag:
            match = re.search(r'btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})', real_mag, re.IGNORECASE)
            if match:
                clean_hash = match.group(1).lower()
        resolved_records.append((r, real_mag, clean_hash))

    # Safe batch size of 15 hashes per HTTP GET to stay within URL length limits
    chunk_size = 15
    for i in range(0, len(resolved_records), chunk_size):
        chunk = resolved_records[i:i + chunk_size]
        hashes_to_query = [h for _, _, h in chunk if h]

        if not hashes_to_query:
            continue

        try:
            res = await ad_client.instant_check(hashes_to_query)
            magnets_res = res.get("magnets", [])
            status_map = {}
            for m in magnets_res:
                if isinstance(m, dict):
                    hash_key = (m.get("hash") or "").lower()
                    mag_key = (m.get("magnet") or "").lower()
                    is_ready = bool(m.get("ready") or m.get("instant"))
                    if hash_key:
                        status_map[hash_key] = is_ready
                    if mag_key:
                        status_map[mag_key] = is_ready

            for rec, real_mag, clean_h in chunk:
                if not clean_h:
                    # Skip unresolvable mock/dummy references without dropping them
                    continue

                is_ready = status_map.get(clean_h, False)
                if not is_ready and real_mag:
                    is_ready = status_map.get(real_mag.lower(), False)

                updates.append({
                    "id": rec["id"],
                    "cached": is_ready,
                    "was_cached": bool(rec.get("cached"))
                })
        except Exception as e:
            logger.debug("[Pre-Warmer] Batch reverify error for chunk: %s", e)

    return CachePrewarmRepository.batch_update_cache_status(updates)


def get_progressive_frontier_candidates(limit: int = 8) -> List[Dict[str, Any]]:
    """
    Selects candidates across all 4 automated progressive expansion vectors:
    - Vector 4: Plex Active Watch-History Priority (Pushes currently watched shows to #1).
    - Vector 1: Multi-Season Progression for existing cached series (S01 -> S02 -> S03...).
    - Vector 2: Master Classic Catalog & Infinite TMDb Ended TV crawl.
    """
    candidates: List[Dict[str, Any]] = []
    existing_items = CachePrewarmRepository.get_items(domain="tv_classic", status="all", limit=1000)
    
    # Map: normalized_title -> set of tracked seasons
    tracked_seasons_map: Dict[str, Set[int]] = {}
    cached_seasons_map: Dict[str, Set[int]] = {}
    for it in existing_items:
        norm = normalize_title(it["title"])
        if norm not in tracked_seasons_map:
            tracked_seasons_map[norm] = set()
            cached_seasons_map[norm] = set()
        tracked_seasons_map[norm].add(it["season"])
        if it["cached"]:
            cached_seasons_map[norm].add(it["season"])

    # Vector 4: Plex Watch History Priority (Check recently watched TV shows from events)
    try:
        with get_db_connection() as conn:
            c = conn.cursor()
            c.execute("""
                SELECT title, data_json FROM events
                WHERE event_type LIKE '%playback%' OR event_type LIKE '%watch%' OR event_type LIKE '%tautulli%'
                ORDER BY id DESC LIMIT 10
            """)
            for row in c.fetchall():
                show_title = row["title"]
                if show_title:
                    norm = normalize_title(show_title)
                    tracked = tracked_seasons_map.get(norm, set())
                    # Check next season
                    for s in range(1, 10):
                        if s not in tracked:
                            if not any(cand["title"].lower() == show_title.lower() and cand["season"] == s for cand in candidates):
                                candidates.append({
                                    "title": show_title,
                                    "domain": "tv",
                                    "season": s,
                                    "type": "plex_watch_priority"
                                })
                                break
    except Exception as e:
        logger.debug("[Pre-Warmer] Vector 4 watch history check error: %s", e)

    # Vector 1: Multi-Season Progression Walker (if S1 is cached, queue S2, then S3...)
    for it in existing_items:
        if it["cached"] and it["season"] > 0:
            norm = normalize_title(it["title"])
            next_season = it["season"] + 1
            if next_season <= 10 and next_season not in tracked_seasons_map.get(norm, set()):
                if not any(c["title"] == it["title"] and c["season"] == next_season for c in candidates):
                    candidates.append({
                        "title": it["title"],
                        "domain": "tv_classic",
                        "season": next_season,
                        "type": "season_progression"
                    })
                    if len(candidates) >= limit:
                        return candidates

    # Vector 2: Master Curated Classic Pool
    for title in MASTER_CLASSIC_TV_CATALOG:
        norm = normalize_title(title)
        tracked = tracked_seasons_map.get(norm, set())
        # If Complete Run (0) not checked
        if 0 not in tracked:
            candidates.append({"title": title, "domain": "tv_classic", "season": 0, "type": "frontier_boxset"})
            if len(candidates) >= limit:
                return candidates
        # If Season 1 not checked
        if 1 not in tracked:
            candidates.append({"title": title, "domain": "tv_classic", "season": 1, "type": "frontier_s1"})
            if len(candidates) >= limit:
                return candidates

    # Vector 2 (Infinite Fallback): Query TMDb Ended / Classic TV if master list exhausted
    try:
        provider = TMDbFactProvider()
        tmdb_ended = provider.discover_tv({
            "with_status": "3|4",
            "vote_count.gte": 40,
            "sort_by": "popularity.desc",
            "page": 2
        })
        for item in tmdb_ended.get("results", []):
            t_name = item.get("name") or item.get("original_name")
            if t_name:
                norm = normalize_title(t_name)
                tracked = tracked_seasons_map.get(norm, set())
                if 1 not in tracked:
                    candidates.append({"title": t_name, "domain": "tv_classic", "season": 1, "type": "infinite_tmdb_classic"})
                    if len(candidates) >= limit:
                        return candidates
    except Exception as e:
        logger.debug("[Pre-Warmer] Vector 2 Infinite TMDb fallback error: %s", e)

    return candidates


async def run_cache_prewarm_cycle(force: bool = False) -> Dict[str, Any]:
    """
    Executes a complete progressive frontier background pre-warming pass:
    - Phase 1: Rapid 200ms batch re-verification of all known records (detects dropped RAM items).
    - Phase 2 & 3: Multi-season walker & 6-8 new Classic TV frontier targets.
    - Phase 4: Top trending TV and Movies.
    """
    global _is_prewarming, _last_prewarm_stats
    if _is_prewarming and not force:
        return {"ok": False, "message": "Pre-warming cycle is already currently running."}

    _is_prewarming = True
    start_time = time.time()
    logger.info("⚡ [Pre-Warmer] Starting Progressive Frontier cache pre-warm cycle...")

    stats = {
        "ok": True,
        "reverified_count": 0,
        "dropped_count": 0,
        "frontier_scanned": 0,
        "cached_count": 0,
        "classic_tv_scanned": 0,
        "tv_scanned": 0,
        "movies_scanned": 0,
        "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_time)),
    }

    try:
        # Phase 1: Sub-second batch re-verification of known cache
        reverify_res = await batch_reverify_existing()
        stats["reverified_count"] = reverify_res.get("verified", 0)
        stats["dropped_count"] = reverify_res.get("dropped", 0)
        logger.info("⚡ [Pre-Warmer] Phase 1 Re-verified %s items (%s newly dropped from RAM)",
                    stats["reverified_count"], stats["dropped_count"])

        # Phase 2 & 3: Progressive Frontier Candidates
        scanned_titles_summary = []
        frontier_targets = get_progressive_frontier_candidates(limit=8)
        for target in frontier_targets:
            v_type = target.get("type", "frontier")
            res = await prewarm_title(
                target["title"],
                domain=target["domain"],
                season=target["season"],
                vector_origin=v_type
            )
            stats["frontier_scanned"] += 1
            stats["classic_tv_scanned"] += 1
            is_c = bool(res and res.get("cached"))
            if is_c:
                stats["cached_count"] += 1
            s_label = f"S{target['season']}" if target['season'] > 0 else "Complete"
            scanned_titles_summary.append(f"{target['title']} ({s_label}) {'⚡' if is_c else '⏳'}")
            await asyncio.sleep(2.5)

        # Phase 4: Modern TV & Movies (Trending + Top Rated Acclaimed)
        provider = TMDbFactProvider()
        try:
            trending_tv = provider.get_trending_tv(page=1)
            tv_results = trending_tv.get("results", []) if trending_tv else []
            for t in tv_results[:6]:
                t_name = t.get("name") or t.get("original_name")
                if t_name:
                    res_tv = await prewarm_title(t_name, domain="tv", season=1, vector_origin="tv_trending")
                    stats["tv_scanned"] += 1
                    is_c = bool(res_tv and res_tv.get("cached"))
                    if is_c:
                        stats["cached_count"] += 1
                    scanned_titles_summary.append(f"{t_name} (S01) {'⚡' if is_c else '⏳'}")
                    await asyncio.sleep(2.5)
        except Exception as e:
            logger.debug("[Pre-Warmer] Modern TV TMDb fetch error: %s", e)

        try:
            # Combine popular and top-rated movies for broad library coverage
            popular_movies = provider.get_popular_movies(page=1)
            top_movies = provider.get_top_rated_movies(page=1) if hasattr(provider, "get_top_rated_movies") else {}
            
            combined_movies = []
            if popular_movies and "results" in popular_movies:
                combined_movies.extend(popular_movies["results"])
            if top_movies and "results" in top_movies:
                combined_movies.extend(top_movies["results"])

            seen_m = set()
            for m in combined_movies[:10]:
                m_title = m.get("title")
                if m_title and m_title.lower() not in seen_m:
                    seen_m.add(m_title.lower())
                    res_m = await prewarm_title(m_title, domain="movies", season=0, vector_origin="movie_popular")
                    stats["movies_scanned"] += 1
                    is_c = bool(res_m and res_m.get("cached"))
                    if is_c:
                        stats["cached_count"] += 1
                    scanned_titles_summary.append(f"{m_title} (Movie) {'⚡' if is_c else '⏳'}")
                    await asyncio.sleep(2.5)
        except Exception as e:
            logger.debug("[Pre-Warmer] Movies TMDb fetch error: %s", e)

        scoreboard = CachePrewarmRepository.get_scoreboard_stats()
        elapsed = round(time.time() - start_time, 1)
        stats["elapsed_seconds"] = elapsed
        stats["scanned_titles"] = scanned_titles_summary
        stats["scoreboard"] = scoreboard
        stats["message"] = (f"Re-verified {stats['reverified_count']} existing ({stats['dropped_count']} dropped) | "
                            f"Scanned {stats['frontier_scanned'] + stats['tv_scanned'] + stats['movies_scanned']} frontier targets ({stats['cached_count']} cached) in {elapsed}s")
        logger.info("✨ [Pre-Warmer] Finished: %s", stats["message"])
        _last_prewarm_stats = stats

        # Record Domain Event
        try:
            from moviebot.db.repositories import EventRepository
            EventRepository.record(
                event_type="cache_prewarm_cycle_completed",
                title="⚡ Cache Pre-warm Pass Completed",
                data={
                    "reverified": stats["reverified_count"],
                    "dropped": stats["dropped_count"],
                    "scanned": len(scanned_titles_summary),
                    "cached_new": stats["cached_count"],
                    "elapsed_s": elapsed,
                    "sample_targets": scanned_titles_summary[:6]
                }
            )
        except Exception as e:
            logger.debug("[Pre-Warmer] Could not record domain event: %s", e)

        return stats
    finally:
        _is_prewarming = False


async def start_background_prewarm_loop():
    """
    Periodic background loop that runs cache pre-warming on a polite interval.
    """
    await asyncio.sleep(60)  # Wait 60s for server startup and library sync to fully settle

    while True:
        try:
            # Check user settings
            stored_str = KeyValueRepository.get("user_settings")
            user_settings = {}
            if stored_str:
                try:
                    user_settings = json.loads(stored_str)
                except Exception:
                    pass

            enabled = user_settings.get("background_prewarm_enabled", True)
            interval_hours = float(user_settings.get("prewarm_interval_hours", 6.0))

            if enabled:
                await run_cache_prewarm_cycle()

            # Sleep for interval hours
            await asyncio.sleep(interval_hours * 3600)
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error("[Pre-Warmer] Error in background pre-warm loop: %s", e)
            await asyncio.sleep(3600)


def get_prewarm_status() -> Dict[str, Any]:
    """Returns current pre-warmer loop status and last cycle telemetry."""
    global _is_prewarming, _last_prewarm_stats
    return {
        "is_prewarming": _is_prewarming,
        "last_stats": _last_prewarm_stats
    }
