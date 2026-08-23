import datetime
import logging
from typing import Dict, Any, List, Optional
from moviebot.tools.tmdb_fact_provider import TMDbFactProvider
from moviebot.db.repositories import LibraryItemRepository
from moviebot.core.dedupe import normalize_title

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

TV_GENRES: Dict[str, int] = {
    "action": 10759,
    "action & adventure": 10759,
    "adventure": 10759,
    "animation": 16,
    "comedy": 35,
    "crime": 80,
    "documentary": 99,
    "drama": 18,
    "family": 10751,
    "kids": 10762,
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

NETWORK_IDS: Dict[str, str] = {
    "abc": "2",
    "nbc": "6",
    "cbs": "16",
    "fox": "19",
    "hbo": "49",
    "bbc": "4|332|100",
    "bbc one": "4",
    "bbc two": "332",
    "pbs": "14",
    "amc": "174",
    "showtime": "67",
    "fx": "88",
    "cw": "71",
    "the cw": "71",
    "netflix": "213",
    "amazon": "1024",
    "hulu": "453",
    "apple tv+": "2552",
    "disney+": "2739",
}

DECADE_RANGES: Dict[str, tuple[str, str]] = {
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
}


def _resolve_genre_id(genre_str: str, is_tv: bool) -> Optional[int]:
    if not genre_str:
        return None
    cleaned = genre_str.strip().lower()
    mapping = TV_GENRES if is_tv else MOVIE_GENRES
    if cleaned in mapping:
        return mapping[cleaned]
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
    default_max_date: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    start_date = None
    end_date = None

    if decade:
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


def _check_owned(
    tmdb_id: Optional[int],
    title: str,
    year: Optional[int],
    db_domain: str
) -> bool:
    try:
        if tmdb_id:
            items = LibraryItemRepository.get_by_tmdb_id(tmdb_id, domain=db_domain)
            if items:
                return True
        if title:
            norm_title = normalize_title(title)
            if year:
                items = LibraryItemRepository.get_by_normalized_title_and_year(norm_title, year, domain=db_domain)
                if items:
                    return True
            else:
                items = LibraryItemRepository.search_by_normalized_title(norm_title, domain=db_domain)
                if items:
                    return True
    except Exception as e:
        logger.debug("Error checking ownership for '%s' in domain '%s': %s", title, db_domain, e)
    return False


async def discover_media_tool(
    domain: str = "movies",
    feed: str = "trending",
    genre: Optional[str] = None,
    min_rating: Optional[float] = None,
    year_range: Optional[str] = None,
    decade: Optional[str] = None,
    language: str = "en",
    network: Optional[str] = None,
    studio: Optional[str] = None,
    exclude_owned: bool = False,
    time_window: str = "week",
    limit: int = 20,
    tmdb_provider: Optional[TMDbFactProvider] = None,
) -> Dict[str, Any]:
    """
    Unified domain-parameterized media discovery tool.
    Fetches trending, popular, digital releases, and top rated titles from TMDb for Movies, TV, and Classic TV,
    with filtering and local library deduplication.
    """
    tool_name = "discover_media_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    domain_normalized = (domain or "movies").strip().lower()
    if domain_normalized not in ("movies", "tv", "classic_tv"):
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "INVALID_DOMAIN",
                "message": f"Unsupported media domain '{domain}'. Must be one of: 'movies', 'tv', 'classic_tv'.",
                "retryable": False,
                "severity": "error",
            }
        }

    feed_normalized = (feed or "trending").strip().lower()
    if feed_normalized not in ("trending", "popular", "digital", "top_rated", "airing"):
        feed_normalized = "trending"

    db_domain = "tv_classic" if domain_normalized == "classic_tv" else domain_normalized
    is_tv = domain_normalized in ("tv", "classic_tv")
    is_classic_tv = domain_normalized == "classic_tv"

    provider = tmdb_provider or TMDbFactProvider()

    try:
        # Determine if we can use the direct trending endpoint or if filters require discover
        has_custom_filters = bool(
            genre or min_rating or year_range or decade or network or studio or is_classic_tv or (language and language != "en")
        )

        raw_results: List[Dict[str, Any]] = []

        if is_tv:
            # TV & Classic TV Logic
            if feed_normalized == "trending" and not has_custom_filters:
                trending_data = provider.get_trending_tv(time_window=time_window)
                raw_results = trending_data.get("results", []) if trending_data else []
            else:
                discover_params: Dict[str, Any] = {}
                if language:
                    discover_params["with_original_language"] = language

                # Feed-specific defaults
                if feed_normalized == "popular" or feed_normalized == "trending":
                    discover_params["sort_by"] = "popularity.desc"
                elif feed_normalized == "top_rated":
                    discover_params["sort_by"] = "vote_average.desc"
                    discover_params["vote_count.gte"] = 50
                elif feed_normalized == "airing":
                    discover_params["sort_by"] = "popularity.desc"
                    today_str = datetime.date.today().isoformat()
                    discover_params["air_date.lte"] = today_str

                # Classic TV defaults and date boundaries
                default_max_date = "2010-01-01" if is_classic_tv else None
                start_date, end_date = _resolve_date_range(year_range, decade, default_max_date)
                if start_date:
                    discover_params["first_air_date.gte"] = start_date
                if end_date:
                    discover_params["first_air_date.lte"] = end_date

                # Genre filter
                if genre:
                    gid = _resolve_genre_id(genre, is_tv=True)
                    if gid:
                        discover_params["with_genres"] = str(gid)

                # Min rating filter
                if min_rating is not None and min_rating > 0:
                    discover_params["vote_average.gte"] = str(min_rating)
                    discover_params["vote_count.gte"] = discover_params.get("vote_count.gte", 10)

                # Network filter
                if network:
                    nid = _resolve_network_id(network)
                    if nid:
                        discover_params["with_networks"] = nid

                discover_data = provider.discover_tv(discover_params)
                raw_results = discover_data.get("results", []) if discover_data else []

        else:
            # Movie Logic
            if feed_normalized == "trending" and not has_custom_filters:
                trending_data = provider.get_trending_movies(time_window=time_window)
                raw_results = trending_data.get("results", []) if trending_data else []
            else:
                discover_params = {}
                if language:
                    discover_params["with_original_language"] = language

                # Feed-specific defaults
                if feed_normalized == "popular" or feed_normalized == "trending":
                    discover_params["sort_by"] = "popularity.desc"
                elif feed_normalized == "digital":
                    discover_params["sort_by"] = "primary_release_date.desc"
                    discover_params["with_release_type"] = "4|5"
                    discover_params["vote_count.gte"] = 20
                elif feed_normalized == "top_rated":
                    discover_params["sort_by"] = "vote_average.desc"
                    discover_params["vote_count.gte"] = 200

                # Date boundaries
                start_date, end_date = _resolve_date_range(year_range, decade, None)
                if start_date:
                    discover_params["primary_release_date.gte"] = start_date
                if end_date:
                    discover_params["primary_release_date.lte"] = end_date

                # Genre filter
                if genre:
                    gid = _resolve_genre_id(genre, is_tv=False)
                    if gid:
                        discover_params["with_genres"] = str(gid)

                # Min rating filter
                if min_rating is not None and min_rating > 0:
                    discover_params["vote_average.gte"] = str(min_rating)
                    discover_params["vote_count.gte"] = discover_params.get("vote_count.gte", 20)

                # Studio filter
                if studio:
                    discover_params["with_companies"] = studio

                discover_data = provider.discover_movies(discover_params)
                raw_results = discover_data.get("results", []) if discover_data else []

        # Process and normalize raw results
        processed_results: List[Dict[str, Any]] = []
        genre_name_map = TV_GENRE_NAMES if is_tv else MOVIE_GENRE_NAMES

        for item in raw_results:
            if not isinstance(item, dict):
                continue

            tmdb_id = item.get("id")
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

            # Check library ownership
            is_owned = _check_owned(tmdb_id, title, year, db_domain)

            if exclude_owned and is_owned:
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
            }
            processed_results.append(res_entry)

            if len(processed_results) >= limit:
                break

        return {
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
