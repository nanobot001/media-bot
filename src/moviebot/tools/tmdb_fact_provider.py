import logging
import time
from typing import Optional, Dict, Any, List
import httpx
from moviebot.config import settings

logger = logging.getLogger(__name__)

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
        request_interval_seconds: float = 0.2,
        max_retries: int = 2,
        retry_backoff_seconds: float = 5.0,
    ):
        self.api_key = api_key or settings.tmdb_api_key
        self.bearer_token = bearer_token or settings.tmdb_bearer_token
        self.base_url = (base_url or settings.tmdb_base_url or "https://api.themoviedb.org/3").rstrip("/")
        
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "MovieBot/1.1 (anthony@example.com)"
        }
        if self.bearer_token:
            self.headers["Authorization"] = f"Bearer {self.bearer_token}"
            
        self.client = httpx.Client(headers=self.headers, timeout=15.0)
        self.request_interval_seconds = request_interval_seconds
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds
        self._last_request_at = 0.0
        self._rate_limited = False

    def _sleep_for_pacing(self) -> None:
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
            
        # Get details with keywords
        details = self._get_json(f"movie/{movie_id}", {"append_to_response": "keywords"})
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
        
        return {
            "source": "tmdb",
            "tmdb_id": movie_id,
            "imdb_id": details.get("imdb_id") or imdb_id,
            "title": details.get("title") or title,
            "collection": collection_name,
            "production_companies": companies,
            "keywords": keywords,
            "genres": genres,
            "tagline": details.get("tagline", ""),
            "overview": details.get("overview", ""),
            "lookup_method": source_method
        }
