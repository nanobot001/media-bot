from typing import List, Dict, Any, Optional
import httpx
from moviebot.config import settings


class PlexClient:
    def __init__(self):
        self.url = settings.plex_url.rstrip('/')
        self.token = settings.plex_token

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Plex-Token": self.token
        }

    async def fetch_all_movies(self) -> List[Dict[str, Any]]:
        """
        Sweeps the Plex server sections, identifies movie libraries,
        and retrieves all movie assets with metadata and file layouts.
        """
        if not self.token:
            raise ValueError("PLEX_TOKEN is not configured.")

        # 1. Fetch all library sections
        sections_endpoint = f"{self.url}/library/sections"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(sections_endpoint, headers=self._get_headers(), timeout=10.0)
                response.raise_for_status()
                sections_data = response.json()
        except Exception as e:
            raise RuntimeError(f"Failed to query Plex sections: {str(e)}")

        sections = sections_data.get("MediaContainer", {}).get("Directory", [])
        movie_sections = [s for s in sections if s.get("type") == "movie"]

        movies = []
        for sec in movie_sections:
            sec_id = sec.get("key")
            if not sec_id:
                continue

            # 2. Fetch all items in this section
            sec_endpoint = f"{self.url}/library/sections/{sec_id}/all"
            try:
                async with httpx.AsyncClient() as client:
                    sec_res = await client.get(sec_endpoint, headers=self._get_headers(), timeout=15.0)
                    sec_res.raise_for_status()
                    sec_data = sec_res.json()
            except Exception as e:
                # Log section warning and continue
                continue

            metadata = sec_data.get("MediaContainer", {}).get("Metadata", [])
            for item in metadata:
                rating_key = item.get("ratingKey")
                title = item.get("title", "")
                year = item.get("year")
                
                # Extract IMDb ID if present in the metadata Guids array
                imdb_id = None
                guids = item.get("Guid", [])
                for g in guids:
                    guid_id = g.get("id", "")
                    if guid_id.startswith("imdb://"):
                        imdb_id = guid_id.replace("imdb://", "")
                        break

                # Resolve media file path details
                file_path = None
                size_bytes = None
                media_list = item.get("Media", [])
                if media_list:
                    parts = media_list[0].get("Part", [])
                    if parts:
                        file_path = parts[0].get("file")
                        size_bytes = parts[0].get("size")

                movies.append({
                    "id": f"plex_{rating_key}",
                    "source": "plex",
                    "rating_key": str(rating_key),
                    "title": title,
                    "year": int(year) if year else None,
                    "imdb_id": imdb_id,
                    "file_path": file_path,
                    "size_bytes": int(size_bytes) if size_bytes is not None else None
                })

        return movies

    async def fetch_movie_details(self, rating_key: str) -> Optional[Dict[str, Any]]:
        """
        Fetches detailed metadata for a specific item on Plex using its rating key.
        """
        if not self.token:
            raise ValueError("PLEX_TOKEN is not configured.")

        endpoint = f"{self.url}/library/metadata/{rating_key}"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(endpoint, headers=self._get_headers(), timeout=10.0)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            return None

        metadata = data.get("MediaContainer", {}).get("Metadata", [])
        if not metadata:
            return None

        item = metadata[0]
        title = item.get("title", "")
        year = item.get("year")
        
        # Extract IMDb ID if present in the metadata Guids array
        imdb_id = None
        guids = item.get("Guid", [])
        for g in guids:
            guid_id = g.get("id", "")
            if guid_id.startswith("imdb://"):
                imdb_id = guid_id.replace("imdb://", "")
                break

        # Resolve media file path details
        file_path = None
        size_bytes = None
        media_list = item.get("Media", [])
        if media_list:
            parts = media_list[0].get("Part", [])
            if parts:
                file_path = parts[0].get("file")
                size_bytes = parts[0].get("size")

        return {
            "id": f"plex_{rating_key}",
            "source": "plex",
            "rating_key": str(rating_key),
            "title": title,
            "year": int(year) if year else None,
            "imdb_id": imdb_id,
            "file_path": file_path,
            "size_bytes": int(size_bytes) if size_bytes is not None else None
        }

