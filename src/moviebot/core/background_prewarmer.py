import asyncio
import logging
import json
import time
import re
import datetime
from typing import Dict, Any, List, Optional, Set
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

# Movie queues are intentionally separated so recent usefulness is not blocked
# by a long-tail historical crawl. The old classic/current keys are retained
# as aliases for callers that imported them, but their persisted state is now
# interpreted using the new queue semantics.
MOVIE_RECENT_CURSOR_KEY = "prewarm:movies:recent_cursor_v2"
MOVIE_ALL_TIME_POPULAR_CURSOR_KEY = "prewarm:movies:all_time_popular_cursor_v2"
MOVIE_RECENT_END_YEAR = 1980
MOVIE_RECENT_MIN_VOTES = 25
MOVIE_ALL_TIME_MIN_VOTES = 1000
MOVIE_MAX_DISCOVER_PAGES = 500

# Backwards-compatible names for internal/test callers from the first queue
# implementation. They no longer represent an oldest-first 1920 frontier.
MOVIE_CLASSIC_CURSOR_KEY = MOVIE_RECENT_CURSOR_KEY
MOVIE_CURRENT_CURSOR_KEY = MOVIE_ALL_TIME_POPULAR_CURSOR_KEY


def _movie_year(item: Dict[str, Any]) -> Optional[int]:
    """Extract a release year from a TMDb movie result without guessing."""
    raw_date = item.get("release_date") or ""
    if len(raw_date) >= 4 and raw_date[:4].isdigit():
        return int(raw_date[:4])
    raw_year = item.get("year")
    try:
        return int(raw_year) if raw_year else None
    except (TypeError, ValueError):
        return None


def _load_cursor(key: str, default: Dict[str, int]) -> Dict[str, int]:
    raw = KeyValueRepository.get(key)
    if not raw:
        return dict(default)
    try:
        value = json.loads(raw)
        return {k: int(value.get(k, v)) for k, v in default.items()}
    except (TypeError, ValueError, json.JSONDecodeError):
        return dict(default)


def _save_cursor(key: str, value: Dict[str, int]) -> None:
    KeyValueRepository.set(key, json.dumps(value, sort_keys=True))

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
    year: Optional[int] = None,
    vector_origin: str = "frontier",
    tmdb_id: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    """
    Searches indexers for the best release for a given title/season, evaluates cache status,
    and updates SQLite prewarmed_cache repository.
    """
    try:
        db_domain = "tv_classic" if domain in ("tv_classic", "classic_tv") else domain
        raw_candidates = []
        seen_refs = set()
        movie_eligibility = None

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
            res = await search_sources_tool(
                query=title,
                domain="movies",
                year=year,
                tmdb_id=tmdb_id,
                limit=20,
                check_cache=True,
            )
            movie_eligibility = res.get("data", {}).get("eligibility")
            raw_candidates = res.get("data", {}).get("results", [])

        if movie_eligibility and not movie_eligibility.get("eligible"):
            return {
                "title": title,
                "year": year,
                "cached": False,
                "cloud_cached": False,
                "instant_download_ready": False,
                "instant_cached": False,
                "browser_stream_ready": False,
                "quality_gate": movie_eligibility,
                "vector_origin": vector_origin,
            }

        if not raw_candidates:
            return None

        target_s = None if season == 0 else season
        ranked = score_and_rank_releases(
            raw_candidates,
            target_title=title,
            target_year=year if db_domain == "movies" else None,
            target_season=target_s,
        )
        valid = [r for r in ranked if not r.get("_mismatch")]

        if not valid:
            return None

        cached_list = [r for r in valid if r.get("cached")]
        # Keep the best cached release as the download candidate.  A passive
        # pre-warm search may record download availability, but it cannot
        # promote an indexer title to browser readiness without provider-file
        # verification.
        winner = cached_list[0] if cached_list else valid[0]

        spec = extract_tv_spec(winner.get("title", "")) if db_domain in ("tv", "tv_classic") else {}
        is_cached = bool(winner.get("cached"))

        CachePrewarmRepository.upsert(
            domain=db_domain,
            title=title,
            season=season,
            year=year if db_domain == "movies" else None,
            reference_id=winner.get("reference_id", ""),
            release_title=winner.get("title", ""),
            resolution=winner.get("resolution") or spec.get("resolution") or "1080p",
            size_bytes=winner.get("size_bytes"),
            formatted_size=winner.get("formatted_size"),
            seeders=winner.get("seeders", 0),
            cached=is_cached,
            score=winner.get("_score", 0),
            data=winner,
            vector_origin=vector_origin,
        )

        stored = CachePrewarmRepository.get(
            db_domain,
            title,
            season=season,
            year=year if db_domain == "movies" else None,
            max_age_hours=168,
        ) or {}
        browser_stream_ready = bool(stored.get("browser_stream_ready"))
        return {
            "title": title,
            "season": season,
            "year": year,
            "cached": is_cached,
            "cloud_cached": is_cached,
            "instant_download_ready": is_cached,
            "instant_cached": browser_stream_ready,
            "browser_stream_ready": browser_stream_ready,
            "browser_stream_reference_id": stored.get("browser_stream_reference_id"),
            "browser_stream_release_title": stored.get("browser_stream_release_title"),
            "download_reference_id": winner.get("reference_id") if is_cached else None,
            "download_release_title": winner.get("title") if is_cached else None,
            "release": winner.get("title"),
            "quality_gate": movie_eligibility,
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
    browser_updates = []

    # Resolve magnets and clean infohashes
    resolved_records = []
    for r in records:
        real_mag = resolve_magnet_uri(r.get("reference_id", ""), domain=r.get("domain"))
        clean_hash = ""
        if real_mag:
            match = re.search(r'btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})', real_mag, re.IGNORECASE)
            if match:
                clean_hash = match.group(1).lower()
        stream_mag = resolve_magnet_uri(
            r.get("browser_stream_reference_id", ""),
            domain=r.get("domain"),
        )
        stream_hash = ""
        if stream_mag:
            stream_match = re.search(
                r'btih:([a-fA-F0-9]{40}|[a-zA-Z2-7]{32})',
                stream_mag,
                re.IGNORECASE,
            )
            if stream_match:
                stream_hash = stream_match.group(1).lower()
        resolved_records.append((r, real_mag, clean_hash, stream_mag, stream_hash))

    # Safe batch size of 15 hashes per HTTP GET to stay within URL length limits
    chunk_size = 15
    for i in range(0, len(resolved_records), chunk_size):
        chunk = resolved_records[i:i + chunk_size]
        hashes_to_query = []
        for _, _, clean_h, _, stream_h in chunk:
            for hash_value in (clean_h, stream_h):
                if hash_value and hash_value not in hashes_to_query:
                    hashes_to_query.append(hash_value)

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

            for rec, real_mag, clean_h, stream_mag, stream_h in chunk:
                if not clean_h and not stream_h:
                    # Skip unresolvable mock/dummy references without dropping them
                    continue

                if clean_h:
                    is_ready = status_map.get(clean_h, False)
                    if not is_ready and real_mag:
                        is_ready = status_map.get(real_mag.lower(), False)

                    updates.append({
                        "id": rec["id"],
                        "cached": is_ready,
                        "was_cached": bool(rec.get("cached"))
                    })

                if stream_h:
                    stream_ready = status_map.get(stream_h, False)
                    if not stream_ready and stream_mag:
                        stream_ready = status_map.get(stream_mag.lower(), False)
                    browser_updates.append((rec["id"], stream_ready))
        except Exception as e:
            logger.debug("[Pre-Warmer] Batch reverify error for chunk: %s", e)

    result = CachePrewarmRepository.batch_update_cache_status(updates)
    for row_id, stream_ready in browser_updates:
        CachePrewarmRepository.update_browser_stream_status(row_id, stream_ready)
    return result


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


def _recent_movie_cursor_default() -> Dict[str, int]:
    return {
        "year": max(MOVIE_RECENT_END_YEAR, datetime.date.today().year),
        "page": 1,
        "item_index": 0,
    }


def get_recent_movie_frontier_candidates(
    limit: int = 5,
    provider: Optional[TMDbFactProvider] = None,
) -> List[Dict[str, Any]]:
    """Return popular movies from the current year down through 1980.

    The cursor is year-descending, then page/item-resumable. Current releases
    therefore receive the first chance to become instant-stream candidates,
    while the 1980s remain the historical floor for this queue.
    """
    provider = provider or TMDbFactProvider()
    cursor = _load_cursor(
        MOVIE_RECENT_CURSOR_KEY,
        _recent_movie_cursor_default(),
    )
    today = datetime.date.today()

    while cursor["year"] >= MOVIE_RECENT_END_YEAR:
        year = cursor["year"]
        end_date = today.isoformat() if year == today.year else f"{year}-12-31"
        response = provider.discover_movies({
            "primary_release_date.gte": f"{year}-01-01",
            "primary_release_date.lte": end_date,
            "vote_count.gte": MOVIE_RECENT_MIN_VOTES,
            "sort_by": "popularity.desc",
            "page": max(1, cursor["page"]),
        }) or {}
        results = response.get("results", []) or []

        ordered = sorted(
            [
                item for item in results
                if item.get("title") or item.get("original_title")
            ],
            key=lambda item: (
                -(float(item.get("popularity") or 0.0)),
                -(int(item.get("vote_count") or 0)),
                item.get("title") or item.get("original_title") or "",
            ),
        )
        if cursor["item_index"] < len(ordered):
            candidates = []
            for item in ordered[cursor["item_index"]:]:
                title = item.get("title") or item.get("original_title")
                item_year = _movie_year(item)
                if not title or not item_year:
                    continue
                candidates.append({
                    "title": title,
                    "year": item_year,
                    "tmdb_id": item.get("id"),
                    "type": "movie_recent",
                })
                if len(candidates) >= limit:
                    break
            return candidates

        total_pages = int(response.get("total_pages") or 1)
        if results and cursor["page"] < total_pages:
            cursor["page"] += 1
        else:
            cursor["year"] -= 1
            cursor["page"] = 1
        cursor["item_index"] = 0
        _save_cursor(MOVIE_RECENT_CURSOR_KEY, cursor)

    return []


def advance_recent_movie_frontier(consumed_count: int) -> None:
    """Advance the recent movie cursor after a bounded batch is processed."""
    if consumed_count <= 0:
        return
    cursor = _load_cursor(
        MOVIE_RECENT_CURSOR_KEY,
        _recent_movie_cursor_default(),
    )
    cursor["item_index"] += consumed_count
    _save_cursor(MOVIE_RECENT_CURSOR_KEY, cursor)


def get_all_time_popular_movie_frontier_candidates(
    limit: int = 5,
    provider: Optional[TMDbFactProvider] = None,
) -> List[Dict[str, Any]]:
    """Return a resumable TMDB all-time popularity batch.

    This intentionally has no release-date window. TMDB's popularity sort
    supplies the broad all-time ranking, while the vote floor prevents a
    short-lived or sparsely rated item from displacing a widely recognized
    movie in the long-term cache frontier.
    """
    provider = provider or TMDbFactProvider()
    cursor = _load_cursor(
        MOVIE_ALL_TIME_POPULAR_CURSOR_KEY,
        {"page": 1, "item_index": 0},
    )
    page = max(1, cursor["page"])
    response = provider.discover_movies({
        "vote_count.gte": MOVIE_ALL_TIME_MIN_VOTES,
        "sort_by": "popularity.desc",
        "page": page,
    }) or {}
    results = response.get("results", []) or []
    ordered = sorted(
        [
            item for item in results
            if (item.get("title") or item.get("original_title")) and _movie_year(item)
        ],
        key=lambda item: (
            -(float(item.get("popularity") or 0.0)),
            -(int(item.get("vote_count") or 0)),
            item.get("title") or item.get("original_title") or "",
        ),
    )
    candidates = []
    for item in ordered[cursor["item_index"]:]:
        candidates.append({
            "title": item.get("title") or item.get("original_title"),
            "year": _movie_year(item),
            "tmdb_id": item.get("id"),
            "type": "movie_all_time_popular",
        })
        if len(candidates) >= limit:
            break
    return candidates


def advance_all_time_popular_movie_frontier(
    consumed_count: int = 0,
    provider: Optional[TMDbFactProvider] = None,
) -> None:
    """Move the all-time popularity cursor forward and wrap at its frontier."""
    if consumed_count < 0:
        return
    provider = provider or TMDbFactProvider()
    cursor = _load_cursor(
        MOVIE_ALL_TIME_POPULAR_CURSOR_KEY,
        {"page": 1, "item_index": 0},
    )
    page = max(1, cursor["page"])
    response = provider.discover_movies({
        "vote_count.gte": MOVIE_ALL_TIME_MIN_VOTES,
        "sort_by": "popularity.desc",
        "page": page,
    }) or {}
    if consumed_count:
        results = response.get("results", []) or []
        ordered_count = len([
            item for item in results
            if (item.get("title") or item.get("original_title")) and _movie_year(item)
        ])
        cursor["item_index"] += consumed_count
        if cursor["item_index"] < ordered_count:
            _save_cursor(MOVIE_ALL_TIME_POPULAR_CURSOR_KEY, cursor)
            return
    total_pages = max(
        1,
        min(int(response.get("total_pages") or 1), MOVIE_MAX_DISCOVER_PAGES),
    )
    if response.get("results") and page < total_pages:
        cursor["page"] = page + 1
    else:
        cursor["page"] = 1
    cursor["item_index"] = 0
    _save_cursor(MOVIE_ALL_TIME_POPULAR_CURSOR_KEY, cursor)


# Compatibility wrappers for code that used the first queue names. The
# persisted behavior is intentionally the new recent/all-time strategy.
def get_classic_movie_frontier_candidates(
    limit: int = 5,
    provider: Optional[TMDbFactProvider] = None,
) -> List[Dict[str, Any]]:
    return get_recent_movie_frontier_candidates(limit=limit, provider=provider)


def advance_classic_movie_frontier(consumed_count: int) -> None:
    advance_recent_movie_frontier(consumed_count)


def get_current_movie_frontier_candidates(
    limit: int = 5,
    provider: Optional[TMDbFactProvider] = None,
) -> List[Dict[str, Any]]:
    return get_all_time_popular_movie_frontier_candidates(limit=limit, provider=provider)


def advance_current_movie_frontier(provider: Optional[TMDbFactProvider] = None) -> None:
    # ``provider`` remains accepted for compatibility with the first queue.
    advance_all_time_popular_movie_frontier(provider=provider)


async def run_cache_prewarm_cycle(force: bool = False) -> Dict[str, Any]:
    """
    Executes a complete progressive frontier background pre-warming pass:
    - Phase 1: Rapid 200ms batch re-verification of all known records (detects dropped RAM items).
    - Phase 2 & 3: Multi-season walker & 6-8 new Classic TV frontier targets.
    - Phase 4: Top trending TV plus recent-to-1980 and all-time popular movie queues.
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
        "cloud_cached_count": 0,
        "classic_tv_scanned": 0,
        "tv_scanned": 0,
        "movies_scanned": 0,
        "recent_movies_scanned": 0,
        "all_time_popular_movies_scanned": 0,
        # Retained as aliases for existing dashboards/event consumers.
        "classic_movies_scanned": 0,
        "popular_movies_scanned": 0,
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
            is_c = bool(res and res.get("cloud_cached", res.get("cached")))
            is_instant = bool(res and res.get("instant_cached", res.get("browser_stream_ready")))
            if is_c:
                stats["cloud_cached_count"] += 1
            if is_instant:
                stats["cached_count"] += 1
            s_label = f"S{target['season']}" if target['season'] > 0 else "Complete"
            marker = "⚡" if is_instant else ("☁️" if is_c else "⏳")
            scanned_titles_summary.append(f"{target['title']} ({s_label}) {marker}")
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
                    is_c = bool(res_tv and res_tv.get("cloud_cached", res_tv.get("cached")))
                    is_instant = bool(res_tv and res_tv.get("instant_cached", res_tv.get("browser_stream_ready")))
                    if is_c:
                        stats["cloud_cached_count"] += 1
                    if is_instant:
                        stats["cached_count"] += 1
                    marker = "⚡" if is_instant else ("☁️" if is_c else "⏳")
                    scanned_titles_summary.append(f"{t_name} (S01) {marker}")
                    await asyncio.sleep(2.5)
        except Exception as e:
            logger.debug("[Pre-Warmer] Modern TV TMDb fetch error: %s", e)

        try:
            # Recent queue: current release year down through 1980, resumed from SQLite KV state.
            recent_targets = get_recent_movie_frontier_candidates(limit=5, provider=provider)
            for target in recent_targets:
                res_m = await prewarm_title(
                    target["title"],
                    domain="movies",
                    season=0,
                    year=target["year"],
                    tmdb_id=target.get("tmdb_id"),
                    vector_origin="movie_recent",
                )
                stats["movies_scanned"] += 1
                stats["recent_movies_scanned"] += 1
                stats["classic_movies_scanned"] = stats["recent_movies_scanned"]
                is_c = bool(res_m and res_m.get("cloud_cached", res_m.get("cached")))
                is_instant = bool(res_m and res_m.get("instant_cached", res_m.get("browser_stream_ready")))
                if is_c:
                    stats["cloud_cached_count"] += 1
                if is_instant:
                    stats["cached_count"] += 1
                marker = "⚡" if is_instant else ("☁️" if is_c else "⏳")
                scanned_titles_summary.append(f"{target['title']} ({target['year']}) {marker}")
                await asyncio.sleep(2.5)
            advance_recent_movie_frontier(len(recent_targets))

            # All-time queue: TMDB popularity across all release years, resumed independently.
            all_time_targets = get_all_time_popular_movie_frontier_candidates(limit=5, provider=provider)
            for target in all_time_targets:
                res_m = await prewarm_title(
                    target["title"],
                    domain="movies",
                    season=0,
                    year=target["year"],
                    tmdb_id=target.get("tmdb_id"),
                    vector_origin="movie_all_time_popular",
                )
                stats["movies_scanned"] += 1
                stats["all_time_popular_movies_scanned"] += 1
                stats["popular_movies_scanned"] = stats["all_time_popular_movies_scanned"]
                is_c = bool(res_m and res_m.get("cloud_cached", res_m.get("cached")))
                is_instant = bool(res_m and res_m.get("instant_cached", res_m.get("browser_stream_ready")))
                if is_c:
                    stats["cloud_cached_count"] += 1
                if is_instant:
                    stats["cached_count"] += 1
                marker = "⚡" if is_instant else ("☁️" if is_c else "⏳")
                scanned_titles_summary.append(f"{target['title']} ({target['year']}) {marker}")
                await asyncio.sleep(2.5)
            if all_time_targets:
                advance_all_time_popular_movie_frontier(
                    consumed_count=len(all_time_targets),
                    provider=provider,
                )
        except Exception as e:
            logger.debug("[Pre-Warmer] Movies TMDb fetch error: %s", e)

        scoreboard = CachePrewarmRepository.get_scoreboard_stats()
        elapsed = round(time.time() - start_time, 1)
        stats["elapsed_seconds"] = elapsed
        stats["scanned_titles"] = scanned_titles_summary
        stats["scoreboard"] = scoreboard
        stats["message"] = (f"Re-verified {stats['reverified_count']} existing ({stats['dropped_count']} dropped) | "
                            f"Scanned {stats['frontier_scanned'] + stats['tv_scanned'] + stats['movies_scanned']} frontier targets ({stats['cached_count']} browser streams, {stats['cloud_cached_count']} cloud-cached) in {elapsed}s")
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
                    "cloud_cached": stats["cloud_cached_count"],
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
