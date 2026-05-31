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

    def _parse_metadata_item(self, item: Dict[str, Any]) -> Dict[str, Any]:
        import json
        import hashlib
        import datetime
        
        rating_key = item.get("ratingKey")
        title = item.get("title", "")
        year = item.get("year")
        
        # Extract IMDb ID
        imdb_id = None
        guids = item.get("Guid", [])
        for g in guids:
            guid_id = g.get("id", "")
            if guid_id.startswith("imdb://"):
                imdb_id = guid_id.replace("imdb://", "")
                break
                
        # Resolve media details
        file_path = None
        size_bytes = None
        resolution = None
        bitrate_kbps = None
        media_list = item.get("Media", [])
        if media_list:
            media = media_list[0]
            resolution = media.get("videoResolution")
            bitrate_kbps = media.get("bitrate")
            parts = media.get("Part", [])
            if parts:
                file_path = parts[0].get("file")
                size_bytes = parts[0].get("size")
                
        # Extract new fields
        genres = json.dumps([g.get("tag") for g in item.get("Genre", []) if g.get("tag")])
        directors = json.dumps([d.get("tag") for d in item.get("Director", []) if d.get("tag")])
        collections = json.dumps([c.get("tag") for c in item.get("Collection", []) if c.get("tag")])
        
        rating = item.get("rating")
        if rating is not None:
            try:
                rating = float(rating)
            except (ValueError, TypeError):
                rating = None
                
        duration = item.get("duration")
        runtime = int(duration / 60000) if duration else None
        
        view_count = int(item.get("viewCount", 0))
        watch_status = "watched" if view_count > 0 else "unwatched"
        
        last_viewed_at = item.get("lastViewedAt")
        last_viewed_iso = None
        if last_viewed_at:
            try:
                last_viewed_iso = datetime.datetime.fromtimestamp(int(last_viewed_at), tz=datetime.timezone.utc).isoformat()
            except Exception:
                pass
                
        synopsis = item.get("summary")
        synopsis_hash = None
        if synopsis:
            synopsis_hash = hashlib.sha256(synopsis.encode("utf-8")).hexdigest()
            
        return {
            "id": f"plex_{rating_key}",
            "source": "plex",
            "rating_key": str(rating_key) if rating_key is not None else None,
            "title": title,
            "year": int(year) if year else None,
            "imdb_id": imdb_id,
            "file_path": file_path,
            "size_bytes": int(size_bytes) if size_bytes is not None else None,
            "genres": genres,
            "directors": directors,
            "rating": rating,
            "runtime": runtime,
            "collections": collections,
            "resolution": resolution,
            "bitrate_kbps": int(bitrate_kbps) if bitrate_kbps is not None else None,
            "watch_status": watch_status,
            "watch_count": view_count,
            "last_watched_at": last_viewed_iso,
            "synopsis": synopsis,
            "synopsis_hash": synopsis_hash
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
                movies.append(self._parse_metadata_item(item))

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

        return self._parse_metadata_item(metadata[0])

    async def unmatch_item(self, rating_key: str) -> bool:
        """
        Breaks the metadata match for a specific library item.
        """
        if not self.token:
            raise ValueError("PLEX_TOKEN is not configured.")

        endpoint = f"{self.url}/library/metadata/{rating_key}/unmatch"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(endpoint, headers=self._get_headers(), timeout=10.0)
                response.raise_for_status()
                return True
        except Exception as e:
            # We can log or raise, returning False indicates failure
            return False

    async def get_matches(self, rating_key: str) -> List[Dict[str, Any]]:
        """
        Queries Plex's metadata search service to get potential match candidates for an item.
        """
        if not self.token:
            raise ValueError("PLEX_TOKEN is not configured.")

        endpoint = f"{self.url}/library/metadata/{rating_key}/matches"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(endpoint, headers=self._get_headers(), timeout=10.0)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            return []

        results = data.get("MediaContainer", {}).get("SearchResult", [])
        match_candidates = []
        for r in results:
            match_candidates.append({
                "guid": r.get("guid"),
                "name": r.get("name"),
                "year": r.get("year"),
                "score": r.get("score")
            })
        return match_candidates

    async def match_item(self, rating_key: str, guid: str, name: str) -> bool:
        """
        Applies a chosen metadata match (GUID) to a specific library item.
        """
        if not self.token:
            raise ValueError("PLEX_TOKEN is not configured.")

        endpoint = f"{self.url}/library/metadata/{rating_key}/match"
        params = {
            "guid": guid,
            "name": name
        }
        try:
            async with httpx.AsyncClient() as client:
                response = await client.put(endpoint, headers=self._get_headers(), params=params, timeout=10.0)
                response.raise_for_status()
                return True
        except Exception as e:
            return False

    async def search_movie(self, title: str, year: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Searches all movie library sections for a movie with a matching title and optional year.
        """
        if not self.token:
            return []

        # 1. Fetch library sections to find movie sections
        sections_endpoint = f"{self.url}/library/sections"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(sections_endpoint, headers=self._get_headers(), timeout=5.0)
                response.raise_for_status()
                sections_data = response.json()
        except Exception:
            return []

        sections = sections_data.get("MediaContainer", {}).get("Directory", [])
        movie_sections = [s for s in sections if s.get("type") == "movie"]

        results = []
        import urllib.parse
        encoded_title = urllib.parse.quote(title)
        
        for sec in movie_sections:
            sec_id = sec.get("key")
            if not sec_id:
                continue

            search_endpoint = f"{self.url}/library/sections/{sec_id}/all?title={encoded_title}"
            try:
                async with httpx.AsyncClient() as client:
                    sec_res = await client.get(search_endpoint, headers=self._get_headers(), timeout=5.0)
                    sec_res.raise_for_status()
                    sec_data = sec_res.json()
            except Exception:
                continue

            metadata = sec_data.get("MediaContainer", {}).get("Metadata", [])
            for item in metadata:
                item_year = item.get("year")
                
                # If year is provided, filter by it
                if year and item_year and int(item_year) != year:
                    continue
                    
                results.append(self._parse_metadata_item(item))
        return results

    async def refresh_movie_sections(self) -> None:
        """
        Triggers a refresh/scan on all movie library sections to detect new files immediately.
        """
        if not self.token:
            return

        sections_endpoint = f"{self.url}/library/sections"
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(sections_endpoint, headers=self._get_headers(), timeout=5.0)
                response.raise_for_status()
                sections_data = response.json()
        except Exception:
            return

        sections = sections_data.get("MediaContainer", {}).get("Directory", [])
        movie_sections = [s for s in sections if s.get("type") == "movie"]

        for sec in movie_sections:
            sec_id = sec.get("key")
            if not sec_id:
                continue

            refresh_endpoint = f"{self.url}/library/sections/{sec_id}/refresh"
            try:
                async with httpx.AsyncClient() as client:
                    await client.get(refresh_endpoint, headers=self._get_headers(), timeout=5.0)
            except Exception:
                pass


