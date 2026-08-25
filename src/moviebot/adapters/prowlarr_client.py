import uuid
import json
import hashlib
import re
import logging
from typing import List, Dict, Any, Optional
import httpx
from moviebot.config import settings
from moviebot.db.repositories import SearchResultRepository

logger = logging.getLogger(__name__)


class ProwlarrClient:
    def __init__(self):
        self.url = settings.prowlarr_url.rstrip('/')
        self.api_key = settings.prowlarr_api_key

    async def _check_alldebrid_cache(self, items: List[Any]) -> Dict[str, bool]:
        """Queries AllDebrid for instant availability and maps download_url/hash -> bool."""
        results = {}
        if not items:
            return results

        # Support list of raw items or list of download URLs
        magnets_to_check = []
        item_keys_map = {} # hash_or_url -> list of matching keys

        for item in items:
            if isinstance(item, dict):
                info_hash = (item.get("infoHash") or "").lower()
                download_url = item.get("downloadUrl") or ""
                magnet_url = item.get("magnetUrl") or ""
                guid = item.get("guid") or ""

                target_hash = ""
                if info_hash:
                    target_hash = info_hash
                elif magnet_url and "xt=urn:btih:" in magnet_url.lower():
                    target_hash = magnet_url.lower().split("xt=urn:btih:")[1].split("&")[0]
                elif download_url.startswith("magnet:") and "xt=urn:btih:" in download_url.lower():
                    target_hash = download_url.lower().split("xt=urn:btih:")[1].split("&")[0]
                elif guid and "xt=urn:btih:" in guid.lower():
                    target_hash = guid.lower().split("xt=urn:btih:")[1].split("&")[0]
                elif len(guid.split("/")[-1]) in (32, 40): # Some indexers put infohash in guid path
                    target_hash = guid.split("/")[-1].lower()

                keys = [k for k in [download_url, guid, info_hash, target_hash] if k]
                if target_hash:
                    mag = f"magnet:?xt=urn:btih:{target_hash}"
                    magnets_to_check.append(mag)
                    for k in keys:
                        item_keys_map.setdefault(target_hash, []).append(k)
                        item_keys_map.setdefault(mag, []).append(k)
                        results[k] = False
                else:
                    if download_url.startswith("magnet:"):
                        magnets_to_check.append(download_url)
                    for k in keys:
                        item_keys_map.setdefault(download_url.lower(), []).append(k)
                        results[k] = False
            elif isinstance(item, str):
                mag = item
                keys = [item]
                target_hash = ""
                if "xt=urn:btih:" in item.lower():
                    target_hash = item.lower().split("xt=urn:btih:")[1].split("&")[0]
                elif len(item) in (32, 40):
                    target_hash = item.lower()
                    mag = f"magnet:?xt=urn:btih:{target_hash}"

                if target_hash:
                    item_keys_map.setdefault(target_hash, []).append(item)
                    item_keys_map.setdefault(mag, []).append(item)
                else:
                    item_keys_map.setdefault(item.lower(), []).append(item)
                magnets_to_check.append(mag)
                results[item] = False

        if not magnets_to_check:
            return results

        try:
            from moviebot.adapters.alldebrid_client import AllDebridClient
            client = AllDebridClient()
            if not client.api_key or client.api_key.lower() == "mock":
                for keys in item_keys_map.values():
                    for k in keys:
                        results[k] = True
                return results

            cache_data = await client.instant_check(magnets_to_check)
            magnets = cache_data.get("magnets", [])
            for m in magnets:
                if isinstance(m, dict):
                    m_hash = (m.get("hash") or "").lower()
                    m_magnet = m.get("magnet", "")
                    is_instant = bool(m.get("instant", False) or m.get("ready", False))
                    if m_hash and m_hash in item_keys_map:
                        for k in item_keys_map[m_hash]:
                            results[k] = is_instant
                    if m_magnet and m_magnet in item_keys_map:
                        for k in item_keys_map[m_magnet]:
                            results[k] = is_instant
        except Exception as e:
            logger.debug("AllDebrid instant cache check failed: %s", e)

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

        cache_map = {}
        if check_cache and raw_results:
            cache_map = await self._check_alldebrid_cache(raw_results)

        obfuscated_results = []
        for item in raw_results:
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

            info_hash = (item.get("infoHash") or "").lower()
            guid = item.get("guid") or ""
            is_cached = bool(
                cache_map.get(download_url, False) or
                cache_map.get(info_hash, False) or
                cache_map.get(guid, False)
            )

            obfuscated_results.append({
                "reference_id": ref_id,
                "title": title,
                "size_bytes": size,
                "seeders": seeders,
                "indexer": indexer,
                "published_at": published_at,
                "cached": is_cached,
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


