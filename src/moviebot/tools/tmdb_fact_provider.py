import logging
import time
from typing import Optional, Dict, Any, List
import httpx
from moviebot.config import settings
from moviebot.tools.media_tier_classifier import classify_media_tier

logger = logging.getLogger(__name__)


_SHARED_CLIENT: Optional[httpx.Client] = None

def get_shared_client(headers: Dict[str, str]) -> httpx.Client:
    global _SHARED_CLIENT
    if _SHARED_CLIENT is None or _SHARED_CLIENT.is_closed:
        _SHARED_CLIENT = httpx.Client(
            headers=headers,
            timeout=10.0,
            limits=httpx.Limits(max_keepalive_connections=30, max_connections=50)
        )
    return _SHARED_CLIENT


class TMDbFactProvider:
    """
    Retrieves facts from TMDb API using API key or Bearer token.
    Paces requests and handles rate limiting.
    """
    def __init__(
        self,
        api_key: Optional[str] = None,
        bearer_token: Optional[str] = None,
        base_url: Optional[str] = None,
        request_interval_seconds: float = 0.0,
        max_retries: int = 2,
        retry_backoff_seconds: float = 2.0,
    ):
        self.api_key = api_key or settings.tmdb_api_key
        self.bearer_token = bearer_token or settings.tmdb_bearer_token
        self.base_url = (base_url or settings.tmdb_base_url or "https://api.themoviedb.org/3").rstrip("/")
        
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "MovieBot/1.5 (anthony@example.com)"
        }
        if self.bearer_token:
            self.headers["Authorization"] = f"Bearer {self.bearer_token}"
            
        self.client = get_shared_client(self.headers)
        self.request_interval_seconds = request_interval_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._last_request_at = 0.0
        self._rate_limited = False


    def _sleep_for_pacing(self) -> None:
        if self.request_interval_seconds <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        remaining = self.request_interval_seconds - elapsed
        if remaining > 0:
            time.sleep(remaining)


    def _get_json(self, path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        
        # Add api_key to params if bearer token is not present
        if not self.bearer_token and self.api_key:
            params = params or {}
            params["api_key"] = self.api_key

        for attempt in range(self.max_retries + 1):
            self._sleep_for_pacing()
            self._last_request_at = time.monotonic()
            try:
                res = self.client.get(url, params=params)
                if res.status_code == 429:
                    self._rate_limited = True
                    retry_after = res.headers.get("Retry-After")
                    try:
                        delay = float(retry_after) if retry_after else self.retry_backoff_seconds * (attempt + 1)
                    except ValueError:
                        delay = self.retry_backoff_seconds * (attempt + 1)
                    logger.warning("TMDb rate limited request; sleeping %.1fs before retry", delay)
                    if attempt >= self.max_retries:
                        return None
                    time.sleep(delay)
                    continue
                res.raise_for_status()
                return res.json()
            except Exception as e:
                if attempt >= self.max_retries:
                    logger.warning(f"Error requesting TMDb API url={url}: {e}")
                    return None
                time.sleep(self.retry_backoff_seconds * (attempt + 1))
        return None

    def get_movie_id_by_imdb_id(self, imdb_id: str) -> Optional[int]:
        if not imdb_id:
            return None
        imdb_id = imdb_id.strip()
        data = self._get_json(f"find/{imdb_id}", {"external_source": "imdb_id"})
        if not data:
            return None
        movie_results = data.get("movie_results", [])
        if movie_results:
            return movie_results[0].get("id")
        return None

    def get_movie_id_by_title_year(self, title: str, year: Optional[int]) -> Optional[int]:
        if not title:
            return None
        params = {"query": title}
        if year:
            params["year"] = str(year)
            params["primary_release_year"] = str(year)
        data = self._get_json("search/movie", params)
        if not data:
            return None
        results = data.get("results", [])
        if results:
            return results[0].get("id")
        return None

    def get_facts(self, title: str, year: Optional[int], imdb_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        if not self.api_key and not self.bearer_token:
            logger.warning("TMDb API key or Bearer token is not set. Skipping TMDb lookup.")
            return None
        # Find movie ID
        movie_id = None
        source_method = "imdb_id"
        
        if imdb_id:
            movie_id = self.get_movie_id_by_imdb_id(imdb_id)
            
        if not movie_id:
            movie_id = self.get_movie_id_by_title_year(title, year)
            source_method = "title_year"
            
        if not movie_id:
            logger.info(f"Could not find TMDb ID for movie '{title} ({year})'")
            return None
            
        # Get details with keywords and release dates for content-rating gates.
        details = self._get_json(f"movie/{movie_id}", {"append_to_response": "keywords,release_dates"})
        if not details:
            return None
            
        collection_name = None
        collection = details.get("belongs_to_collection")
        if collection:
            collection_name = collection.get("name")
            
        companies = [c.get("name") for c in details.get("production_companies", []) if c.get("name")]
        
        kw_data = details.get("keywords", {})
        kw_list = kw_data.get("keywords", []) if isinstance(kw_data, dict) else []
        keywords = [k.get("name") for k in kw_list if k.get("name")]
        
        genres = [g.get("name") for g in details.get("genres", []) if g.get("name")]
        content_rating = self._extract_us_certification(details)
        
        return {
            "source": "tmdb",
            "tmdb_id": movie_id,
            "imdb_id": details.get("imdb_id") or imdb_id,
            "title": details.get("title") or title,
            "collection": collection_name,
            "production_companies": companies,
            "keywords": keywords,
            "genres": genres,
            "content_rating": content_rating,
            "tagline": details.get("tagline", ""),
            "overview": details.get("overview", ""),
            "poster_path": details.get("poster_path"),
            "lookup_method": source_method
        }

    def get_tv_id_by_imdb_id(self, imdb_id: str) -> Optional[int]:
        if not imdb_id:
            return None
        imdb_id = imdb_id.strip()
        data = self._get_json(f"find/{imdb_id}", {"external_source": "imdb_id"})
        if not data:
            return None
        tv_results = data.get("tv_results", [])
        if tv_results:
            return tv_results[0].get("id")
        return None

    def get_tv_id_by_title_year(self, title: str, year: Optional[int] = None) -> Optional[int]:
        if not title:
            return None
        params = {"query": title}
        if year:
            params["first_air_date_year"] = str(year)
        data = self._get_json("search/tv", params)
        if not data:
            return None
        results = data.get("results", [])
        if results:
            return results[0].get("id")
        return None

    def get_tv_show_facts(self, tv_id: int) -> Optional[Dict[str, Any]]:
        if not tv_id:
            return None
        details = self._get_json(f"tv/{tv_id}", {"append_to_response": "keywords,content_ratings"})
        if not details:
            return None

        kw_data = details.get("keywords", {})
        kw_list = kw_data.get("results", []) if isinstance(kw_data, dict) else []
        keywords = [k.get("name") for k in kw_list if isinstance(k, dict) and k.get("name")]

        genres = [g.get("name") for g in details.get("genres", []) if isinstance(g, dict) and g.get("name")]
        networks = [n.get("name") for n in details.get("networks", []) if isinstance(n, dict) and n.get("name")]
        companies = [c.get("name") for c in details.get("production_companies", []) if isinstance(c, dict) and c.get("name")]
        content_rating = self._extract_us_tv_certification(details)
        poster_path = details.get("poster_path")
        poster_url = f"https://image.tmdb.org/t/p/w500{poster_path}" if poster_path else None

        return {
            "source": "tmdb",
            "tmdb_id": tv_id,
            "title": details.get("name") or details.get("original_name") or "",
            "overview": details.get("overview", ""),
            "genres": genres,
            "number_of_seasons": details.get("number_of_seasons", 0),
            "number_of_episodes": details.get("number_of_episodes", 0),
            "seasons": details.get("seasons", []),
            "networks": networks,
            "production_companies": companies,
            "keywords": keywords,
            "content_rating": content_rating,
            "first_air_date": details.get("first_air_date"),
            "last_air_date": details.get("last_air_date"),
            "status": details.get("status"),
            "poster_path": poster_path,
            "poster_url": poster_url,
            "backdrop_path": details.get("backdrop_path"),
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
        }

    def get_tv_season_facts(self, tv_id: int, season: int) -> Optional[Dict[str, Any]]:
        if not tv_id:
            return None
        season_data = self._get_json(f"tv/{tv_id}/season/{season}")
        if not season_data:
            return None

        raw_episodes = season_data.get("episodes", [])
        episodes = []
        for ep in raw_episodes:
            if isinstance(ep, dict):
                episodes.append({
                    "episode_number": ep.get("episode_number"),
                    "name": ep.get("name", ""),
                    "overview": ep.get("overview", ""),
                    "air_date": ep.get("air_date"),
                    "vote_average": ep.get("vote_average"),
                    "still_path": ep.get("still_path"),
                })

        return {
            "tv_id": tv_id,
            "season_number": season_data.get("season_number", season),
            "name": season_data.get("name", f"Season {season}"),
            "overview": season_data.get("overview", ""),
            "air_date": season_data.get("air_date"),
            "poster_path": season_data.get("poster_path"),
            "episodes": episodes,
        }

    def get_trending_movies(self, time_window: str = "day", page: Optional[int] = None) -> Optional[Dict[str, Any]]:
        window = "week" if time_window.lower() == "week" else "day"
        params = {"page": page} if (page is not None and page > 1) else None
        return self._get_json(f"trending/movie/{window}", params)

    def get_trending_tv(self, time_window: str = "day", page: Optional[int] = None) -> Optional[Dict[str, Any]]:
        window = "week" if time_window.lower() == "week" else "day"
        params = {"page": page} if (page is not None and page > 1) else None
        return self._get_json(f"trending/tv/{window}", params)

    def get_popular_movies(self, page: Optional[int] = None) -> Optional[Dict[str, Any]]:
        params = {"page": page} if (page is not None and page > 1) else None
        return self._get_json("movie/popular", params)

    def get_popular_tv(self, page: Optional[int] = None) -> Optional[Dict[str, Any]]:
        params = {"page": page} if (page is not None and page > 1) else None
        return self._get_json("tv/popular", params)


    def discover_movies(self, filters: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return self._get_json("discover/movie", filters or {})

    def discover_tv(self, filters: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        return self._get_json("discover/tv", filters or {})


    @staticmethod
    def _format_currency(amount: Optional[int]) -> Optional[str]:
        if not amount or amount <= 0:
            return None
        if amount >= 1_000_000_000:
            return f"${amount / 1_000_000_000:.2f}B"
        elif amount >= 1_000_000:
            return f"${amount / 1_000_000:.1f}M"
        elif amount >= 1_000:
            return f"${amount / 1_000:.0f}K"
        return f"${amount:,}"

    def get_movie_details(self, movie_id: int) -> Optional[Dict[str, Any]]:
        if not movie_id:
            return None
        details = self._get_json(f"movie/{movie_id}", {"append_to_response": "credits,videos,external_ids,release_dates,reviews"})
        if not details:
            return None

        # Format runtime (e.g. 128m -> 2h 8m)
        raw_runtime = details.get("runtime")
        runtime_str = None
        if raw_runtime and raw_runtime > 0:
            hrs = raw_runtime // 60
            mins = raw_runtime % 60
            runtime_str = f"{hrs}h {mins}m" if hrs > 0 else f"{mins}m"

        credits = details.get("credits", {})
        crew = credits.get("crew", []) if isinstance(credits, dict) else []
        cast_raw = credits.get("cast", []) if isinstance(credits, dict) else []

        directors = [c.get("name") for c in crew if isinstance(c, dict) and c.get("job") == "Director"]
        writers = [c.get("name") for c in crew if isinstance(c, dict) and c.get("job") in ("Screenplay", "Writer", "Story")][:3]

        cast = []
        for c in cast_raw[:8]:
            if isinstance(c, dict):
                p_path = c.get("profile_path")
                cast.append({
                    "name": c.get("name", ""),
                    "character": c.get("character", ""),
                    "profile_url": f"https://image.tmdb.org/t/p/w185{p_path}" if p_path else None
                })

        # Reviews
        reviews_raw = details.get("reviews", {}).get("results", []) if isinstance(details.get("reviews"), dict) else []
        reviews = []
        for r in reviews_raw[:3]:
            if isinstance(r, dict):
                content = (r.get("content") or "").strip().replace("\r\n", " ").replace("\n", " ")
                if len(content) > 240:
                    content = content[:237].rsplit(" ", 1)[0] + "..."
                author_rating = r.get("author_details", {}).get("rating") if isinstance(r.get("author_details"), dict) else None
                reviews.append({
                    "author": r.get("author") or "Verified Reviewer",
                    "rating": author_rating,
                    "content": content,
                    "url": r.get("url"),
                })

        # Find official YouTube trailer
        videos = details.get("videos", {}).get("results", []) if isinstance(details.get("videos"), dict) else []
        trailer_key = None
        for v in videos:
            if isinstance(v, dict) and v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
                trailer_key = v.get("key")
                if v.get("type") == "Trailer":
                    break

        ext_ids = details.get("external_ids", {}) if isinstance(details.get("external_ids"), dict) else {}
        imdb_id = details.get("imdb_id") or ext_ids.get("imdb_id")

        genres = [g.get("name") for g in details.get("genres", []) if isinstance(g, dict) and g.get("name")]
        companies = [c.get("name") for c in details.get("production_companies", []) if isinstance(c, dict) and c.get("name")]

        # Extract US Release Dates (Theatrical, Digital, Certification)
        us_theatrical_date = None
        us_digital_date = None
        us_certification = None
        rd_data = details.get("release_dates", {})
        rd_results = rd_data.get("results", []) if isinstance(rd_data, dict) else []
        for country in rd_results:
            if isinstance(country, dict) and country.get("iso_3166_1") == "US":
                for r in country.get("release_dates") or []:
                    if not isinstance(r, dict):
                        continue
                    r_type = r.get("type")
                    r_date_str = (r.get("release_date") or "")[:10]
                    if not us_certification and r.get("certification"):
                        us_certification = r.get("certification").strip()
                    if r_type == 3 and not us_theatrical_date and r_date_str:
                        us_theatrical_date = r_date_str
                    elif r_type in (4, 5) and not us_digital_date and r_date_str:
                        us_digital_date = r_date_str

        theatrical_date_final = us_theatrical_date or details.get("release_date")
        budget_num = details.get("budget")
        revenue_num = details.get("revenue")

        movie_tier = classify_media_tier(
            title=details.get("title") or details.get("original_title") or "",
            overview=details.get("overview") or "",
            vote_count=details.get("vote_count") or 0,
            popularity=details.get("popularity") or 0.0,
            budget=budget_num,
            revenue=revenue_num,
            production_companies=companies,
        )

        return {
            "tmdb_id": movie_id,
            "imdb_id": imdb_id,
            "imdb_url": f"https://www.imdb.com/title/{imdb_id}" if imdb_id else None,
            "tmdb_url": f"https://www.themoviedb.org/movie/{movie_id}",
            "title": details.get("title") or details.get("original_title") or "",
            "tagline": details.get("tagline") or "",
            "overview": details.get("overview") or "",
            "runtime_minutes": raw_runtime,
            "runtime_formatted": runtime_str,
            "release_date": details.get("release_date"),
            "us_theatrical_date": theatrical_date_final,
            "us_digital_date": us_digital_date,
            "certification": us_certification,
            "status": details.get("status") or "Released",
            "tier": movie_tier,
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
            "genres": genres,
            "directors": directors,
            "writers": writers,
            "cast": cast,
            "production_companies": companies,
            "budget": budget_num,
            "budget_formatted": self._format_currency(budget_num),
            "revenue": revenue_num,
            "revenue_formatted": self._format_currency(revenue_num),
            "reviews": reviews,
            "trailer_key": trailer_key,
            "trailer_url": f"https://www.youtube.com/watch?v={trailer_key}" if trailer_key else None,
            "poster_url": f"https://image.tmdb.org/t/p/w500{details.get('poster_path')}" if details.get("poster_path") else None,
            "backdrop_url": f"https://image.tmdb.org/t/p/original{details.get('backdrop_path')}" if details.get("backdrop_path") else None,
        }

    def get_tv_full_details(self, tv_id: int) -> Optional[Dict[str, Any]]:
        if not tv_id:
            return None
        details = self._get_json(f"tv/{tv_id}", {"append_to_response": "credits,videos,external_ids,content_ratings,reviews"})
        if not details:
            return None

        credits = details.get("credits", {})
        cast_raw = credits.get("cast", []) if isinstance(credits, dict) else []
        created_by = details.get("created_by", []) or []
        creators = [c.get("name") for c in created_by if isinstance(c, dict) and c.get("name")]

        cast = []
        for c in cast_raw[:8]:
            if isinstance(c, dict):
                p_path = c.get("profile_path")
                cast.append({
                    "name": c.get("name", ""),
                    "character": c.get("character", ""),
                    "profile_url": f"https://image.tmdb.org/t/p/w185{p_path}" if p_path else None
                })

        # Reviews
        reviews_raw = details.get("reviews", {}).get("results", []) if isinstance(details.get("reviews"), dict) else []
        reviews = []
        for r in reviews_raw[:3]:
            if isinstance(r, dict):
                content = (r.get("content") or "").strip().replace("\r\n", " ").replace("\n", " ")
                if len(content) > 240:
                    content = content[:237].rsplit(" ", 1)[0] + "..."
                author_rating = r.get("author_details", {}).get("rating") if isinstance(r.get("author_details"), dict) else None
                reviews.append({
                    "author": r.get("author") or "Verified Reviewer",
                    "rating": author_rating,
                    "content": content,
                    "url": r.get("url"),
                })

        videos = details.get("videos", {}).get("results", []) if isinstance(details.get("videos"), dict) else []
        trailer_key = None
        for v in videos:
            if isinstance(v, dict) and v.get("site") == "YouTube" and v.get("type") in ("Trailer", "Teaser"):
                trailer_key = v.get("key")
                if v.get("type") == "Trailer":
                    break

        ext_ids = details.get("external_ids", {}) if isinstance(details.get("external_ids"), dict) else {}
        imdb_id = ext_ids.get("imdb_id")

        genres = [g.get("name") for g in details.get("genres", []) if isinstance(g, dict) and g.get("name")]
        networks = [n.get("name") for n in details.get("networks", []) if isinstance(n, dict) and n.get("name")]
        companies = [c.get("name") for c in details.get("production_companies", []) if isinstance(c, dict) and c.get("name")]
        content_rating = self._extract_us_tv_certification(details)

        tv_tier = classify_media_tier(
            title=details.get("name") or details.get("original_name") or "",
            overview=details.get("overview") or "",
            vote_count=details.get("vote_count") or 0,
            popularity=details.get("popularity") or 0.0,
            production_companies=companies,
            networks=networks,
        )

        return {
            "tmdb_id": tv_id,
            "imdb_id": imdb_id,
            "imdb_url": f"https://www.imdb.com/title/{imdb_id}" if imdb_id else None,
            "tmdb_url": f"https://www.themoviedb.org/tv/{tv_id}",
            "title": details.get("name") or details.get("original_name") or "",
            "tagline": details.get("tagline") or "",
            "overview": details.get("overview") or "",
            "number_of_seasons": details.get("number_of_seasons", 0),
            "number_of_episodes": details.get("number_of_episodes", 0),
            "first_air_date": details.get("first_air_date"),
            "last_air_date": details.get("last_air_date"),
            "status": details.get("status") or "Returning Series",
            "tier": tv_tier,
            "certification": content_rating,
            "vote_average": details.get("vote_average"),
            "vote_count": details.get("vote_count"),
            "genres": genres,
            "creators": creators,
            "cast": cast,
            "networks": networks,
            "production_companies": companies,
            "reviews": reviews,
            "trailer_key": trailer_key,
            "trailer_url": f"https://www.youtube.com/watch?v={trailer_key}" if trailer_key else None,
            "poster_url": f"https://image.tmdb.org/t/p/w500{details.get('poster_path')}" if details.get("poster_path") else None,
            "backdrop_url": f"https://image.tmdb.org/t/p/original{details.get('backdrop_path')}" if details.get("backdrop_path") else None,
            "seasons": details.get("seasons", []),
        }



    @staticmethod
    def _extract_us_certification(details: Dict[str, Any]) -> Optional[str]:
        release_dates = details.get("release_dates") or {}
        results = release_dates.get("results") if isinstance(release_dates, dict) else []
        if not isinstance(results, list):
            return None
        for country in results:
            if country.get("iso_3166_1") != "US":
                continue
            for release in country.get("release_dates") or []:
                certification = (release.get("certification") or "").strip()
                if certification:
                    return certification
        return None

    @staticmethod
    def _extract_us_tv_certification(details: Dict[str, Any]) -> Optional[str]:
        ratings = details.get("content_ratings") or {}
        results = ratings.get("results") if isinstance(ratings, dict) else []
        if not isinstance(results, list):
            return None
        for item in results:
            if isinstance(item, dict) and item.get("iso_3166_1") == "US":
                rating = (item.get("rating") or "").strip()
                if rating:
                    return rating
        return None


