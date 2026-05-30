import uuid
import json
import hashlib
from typing import List, Dict, Any, Optional
import httpx
from moviebot.config import settings
from moviebot.db.repositories import SearchResultRepository


class ProwlarrClient:
    def __init__(self):
        self.url = settings.prowlarr_url.rstrip('/')
        self.api_key = settings.prowlarr_api_key

    async def search_movies(self, query: str, imdb_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Queries Prowlarr's search endpoint for Category 2000 (Movies).
        Caches and obfuscates sensitive download URLs in search_results table.
        """
        raw_results = []
        is_mock = not self.api_key or self.api_key.lower() == "mock"

        if not is_mock:
            params = {
                "apikey": self.api_key,
                "query": query,
                "categories": 2000,  # Movies category
            }
            
            # Add IMDb ID filter if present
            # Prowlarr api search supports search type parameter
            if imdb_id:
                # strip 'tt' prefix if it exists as some indexers expect digits only
                clean_imdb = imdb_id.lstrip('t')
                params["imdbId"] = clean_imdb

            endpoint = f"{self.url}/api/v1/search"
            
            async with httpx.AsyncClient() as client:
                response = await client.get(endpoint, params=params, timeout=30.0)
                response.raise_for_status()
                raw_results = response.json()

        if is_mock:
            raw_results = [
                {
                    "title": f"{query}.2024.1080p.BluRay.DDP5.1.x264-MockRelease",
                    "indexer": "MockPublicTracker",
                    "size": 8589934592,
                    "seeders": 142,
                    "downloadUrl": f"magnet:?xt=urn:btih:mockbtih{hashlib.md5(query.encode()).hexdigest()[:16]}&dn={query}+2024+1080p",
                    "guid": f"mock-guid-1-{query}"
                },
                {
                    "title": f"{query}.2024.2160p.UHD.BluRay.HDR.HEVC-MockUHD",
                    "indexer": "MockPrivateTracker",
                    "size": 17179869184,
                    "seeders": 56,
                    "downloadUrl": f"magnet:?xt=urn:btih:mockbtih2{hashlib.md5(query.encode()).hexdigest()[:16]}&dn={query}+2024+2160p",
                    "guid": f"mock-guid-2-{query}"
                }
            ]

        obfuscated_results = []
        for item in raw_results:
            title = item.get("title", "Unknown Title")
            indexer = item.get("indexer", "Unknown Indexer")
            size = item.get("size", 0)
            seeders = item.get("seeders", 0)
            
            # The download url containing potential keys
            download_url = item.get("downloadUrl") or item.get("guid") or ""
            if not download_url:
                continue

            # Generate obfuscated key and hash representations
            ref_id = str(uuid.uuid4())
            magnet_hash = hashlib.sha256(download_url.encode("utf-8")).hexdigest()

            # Save the full entry in local search cache repository
            SearchResultRepository.insert(
                id=ref_id,
                query_string=query,
                indexer=indexer,
                title=title,
                size_bytes=size,
                seeders=seeders,
                magnet_uri_hash=magnet_hash,
                raw_json_payload=json.dumps(item)
            )

            # Return stripped result details back to presentation layers
            obfuscated_results.append({
                "reference_id": ref_id,
                "title": title,
                "size_bytes": size,
                "seeders": seeders,
                "indexer": indexer
            })

        return obfuscated_results
