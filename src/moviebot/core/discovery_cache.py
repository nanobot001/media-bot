"""
High-performance In-Memory TTL Cache and Background Pre-Warming Engine for MediaBot Discovery.
"""
import time
import asyncio
import logging
from typing import Dict, Any, Optional, Tuple, List

logger = logging.getLogger(__name__)

# Primary feed cache TTL: 15 minutes (900 seconds)
FEED_CACHE_TTL = 900.0
# Deep media detail cache TTL: 1 hour (3600 seconds)
DETAIL_CACHE_TTL = 3600.0

_feed_cache: Dict[str, Tuple[float, Any]] = {}
_detail_cache: Dict[str, Tuple[float, Any]] = {}
_prewarm_task: Optional[asyncio.Task] = None


def make_feed_cache_key(
    domain: str,
    feed: str,
    genre: Optional[str] = None,
    sort_by: Optional[str] = None,
    time_range: Optional[str] = None,
    tier: Optional[str] = None,
    decade: Optional[str] = None,
    network: Optional[str] = None,
    language: Optional[str] = None,
    exclude_owned: bool = False,
    page: int = 1,
    limit: int = 48
) -> str:
    """Generates a canonical cache key for a discovery query."""
    return f"{domain}|{feed}|{genre or ''}|{sort_by or ''}|{time_range or ''}|{tier or ''}|{decade or ''}|{network or ''}|{language or ''}|{exclude_owned}|{page}|{limit}"




def get_cached_feed(cache_key: str) -> Optional[Any]:
    """Retrieves cached discovery results if within TTL."""
    now = time.time()
    if cache_key in _feed_cache:
        timestamp, data = _feed_cache[cache_key]
        if now - timestamp < FEED_CACHE_TTL:
            return data
        else:
            del _feed_cache[cache_key]
    return None


def set_cached_feed(cache_key: str, data: Any) -> None:
    """Stores discovery results in memory cache."""
    _feed_cache[cache_key] = (time.time(), data)


def get_cached_detail(domain: str, tmdb_id: int) -> Optional[Any]:
    """Retrieves deep detail metadata if within TTL."""
    key = f"{domain}:{tmdb_id}"
    now = time.time()
    if key in _detail_cache:
        timestamp, data = _detail_cache[key]
        if now - timestamp < DETAIL_CACHE_TTL:
            return data
        else:
            del _detail_cache[key]
    return None


def set_cached_detail(domain: str, tmdb_id: int, data: Any) -> None:
    """Stores deep detail metadata in memory cache."""
    key = f"{domain}:{tmdb_id}"
    _detail_cache[key] = (time.time(), data)


async def prewarm_primary_feeds():
    """
    Background worker that pre-fetches all primary feeds into memory
    on server launch and periodically to ensure sub-millisecond page loads.
    """
    from moviebot.tools.discover_media_tool import discover_media_tool

    primary_presets: List[Dict[str, Any]] = [
        # Movies Default Combos (Date Desc & 30d/60d/all)
        {"domain": "movies", "feed": "available_now", "sort_by": "date.desc", "time_range": "30d", "limit": 48},
        {"domain": "movies", "feed": "available_now", "sort_by": "date.desc", "time_range": "60d", "limit": 48},
        {"domain": "movies", "feed": "available_now", "sort_by": "date.desc", "time_range": "all", "limit": 48},
        {"domain": "movies", "feed": "available_now", "sort_by": "date.desc", "time_range": "30d", "tier": "major", "limit": 48},
        {"domain": "movies", "feed": "available_now", "sort_by": "date.desc", "time_range": "30d", "tier": "indie", "limit": 48},
        {"domain": "movies", "feed": "available_now", "limit": 48},
        {"domain": "movies", "feed": "trending", "limit": 48},
        {"domain": "movies", "feed": "popular", "limit": 48},
        {"domain": "movies", "feed": "new", "limit": 48},
        # TV Presets
        {"domain": "tv", "feed": "available_now", "sort_by": "date.desc", "time_range": "30d", "limit": 48},
        {"domain": "tv", "feed": "available_now", "sort_by": "date.desc", "time_range": "2020s", "limit": 48},
        {"domain": "tv", "feed": "available_now", "sort_by": "date.desc", "time_range": "2010s", "limit": 48},
        {"domain": "tv", "feed": "available_now", "limit": 48},
        {"domain": "tv", "feed": "trending", "limit": 48},
        {"domain": "tv", "feed": "popular", "limit": 48},
        {"domain": "tv", "feed": "new", "limit": 48},
        # Classic TV Era Presets
        {"domain": "classic_tv", "feed": "available_now", "time_range": "all", "sort_by": "popularity.desc", "limit": 48},
        {"domain": "classic_tv", "feed": "available_now", "time_range": "1990s", "sort_by": "popularity.desc", "limit": 48},
        {"domain": "classic_tv", "feed": "available_now", "time_range": "1980s", "sort_by": "popularity.desc", "limit": 48},
        {"domain": "classic_tv", "feed": "available_now", "time_range": "1970s", "sort_by": "popularity.desc", "limit": 48},
        {"domain": "classic_tv", "feed": "available_now", "time_range": "1960s", "sort_by": "popularity.desc", "limit": 48},
        {"domain": "classic_tv", "feed": "available_now", "time_range": "prior_50s", "sort_by": "popularity.desc", "limit": 48},
    ]



    logger.info("⚡ Background pre-warming primary discovery feeds into memory...")
    for preset in primary_presets:
        try:
            await discover_media_tool(**preset)
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.debug(f"Pre-warm skipped for {preset}: {e}")
    logger.info("✨ Primary discovery feeds pre-warmed successfully!")


def start_background_prewarming():
    """Starts background pre-warming task safely without blocking event loop."""
    global _prewarm_task
    try:
        loop = asyncio.get_running_loop()
        if _prewarm_task is None or _prewarm_task.done():
            _prewarm_task = loop.create_task(prewarm_primary_feeds())
    except RuntimeError:
        pass
