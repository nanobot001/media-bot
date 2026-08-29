import uuid
import json
import hashlib
import re
import logging
from typing import List, Dict, Any, Optional
import httpx
from moviebot.config import settings
from moviebot.db.repositories import SearchResultRepository
from moviebot.core.provider_cache_outcomes import check_cache_references

logger = logging.getLogger(__name__)


class ProwlarrClient:
    def __init__(self):
        self.url = settings.prowlarr_url.rstrip('/')
        self.api_key = settings.prowlarr_api_key

    @staticmethod
    def _cache_reference(item: Any) -> str:
        if isinstance(item, str):
            return item
        if not isinstance(item, dict):
            return ""
        info_hash = str(item.get("infoHash") or "").strip()
        if info_hash:
            return info_hash
        for key in ("magnetUrl", "downloadUrl", "guid"):
            value = str(item.get(key) or "").strip()
            if "xt=urn:btih:" in value.lower():
                return value
        guid_tail = str(item.get("guid") or "").rstrip("/").split("/")[-1]
        if len(guid_tail) in (32, 40):
            return guid_tail
        return ""

    async def _check_alldebrid_cache_outcomes(self, items: List[Any]) -> Dict[str, Any]:
        references = [self._cache_reference(item) for item in items]
        return await check_cache_references(references)

    async def _check_alldebrid_cache(self, items: List[Any]) -> Dict[str, bool]:
        """Compatibility bool map retained for callers outside the producer path."""
        structured = await self._check_alldebrid_cache_outcomes(items)
        results: Dict[str, bool] = {}
        for item, outcome in zip(items, structured.get("outcomes", [])):
            cached = outcome.get("status") == "cached"
            if isinstance(item, dict):
                for key in ("downloadUrl", "guid", "infoHash", "magnetUrl"):
                    value = item.get(key)
                    if value:
                        results[str(value)] = cached
            elif isinstance(item, str):
                results[item] = cached
        return results

    async def search(
        self,
        query: str,
        categories: Optional[List[int]] = None,
        imdb_id: Optional[str] = None,
        tvdb_id: Optional[str] = None,
        type: str = "search",
        domain: str = "movies",
        check_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Queries Prowlarr search endpoint for specified categories.
        Caches and obfuscates sensitive download URLs in search_results table.
        Optionally checks AllDebrid lightning instant cache.
        """
        raw_results = []
        is_mock = not self.api_key or self.api_key.lower() == "mock"

        if categories is None:
            categories = [2000] if domain == "movies" else [5000, 5030, 5040, 5045]

        if not is_mock:
            params: Dict[str, Any] = {
                "apikey": self.api_key,
                "query": query,
                "type": type,
            }
            if categories:
                params["categories"] = categories

            if imdb_id:
                clean_imdb = imdb_id.lstrip('t')
                params["imdbId"] = clean_imdb
            if tvdb_id:
                params["tvdbId"] = str(tvdb_id)

            endpoint = f"{self.url}/api/v1/search"

            async with httpx.AsyncClient() as client:
                response = await client.get(endpoint, params=params, timeout=60.0)
                response.raise_for_status()
                raw_results = response.json()


        if is_mock:
            tag = "2160p.UHD" if "2160" in query or "4k" in query.lower() else "1080p.BluRay"
            raw_results = [
                {
                    "title": f"{query}.2024.{tag}.DDP5.1.x264-MockRelease",
                    "indexer": "MockPublicTracker",
                    "size": 8589934592,
                    "seeders": 142,
                    "downloadUrl": f"magnet:?xt=urn:btih:mockbtih{hashlib.md5(query.encode()).hexdigest()[:16]}&dn={query}",
                    "guid": f"mock-guid-1-{query}",
                    "categories": categories or [2000]
                },
                {
                    "title": f"{query}.2024.720p.HDTV.x264-MockGroup",
                    "indexer": "MockPrivateTracker",
                    "size": 3221225472,
                    "seeders": 56,
                    "downloadUrl": f"magnet:?xt=urn:btih:mockbtih2{hashlib.md5(query.encode()).hexdigest()[:16]}&dn={query}",
                    "guid": f"mock-guid-2-{query}",
                    "categories": categories or [2000]
                }
            ]

        cache_outcomes = {
            "outcomes": [
                {"status": "unknown", "error_code": None} for _ in raw_results
            ]
        }
        if check_cache and raw_results:
            cache_outcomes = await self._check_alldebrid_cache_outcomes(raw_results)

        obfuscated_results = []
        for item_index, item in enumerate(raw_results):
            title = item.get("title", "Unknown Title")
            indexer = item.get("indexer", "Unknown Indexer")
            size = item.get("size", 0)
            seeders = item.get("seeders", 0)
            published_at = item.get("publishDate")

            download_url = item.get("downloadUrl") or item.get("guid") or ""
            if not download_url:
                continue

            ref_id = str(uuid.uuid4())
            magnet_hash = hashlib.sha256(download_url.encode("utf-8")).hexdigest()

            # Save to domain-specific database
            SearchResultRepository.insert(
                id=ref_id,
                query_string=query,
                indexer=indexer,
                title=title,
                size_bytes=size,
                seeders=seeders,
                magnet_uri_hash=magnet_hash,
                raw_json_payload=json.dumps(item),
                domain=domain
            )

            outcomes = cache_outcomes.get("outcomes", [])
            outcome = outcomes[item_index] if item_index < len(outcomes) else {
                "status": "unknown",
                "error_code": "AD_PARTIAL_RESPONSE",
            }
            cache_status = str(outcome.get("status") or "unknown")
            is_cached = cache_status == "cached"

            obfuscated_results.append({
                "reference_id": ref_id,
                "title": title,
                "size_bytes": size,
                "seeders": seeders,
                "indexer": indexer,
                "published_at": published_at,
                "cached": is_cached,
                "cache_status": cache_status,
                "cache_checked": cache_status in {"cached", "not_cached"},
                "cache_error_code": outcome.get("error_code"),
            })

        return obfuscated_results

    async def search_movies(
        self,
        query: str,
        imdb_id: Optional[str] = None,
        categories: Optional[List[int]] = None,
        domain: str = "movies",
        check_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Queries Prowlarr's search endpoint for Movies (Category 2000).
        """
        cats = categories or [2000]
        return await self.search(
            query=query,
            categories=cats,
            imdb_id=imdb_id,
            type="search",
            domain=domain,
            check_cache=check_cache
        )

    async def search_tv(
        self,
        query: str,
        season: Optional[int] = None,
        episode: Optional[int] = None,
        imdb_id: Optional[str] = None,
        tvdb_id: Optional[str] = None,
        categories: Optional[List[int]] = None,
        domain: str = "tv",
        check_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Queries Prowlarr's search endpoint for TV Series / Classic TV (Category 5000).
        Supports structured season / episode query formatting:
        - Series only: e.g. 'Reacher'
        - Season pack: e.g. 'Reacher S02'
        - Individual episode: e.g. 'Reacher S02E01'
        """
        clean_query = query.strip()
        if season is not None and episode is not None:
            tag = f"S{season:02d}E{episode:02d}"
            formatted_query = f"{clean_query} {tag}"
        elif season is not None:
            tag = f"S{season:02d}"
            formatted_query = f"{clean_query} {tag}"
        else:
            formatted_query = clean_query

        cats = categories or [5000, 5030, 5040, 5045]
        return await self.search(
            query=formatted_query,
            categories=cats,
            imdb_id=imdb_id,
            tvdb_id=tvdb_id,
            type="search",
            domain=domain,
            check_cache=check_cache
        )


