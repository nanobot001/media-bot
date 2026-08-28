import asyncio
import datetime
import logging
import re
from typing import Dict, Any, List, Optional
from moviebot.tools.tmdb_fact_provider import TMDbFactProvider
from moviebot.tools.media_tier_classifier import classify_media_tier
from moviebot.core.discovery_cache import make_feed_cache_key, get_cached_feed, set_cached_feed
from moviebot.db.repositories import LibraryItemRepository, TVLibraryRepository


from moviebot.config import settings
from moviebot.core.dedupe import normalize_title
from moviebot.core.movie_quality_gate import evaluate_movie_eligibility

logger = logging.getLogger(__name__)


# Genre mappings for movies and TV
MOVIE_GENRES: Dict[str, int] = {
    "action": 28,
    "adventure": 12,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "fantasy": 14,
    "history": 36,
    "horror": 27,
    "music": 10402,
    "mystery": 9648,
    "romance": 10749,
    "science fiction": 878,
    "sci-fi": 878,
    "tv movie": 10770,
    "thriller": 53,
    "war": 10752,
    "western": 37,
}

TV_GENRES: Dict[str, Any] = {
    "action": 10759,
    "action & adventure": 10759,
    "adventure": 10759,
    "animation": 16,
    "cartoons": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "kids": 10762,
    "children": 10762,
    "kids & family": 10762,
    "mystery": 9648,

    "news": 10763,
    "reality": 10764,
    "science fiction": 10765,
    "sci-fi": 10765,
    "sci-fi & fantasy": 10765,
    "fantasy": 10765,
    "soap": 10766,
    "talk": 10767,
    "war & politics": 10768,
    "war": 10768,
    "western": 37,
}


MOVIE_GENRE_NAMES: Dict[int, str] = {v: k.title() for k, v in MOVIE_GENRES.items() if k != "sci-fi"}
TV_GENRE_NAMES: Dict[int, str] = {v: k.title() for k, v in TV_GENRES.items() if k not in ("sci-fi", "action", "adventure", "fantasy", "war")}

MAJOR_TV_NETWORKS = "213|49|2552|1024|2739|453|88|174|6|16|2|19|67|4330|3353|14|4|332|71|318"

NETWORK_IDS: Dict[str, str] = {
    "major": MAJOR_TV_NETWORKS,
    "major_networks": MAJOR_TV_NETWORKS,
    "streamers": "213|2552|1024|2739|453|4330|3353",
    "broadcast": "2|6|16|19|71|14",
    "premium": "49|67|318|88|174",
    "abc": "2",
    "nbc": "6",
    "cbs": "16",
    "fox": "19",
    "hbo": "49",
    "max": "49",
    "bbc": "4|332|100",
    "bbc one": "4",
    "bbc two": "332",
    "pbs": "14",
    "amc": "174",
    "showtime": "67",
    "apple": "2552",
    "apple tv": "2552",
    "apple tv+": "2552",
    "amazon": "1024",
    "prime": "1024",
    "amazon prime": "1024",
    "disney": "2739",
    "disney+": "2739",
    "hulu": "453",
    "paramount": "4330",
    "paramount+": "4330",
    "peacock": "3353",
    "fx": "88",
    "amc": "174",
    "showtime": "67",
    "starz": "318",
    "nbc": "6",
    "cbs": "16",
    "abc": "2",
    "fox": "19",
    "the cw": "71",
    "cw": "71",
    "pbs": "14",
    "bbc": "4",
    "bbc one": "4",
    "bbc two": "332",
}


DECADE_RANGES: Dict[str, tuple[str, str]] = {
    "prior_50s": ("1900-01-01", "1959-12-31"),
    "50s": ("1950-01-01", "1959-12-31"),
    "1950s": ("1950-01-01", "1959-12-31"),
    "60s": ("1960-01-01", "1969-12-31"),
    "1960s": ("1960-01-01", "1969-12-31"),
    "70s": ("1970-01-01", "1979-12-31"),
    "1970s": ("1970-01-01", "1979-12-31"),
    "80s": ("1980-01-01", "1989-12-31"),
    "1980s": ("1980-01-01", "1989-12-31"),
    "90s": ("1990-01-01", "1999-12-31"),
    "1990s": ("1990-01-01", "1999-12-31"),
    "00s": ("2000-01-01", "2009-12-31"),
    "2000s": ("2000-01-01", "2009-12-31"),
    "10s": ("2010-01-01", "2019-12-31"),
    "2010s": ("2010-01-01", "2019-12-31"),
    "20s": ("2020-01-01", "2025-12-31"),
    "2020s": ("2020-01-01", "2025-12-31"),
}



def _resolve_genre_id(genre_str: str, is_tv: bool) -> Optional[Any]:
    if not genre_str:
        return None
    cleaned = genre_str.strip().lower()
    mapping = TV_GENRES if is_tv else MOVIE_GENRES
    if cleaned in mapping:
        val = mapping[cleaned]
        if isinstance(val, int):
            return val
        if isinstance(val, str) and val.isdigit():
            return int(val)
        return val
    if cleaned.isdigit():
        return int(cleaned)
    return None



def _resolve_network_id(network_str: str) -> Optional[str]:
    if not network_str:
        return None
    cleaned = network_str.strip().lower()
    if cleaned in NETWORK_IDS:
        return NETWORK_IDS[cleaned]
    return network_str.strip()


def _resolve_date_range(
    year_range: Optional[str] = None,
    decade: Optional[str] = None,
    time_range: Optional[str] = None,
    default_max_date: Optional[str] = None,
    offset_days: int = 0
) -> tuple[Optional[str], Optional[str]]:
    start_date = None
    end_date = None

    if time_range:
        tr = time_range.strip().lower()
        if tr in DECADE_RANGES:
            return DECADE_RANGES[tr]
        today = datetime.date.today()
        anchor_date = today - datetime.timedelta(days=offset_days)
        if tr == "30d":
            start_date, end_date = (anchor_date - datetime.timedelta(days=30)).isoformat(), anchor_date.isoformat()
        elif tr == "60d":
            start_date, end_date = (anchor_date - datetime.timedelta(days=60)).isoformat(), anchor_date.isoformat()
        elif tr == "90d":
            start_date, end_date = (anchor_date - datetime.timedelta(days=90)).isoformat(), anchor_date.isoformat()
        elif tr == "6m":
            start_date, end_date = (anchor_date - datetime.timedelta(days=180)).isoformat(), anchor_date.isoformat()
        elif tr == "1y":
            start_date, end_date = (anchor_date - datetime.timedelta(days=365)).isoformat(), anchor_date.isoformat()
        elif tr in ("all", "all_time"):
            start_date = None
            end_date = anchor_date.isoformat() if offset_days > 0 else None


    if not start_date and decade:
        dec_key = decade.strip().lower()
        if dec_key in DECADE_RANGES:
            start_date, end_date = DECADE_RANGES[dec_key]

    if not start_date and year_range:
        parts = year_range.split("-")
        if len(parts) == 2 and parts[0].strip().isdigit() and parts[1].strip().isdigit():
            start_date = f"{parts[0].strip()}-01-01"
            end_date = f"{parts[1].strip()}-12-31"
        elif len(parts) == 1 and parts[0].strip().isdigit():
            start_date = f"{parts[0].strip()}-01-01"
            end_date = f"{parts[0].strip()}-12-31"

    if not end_date and default_max_date:
        end_date = default_max_date

    return start_date, end_date




import time
from moviebot.db.connection import get_db_connection

_owned_cache: Dict[str, Any] = {}

def _get_owned_sets(domain: str, force_refresh: bool = False) -> tuple:
    """Returns cached (tmdb_id_set, title_set) for the domain with 60s TTL."""
    now = time.time()
    db_path = getattr(settings, f"{domain}_database_path", "") or getattr(settings, "database_path", "")
    cache_key = f"{domain}:{db_path}"
    if not force_refresh and cache_key in _owned_cache:
        ts, ids, titles = _owned_cache[cache_key]
        if now - ts < 60.0:
            return ids, titles

    ids = set()
    titles = set()
    try:
        if domain in ("tv", "tv_classic"):
            shows = TVLibraryRepository.get_all_shows(domain=domain)
            for s in shows:
                if s.get("tmdb_id"):
                    ids.add(s["tmdb_id"])
                if s.get("normalized_title"):
                    titles.add((s["normalized_title"], s.get("year")))
                    titles.add((s["normalized_title"], None))
        else:
            with get_db_connection() as conn:
                c = conn.cursor()
                c.execute("SELECT tmdb_id, title, normalized_title, year FROM library_items")
                for r in c.fetchall():
                    if r[0]:
                        ids.add(r[0])
                    for alias in _ownership_title_aliases(r[1] or r[2] or ""):
                        titles.add((alias, r[3]))
                        titles.add((alias, None))
        _owned_cache[cache_key] = (now, ids, titles)
    except Exception as e:
        logger.debug("Error loading owned sets: %s", e)

    return ids, titles


def _ownership_title_aliases(title: str) -> set[str]:
    """Return conservative aliases for Plex subtitle/prefix title variants."""
    raw_title = (title or "").strip()
    aliases = {normalize_title(raw_title)} if raw_title else set()
    parts = re.split(r"\s*:\s*|\s+[\u2013\u2014-]\s+", raw_title)
    if len(parts) > 1:
        suffix = normalize_title(parts[-1])
        # Avoid treating very short generic words as a distinct movie title.
        if len(suffix) >= 8:
            aliases.add(suffix)
    return {alias for alias in aliases if alias}


def _check_owned_fast(
    tmdb_id: Optional[int],
    title: str,
    year: Optional[int],
    owned_ids: set,
    owned_titles: set
) -> bool:
    if tmdb_id and tmdb_id in owned_ids:
        return True
    if title:
        norm = normalize_title(title)
        if (norm, year) in owned_titles or (norm, None) in owned_titles:
            return True
    return False


def _refresh_cached_ownership(
    payload: Dict[str, Any],
    db_domain: str,
    exclude_owned: bool,
) -> Dict[str, Any]:
    """Refresh ownership flags without rebuilding the cached TMDb feed."""
    if not isinstance(payload.get("data"), dict):
        return payload

    data = dict(payload["data"])
    owned_ids, owned_titles = _get_owned_sets(db_domain, force_refresh=True)
    refreshed_results = []
    for item in data.get("results", []):
        refreshed = dict(item)
        is_owned = _check_owned_fast(
            refreshed.get("tmdb_id") or refreshed.get("id"),
            refreshed.get("title") or refreshed.get("name") or "",
            refreshed.get("year"),
            owned_ids,
            owned_titles,
        )
        refreshed["owned"] = is_owned
        refreshed["in_library"] = is_owned
        if not (exclude_owned and is_owned):
            refreshed_results.append(refreshed)
    data["results"] = refreshed_results
    data["total_results"] = len(refreshed_results)
    refreshed_payload = dict(payload)
    refreshed_payload["data"] = data
    return refreshed_payload


def _refresh_cached_movie_quality(
    payload: Dict[str, Any],
    feed: str,
    provider: TMDbFactProvider,
) -> Dict[str, Any]:
    """Reapply the current movie gate to short-lived discovery cache entries."""
    if not isinstance(payload.get("data"), dict):
        return payload

    data = dict(payload["data"])
    refreshed_results = []
    for item in data.get("results", []):
        refreshed = dict(item)
        title = refreshed.get("title") or ""
        decision = evaluate_movie_eligibility(
            title=title,
            year=refreshed.get("year"),
            tmdb_id=refreshed.get("tmdb_id"),
            authoritative_release_date=refreshed.get("release_date"),
            provider=provider,
        )
        refreshed["quality_gate"] = decision
        refreshed["available_now"] = bool(decision.get("eligible"))
        if feed in ("available_now", "digital") and not decision.get("eligible"):
            continue
        refreshed_results.append(refreshed)
    data["results"] = refreshed_results
    data["total_results"] = len(refreshed_results)
    refreshed_payload = dict(payload)
    refreshed_payload["data"] = data
    return refreshed_payload


def _check_owned(
    tmdb_id: Optional[int],
    title: str,
    year: Optional[int],
    db_domain: str
) -> bool:
    owned_ids, owned_titles = _get_owned_sets(db_domain)
    return _check_owned_fast(tmdb_id, title, year, owned_ids, owned_titles)




def is_show_or_episode_owned(
    title: str,
    year: Optional[int] = None,
    season_number: Optional[int] = None,
    episode_number: Optional[int] = None,
    tmdb_id: Optional[int] = None,
    imdb_id: Optional[str] = None,
    domain: str = "movies"
) -> bool:
    """
    Canonical deduplication helper checking whether a movie, TV show, or specific TV episode
    is already present in the local database.
    """
    domain_norm = (domain or "movies").strip().lower()
    if domain_norm in ("tv", "classic_tv", "tv_classic"):
        target_domain = "tv_classic" if domain_norm in ("classic_tv", "tv_classic") else "tv"
        if season_number is not None and episode_number is not None:
            return TVLibraryRepository.is_episode_owned(
                show_title=title,
                year=year,
                season_number=season_number,
                episode_number=episode_number,
                tmdb_id=tmdb_id,
                domain=target_domain
            )
        return TVLibraryRepository.is_show_owned(
            tmdb_id=tmdb_id,
            title=title,
            year=year,
            imdb_id=imdb_id,
            domain=target_domain
        )
    else:
        return _check_owned(tmdb_id=tmdb_id, title=title, year=year, db_domain="movies")



async def discover_media_tool(
    domain: str = "movies",
    feed: str = "trending",
    genre: Optional[str] = None,
    sort_by: Optional[str] = None,
    time_range: Optional[str] = None,
    tier: Optional[str] = None,
    min_rating: Optional[float] = None,
    year_range: Optional[str] = None,
    decade: Optional[str] = None,
    language: Optional[str] = None,
    network: Optional[str] = None,
    studio: Optional[str] = None,
    exclude_owned: bool = False,
    time_window: str = "week",
    page: int = 1,
    limit: int = 24,
    tmdb_provider: Optional[TMDbFactProvider] = None,
) -> Dict[str, Any]:

    """
    Unified domain-parameterized media discovery tool.
    Fetches trending, popular, digital releases, and top rated titles from TMDb for Movies, TV, and Classic TV,
    with filtering, sorting, pagination, and local library deduplication.
    """
    tool_name = "discover_media_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    domain_normalized = (domain or "movies").strip().lower()
    if domain_normalized in ("tv_classic", "classic_tv", "classictv"):
        domain_normalized = "classic_tv"

    if domain_normalized not in ("movies", "tv", "classic_tv"):
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "INVALID_DOMAIN",
                "message": f"Unsupported media domain '{domain}'. Must be one of: 'movies', 'tv', 'classic_tv', 'tv_classic'.",
                "retryable": False,
                "severity": "error",
            }
        }

    feed_normalized = (feed or "available_now").strip().lower()
    if feed_normalized not in ("available_now", "trending", "popular", "digital", "top_rated", "airing", "new"):
        feed_normalized = "available_now"

    db_domain = "tv_classic" if domain_normalized in ("classic_tv", "tv_classic") else domain_normalized

    cache_key = make_feed_cache_key(
        domain=domain_normalized,
        feed=feed_normalized,
        genre=genre,
        sort_by=sort_by,
        time_range=time_range,
        tier=tier,
        decade=decade,
        network=network,
        language=language,
        exclude_owned=exclude_owned,
        page=page,
        limit=limit
    )

    provider = tmdb_provider or TMDbFactProvider()

    cached_payload = get_cached_feed(cache_key)
    if cached_payload is not None:
        refreshed = _refresh_cached_ownership(cached_payload, db_domain, exclude_owned)
        if domain_normalized == "movies":
            return _refresh_cached_movie_quality(refreshed, feed_normalized, provider)
        return refreshed


    is_tv = domain_normalized in ("tv", "classic_tv", "tv_classic")
    is_classic_tv = domain_normalized in ("classic_tv", "tv_classic")

    try:
        # Determine if we can use the direct trending endpoint or if filters require discover
        has_custom_filters = bool(
            page > 1 or sort_by or time_range or genre or min_rating or year_range or decade or network or studio or is_classic_tv or (language and language != "en")
        )


        raw_results: List[Dict[str, Any]] = []

        if is_tv:
            # TV & Classic TV Logic
            if feed_normalized == "trending" and not has_custom_filters:

                start_page = max(1, page)
                pages_to_fetch = 3 if (limit > 20 or tier) else 2
                fetch_tasks = [
                    asyncio.to_thread(provider.get_trending_tv, time_window=time_window, page=p)
                    for p in range(start_page, start_page + pages_to_fetch)
                ]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for t_data in pages:
                    if isinstance(t_data, dict):
                        raw_results.extend(t_data.get("results", []))
            elif feed_normalized == "popular" and not has_custom_filters:
                start_page = max(1, page)
                pages_to_fetch = 3 if (limit > 20 or tier) else 2
                fetch_tasks = [
                    asyncio.to_thread(provider.get_popular_tv, page=p)
                    for p in range(start_page, start_page + pages_to_fetch)
                ]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for p_data in pages:
                    if isinstance(p_data, dict):
                        raw_results.extend(p_data.get("results", []))
            else:
                discover_params: Dict[str, Any] = {
                    "language": language,
                    "include_adult": False,
                }
                if is_classic_tv:
                    last_year_end = f"{datetime.date.today().year - 1}-12-31"
                    discover_params["first_air_date.lte"] = last_year_end
                    discover_params["with_status"] = "3|4"
                    discover_params["sort_by"] = "popularity.desc"
                    discover_params["vote_count.gte"] = 10
                else:
                    # Modern TV: Strictly active, returning, or in-production series
                    discover_params["with_status"] = "0|1|2"
                    if feed_normalized in ("available_now", "digital"):
                        today_str = datetime.date.today().isoformat()
                        discover_params["first_air_date.lte"] = today_str
                        discover_params["sort_by"] = "popularity.desc"
                        discover_params["vote_count.gte"] = 10
                    elif feed_normalized == "new":
                        today_str = datetime.date.today().isoformat()
                        discover_params["first_air_date.lte"] = today_str
                        discover_params["sort_by"] = "first_air_date.desc"
                        discover_params["vote_count.gte"] = 5
                    elif feed_normalized in ("popular", "trending"):
                        discover_params["sort_by"] = "popularity.desc"
                    elif feed_normalized == "top_rated":
                        discover_params["sort_by"] = "vote_average.desc"
                        discover_params["vote_count.gte"] = 50


                offset = 0
                time_range_effective = None if (is_classic_tv and time_range in ("30d", "60d", "90d", "6m", "1y")) else time_range
                start_date, end_date = _resolve_date_range(year_range, decade, time_range_effective, None, offset_days=offset)
                if start_date:
                    if is_tv and not is_classic_tv and feed_normalized != "new" and not decade and not year_range:
                        discover_params["air_date.gte"] = start_date
                    else:
                        discover_params["first_air_date.gte"] = start_date
                if end_date:
                    last_year_end = f"{datetime.date.today().year - 1}-12-31"
                    if not is_classic_tv or end_date <= last_year_end:
                        if is_tv and not is_classic_tv and feed_normalized != "new" and not decade and not year_range:
                            discover_params["air_date.lte"] = end_date
                        else:
                            discover_params["first_air_date.lte"] = end_date






                if language:
                    lang_clean = language.strip().lower()
                    if lang_clean in ("en_us", "en-us", "us"):
                        discover_params["with_origin_country"] = "US"
                        discover_params["with_original_language"] = "en"
                    elif lang_clean in ("en_gb", "en-gb", "gb", "uk"):
                        discover_params["with_origin_country"] = "GB"
                        discover_params["with_original_language"] = "en"
                    elif lang_clean in ("en_ca", "en-ca", "ca"):
                        discover_params["with_origin_country"] = "CA"
                        discover_params["with_original_language"] = "en"
                    elif lang_clean in ("en_au", "en-au", "au"):
                        discover_params["with_origin_country"] = "AU"
                        discover_params["with_original_language"] = "en"
                    elif lang_clean not in ("all", "any", ""):
                        discover_params["with_original_language"] = lang_clean


                if genre:
                    gid = _resolve_genre_id(genre, is_tv=True)
                    if gid:
                        discover_params["with_genres"] = str(gid)

                if min_rating is not None and min_rating > 0:
                    discover_params["vote_average.gte"] = str(min_rating)
                    discover_params["vote_count.gte"] = discover_params.get("vote_count.gte", 10)


                if tier:
                    t_norm = tier.strip().lower()
                    if t_norm in ("major", "major_networks", "blockbuster", "studio"):
                        discover_params["with_networks"] = MAJOR_TV_NETWORKS
                    elif t_norm in ("streamers", "streaming"):
                        discover_params["with_networks"] = "213|2552|1024|2739|453|4330|3353"
                    elif t_norm in ("broadcast", "network"):
                        discover_params["with_networks"] = "2|6|16|19|71|14"
                    elif t_norm in ("premium", "cable"):
                        discover_params["with_networks"] = "49|67|318|88|174"

                if network:
                    nid = _resolve_network_id(network)
                    if nid:
                        discover_params["with_networks"] = nid


                if sort_by:
                    s_norm = sort_by.strip().lower()
                    if s_norm in ("date.desc", "date", "newest"):
                        discover_params["sort_by"] = "first_air_date.desc"
                        today_str = datetime.date.today().isoformat()
                        if not discover_params.get("first_air_date.lte"):
                            discover_params["first_air_date.lte"] = today_str
                        discover_params["vote_count.gte"] = max(discover_params.get("vote_count.gte", 0), 5)
                    elif s_norm in ("popularity.desc", "popularity", "popular"):
                        discover_params["sort_by"] = "popularity.desc"
                    elif s_norm in ("rating.desc", "rating", "vote_average.desc", "top_rated"):
                        discover_params["sort_by"] = "vote_average.desc"
                        discover_params["vote_count.gte"] = max(discover_params.get("vote_count.gte", 0), 100)
                    elif s_norm in ("votes.desc", "vote_count.desc"):
                        discover_params["sort_by"] = "vote_count.desc"
                        discover_params["vote_count.gte"] = max(discover_params.get("vote_count.gte", 0), 100)

                # Parallel multi-page fetching
                start_page = max(1, page)
                pages_to_fetch = 3 if (limit > 20 or tier) else 2
                fetch_tasks = [
                    asyncio.to_thread(provider.discover_tv, {**discover_params, "page": p})
                    for p in range(start_page, start_page + pages_to_fetch)
                ]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for d_page in pages:
                    if isinstance(d_page, dict):
                        raw_results.extend(d_page.get("results", []))

        else:
            # Movie Logic
            if feed_normalized == "trending" and not has_custom_filters:
                start_page = max(1, page)
                pages_to_fetch = 3 if (limit > 20 or tier) else 2
                fetch_tasks = [
                    asyncio.to_thread(provider.get_trending_movies, time_window=time_window, page=p)
                    for p in range(start_page, start_page + pages_to_fetch)
                ]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for t_data in pages:
                    if isinstance(t_data, dict):
                        raw_results.extend(t_data.get("results", []))
            elif feed_normalized == "popular" and not has_custom_filters:
                start_page = max(1, page)
                pages_to_fetch = 3 if (limit > 20 or tier) else 2
                fetch_tasks = [
                    asyncio.to_thread(provider.get_popular_movies, page=p)
                    for p in range(start_page, start_page + pages_to_fetch)
                ]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for p_data in pages:
                    if isinstance(p_data, dict):
                        raw_results.extend(p_data.get("results", []))
            else:
                discover_params: Dict[str, Any] = {
                    "language": language,
                    "include_adult": False,
                }
                is_acclaim_sort = bool(sort_by and sort_by.strip().lower() in ("rating.desc", "rating", "vote_average.desc", "top_rated", "votes.desc", "vote_count.desc"))

                if feed_normalized in ("available_now", "digital"):
                    today_date = datetime.date.today()
                    max_theatrical_date = (today_date - datetime.timedelta(days=65)).isoformat()
                    discover_params["primary_release_date.lte"] = max_theatrical_date
                    if not is_acclaim_sort:
                        min_theatrical_date = (today_date - datetime.timedelta(days=730)).isoformat()
                        discover_params["primary_release_date.gte"] = min_theatrical_date
                    discover_params["sort_by"] = "popularity.desc"
                    discover_params["vote_count.gte"] = 15
                elif feed_normalized == "new":
                    discover_params["sort_by"] = "primary_release_date.desc"
                    today_str = datetime.date.today().isoformat()
                    discover_params["primary_release_date.lte"] = today_str
                    discover_params["vote_count.gte"] = 10
                elif feed_normalized in ("popular", "trending"):
                    discover_params["sort_by"] = "popularity.desc"
                elif feed_normalized == "top_rated":
                    discover_params["sort_by"] = "vote_average.desc"
                    discover_params["vote_count.gte"] = 100

                if sort_by:
                    s_norm = sort_by.strip().lower()
                    if s_norm in ("date.desc", "date", "newest"):
                        discover_params["sort_by"] = "primary_release_date.desc"
                        today_str = datetime.date.today().isoformat()
                        if not discover_params.get("primary_release_date.lte"):
                            discover_params["primary_release_date.lte"] = today_str
                        discover_params["vote_count.gte"] = max(discover_params.get("vote_count.gte", 0), 5)
                    elif s_norm in ("popularity.desc", "popularity", "popular"):
                        discover_params["sort_by"] = "popularity.desc"
                    elif s_norm in ("rating.desc", "rating", "vote_average.desc", "top_rated"):
                        discover_params["sort_by"] = "vote_average.desc"
                        discover_params["vote_count.gte"] = max(discover_params.get("vote_count.gte", 0), 200)
                    elif s_norm in ("votes.desc", "vote_count.desc"):
                        discover_params["sort_by"] = "vote_count.desc"
                        discover_params["vote_count.gte"] = max(discover_params.get("vote_count.gte", 0), 200)

                offset = 65 if feed_normalized in ("available_now", "digital") else 0
                start_date, end_date = _resolve_date_range(year_range, decade, time_range, None, offset_days=offset)
                if start_date:
                    discover_params["primary_release_date.gte"] = start_date
                if end_date:
                    discover_params["primary_release_date.lte"] = end_date



                if feed_normalized in ("available_now", "digital"):
                    today_date = datetime.date.today()
                    absolute_max_theatrical = (today_date - datetime.timedelta(days=65)).isoformat()
                    current_lte = discover_params.get("primary_release_date.lte")
                    if not current_lte or current_lte > absolute_max_theatrical:
                        discover_params["primary_release_date.lte"] = absolute_max_theatrical

                if language:
                    lang_clean = language.strip().lower()
                    if lang_clean in ("en_us", "en-us", "us"):
                        discover_params["with_origin_country"] = "US"
                        discover_params["with_original_language"] = "en"
                    elif lang_clean in ("en_gb", "en-gb", "gb", "uk"):
                        discover_params["with_origin_country"] = "GB"
                        discover_params["with_original_language"] = "en"
                    elif lang_clean in ("en_ca", "en-ca", "ca"):
                        discover_params["with_origin_country"] = "CA"
                        discover_params["with_original_language"] = "en"
                    elif lang_clean in ("en_au", "en-au", "au"):
                        discover_params["with_origin_country"] = "AU"
                        discover_params["with_original_language"] = "en"
                    elif lang_clean not in ("all", "any", ""):
                        discover_params["with_original_language"] = lang_clean


                if genre:
                    gid = _resolve_genre_id(genre, is_tv=False)
                    if gid:
                        discover_params["with_genres"] = str(gid)

                if min_rating is not None and min_rating > 0:
                    discover_params["vote_average.gte"] = str(min_rating)
                    discover_params["vote_count.gte"] = discover_params.get("vote_count.gte", 15)


                if studio:
                    discover_params["with_companies"] = studio

                # Parallel multi-page fetching
                start_page = max(1, page)
                pages_to_fetch = 3 if (limit > 20 or tier) else 2
                fetch_tasks = [
                    asyncio.to_thread(provider.discover_movies, {**discover_params, "page": p})
                    for p in range(start_page, start_page + pages_to_fetch)
                ]
                pages = await asyncio.gather(*fetch_tasks, return_exceptions=True)
                for d_page in pages:
                    if isinstance(d_page, dict):
                        raw_results.extend(d_page.get("results", []))

        # Process and normalize raw results
        processed_results: List[Dict[str, Any]] = []
        seen_result_ids = set()
        genre_name_map = TV_GENRE_NAMES if is_tv else MOVIE_GENRE_NAMES
        owned_ids, owned_titles = _get_owned_sets(db_domain)

        for item in raw_results:
            if not isinstance(item, dict):
                continue

            tmdb_id = item.get("id")
            if tmdb_id:
                if tmdb_id in seen_result_ids:
                    continue
                seen_result_ids.add(tmdb_id)

            title = item.get("title") or item.get("name") or item.get("original_title") or item.get("original_name") or ""
            release_date = item.get("release_date") or item.get("first_air_date") or ""


            year = None
            if release_date and len(release_date) >= 4 and release_date[:4].isdigit():
                year = int(release_date[:4])

            # Extract genre names from genre_ids
            raw_gids = item.get("genre_ids", [])
            item_genres: List[str] = []
            for gid in raw_gids:
                if gid in genre_name_map:
                    item_genres.append(genre_name_map[gid])
                elif isinstance(gid, str):
                    item_genres.append(gid)

            poster_path = item.get("poster_path")
            poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None
            backdrop_path = item.get("backdrop_path")

            vote_avg = float(item.get("vote_average", 0.0) or 0.0)
            vote_count = int(item.get("vote_count", 0) or 0)
            popularity = float(item.get("popularity", 0.0) or 0.0)

            # In-memory min-rating filter check if trending feed was used directly
            if min_rating is not None and vote_avg < min_rating:
                continue

            # Fast in-memory library ownership check
            is_owned = _check_owned_fast(tmdb_id, title, year, owned_ids, owned_titles)

            if exclude_owned and is_owned:
                continue


            # Apply the shared hard movie release-window decision. Discovery may
            # retain a rejected title as informational evidence, but it must never
            # expose it as available or actionable.
            today = datetime.date.today()
            today_str = today.isoformat()
            is_available_now = False
            quality_gate = None

            if is_tv:
                if release_date:
                    # TV broadcasts are immediately studio HDTV/Web-DL quality upon airing
                    is_available_now = bool(release_date <= today_str)
            else:
                quality_gate = evaluate_movie_eligibility(
                    title=title,
                    year=year,
                    tmdb_id=tmdb_id,
                    authoritative_release_date=release_date,
                    provider=provider,
                )
                is_available_now = bool(quality_gate.get("eligible"))

            # If user is specifically on the Available Now feed for movies, skip any non-available / CAM media
            if feed_normalized in ("available_now", "digital") and not is_tv and not is_available_now:
                continue

            # Unified Authoritative Tier classification: "major" vs "indie"
            item_tier = classify_media_tier(
                title=title,
                overview=item.get("overview", ""),
                vote_count=vote_count,
                popularity=popularity,
            )

            if tier:
                t_norm = tier.strip().lower()
                if t_norm in ("major", "blockbuster", "studio") and item_tier != "major":
                    continue
                elif t_norm in ("indie", "boutique", "independent") and item_tier != "indie":
                    continue




            res_entry = {
                "tmdb_id": tmdb_id,
                "title": title,
                "overview": item.get("overview", ""),
                "year": year,
                "release_date": release_date,
                "vote_average": round(vote_avg, 1),
                "vote_count": vote_count,
                "popularity": round(popularity, 1),
                "genres": item_genres,
                "poster_path": poster_path,
                "poster_url": poster_url,
                "backdrop_path": backdrop_path,
                "owned": is_owned,
                "in_library": is_owned,
                "available_now": is_available_now,
                "tier": item_tier,
                "quality_gate": quality_gate,
            }
            processed_results.append(res_entry)



            if len(processed_results) >= limit:
                break

        payload = {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "domain": domain_normalized,
                "feed": feed_normalized,
                "total_results": len(processed_results),
                "results": processed_results,
            }
        }
        set_cached_feed(cache_key, payload)
        return payload


    except Exception as e:
        logger.exception("Error executing discover_media_tool: %s", e)
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "DISCOVERY_ERROR",
                "message": f"Media discovery failed: {str(e)}",
                "retryable": True,
                "severity": "error",
            }
        }
