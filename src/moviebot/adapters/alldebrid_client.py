from typing import List, Dict, Any
import httpx
from moviebot.config import settings


class AllDebridClient:
    def __init__(self):
        self.api_key = settings.alldebrid_api_key
        self.base_url = "https://api.alldebrid.com/v4.1"
        self.agent = "moviebot"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}"
        }

    async def instant_check(self, hashes: List[str]) -> Dict[str, Any]:
        """Checks cache status of infohashes against AllDebrid."""
        if not self.api_key:
            raise ValueError("ALLDEBRID_API_KEY is not configured.")

        # API expects: /v4.1/magnet/instant?magnets[]=hash1&magnets[]=hash2...
        params = {
            "agent": self.agent,
            "apikey": self.api_key,
        }
        
        # We append magnets directly to the query string to support array keys
        query_parts = [f"magnets[]={h}" for h in hashes]
        query_string = "&".join(query_parts)
        url = f"{self.base_url}/magnet/instant?agent={self.agent}&apikey={self.api_key}&{query_string}"

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=10.0)
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("status") == "success":
                return res_json.get("data", {})
            raise RuntimeError(f"AllDebrid error: {res_json.get('error', {}).get('message', 'Unknown error')}")

    async def upload_magnet(self, magnet_link: str) -> Dict[str, Any]:
        """Uploads a magnet link to AllDebrid."""
        if not self.api_key:
            raise ValueError("ALLDEBRID_API_KEY is not configured.")

        url = f"{self.base_url}/magnet/upload"
        params = {
            "agent": self.agent,
            "apikey": self.api_key,
            "magnets[]": magnet_link
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("status") == "success":
                magnets = res_json.get("data", {}).get("magnets", [])
                if magnets:
                    magnet_info = magnets[0]
                    if isinstance(magnet_info, dict) and magnet_info.get("error"):
                        err_msg = magnet_info["error"].get("message") or "Unknown magnet upload error"
                        raise RuntimeError(f"AllDebrid magnet upload error: {err_msg}")
                    return magnet_info
                raise RuntimeError("No magnets returned in AllDebrid upload response.")
            raise RuntimeError(f"AllDebrid error: {res_json.get('error', {}).get('message', 'Unknown error')}")

    async def get_magnet_status(self, id: str) -> Dict[str, Any]:
        """Retrieves status of an active magnet download."""
        if not self.api_key:
            raise ValueError("ALLDEBRID_API_KEY is not configured.")

        url = f"{self.base_url}/magnet/status"
        params = {
            "agent": self.agent,
            "apikey": self.api_key,
            "id": id
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("status") == "success":
                magnets = res_json.get("data", {}).get("magnets", [])
                # If queried with a single ID, magnets is a dict or single-item list
                if isinstance(magnets, list) and magnets:
                    magnet_info = magnets[0]
                elif isinstance(magnets, dict):
                    magnet_info = magnets
                else:
                    magnet_info = res_json.get("data", {})

                if isinstance(magnet_info, dict) and magnet_info.get("error"):
                    err_msg = magnet_info["error"].get("message") or "Unknown magnet status error"
                    raise RuntimeError(f"AllDebrid magnet error: {err_msg}")
                return magnet_info
            raise RuntimeError(f"AllDebrid error: {res_json.get('error', {}).get('message', 'Unknown error')}")

    async def get_magnet_files(self, id: str) -> List[Dict[str, Any]]:
        """Retrieves and flattens files of a ready magnet using AllDebrid v4.1."""
        if not self.api_key:
            raise ValueError("ALLDEBRID_API_KEY is not configured.")

        url = f"{self.base_url}/magnet/files"
        params = {
            "agent": self.agent,
            "apikey": self.api_key,
        }
        data = {
            "id[]": [id]
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, params=params, data=data, timeout=10.0)
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("status") == "success":
                magnets = res_json.get("data", {}).get("magnets", [])
                if magnets and isinstance(magnets, list):
                    files_tree = magnets[0].get("files", [])
                    flat_list = self._flatten_files(files_tree)
                    # Assign a 1-based sequential ID to each file to match expected format
                    for idx, f in enumerate(flat_list, start=1):
                        f["id"] = idx
                    return flat_list
                return []
            raise RuntimeError(f"AllDebrid error: {res_json.get('error', {}).get('message', 'Unknown error')}")

    def _flatten_files(self, elements: List[Dict[str, Any]], current_path: str = "") -> List[Dict[str, Any]]:
        """Recursively flattens AllDebrid v4.1 hierarchical files tree."""
        flat = []
        for el in elements:
            name = el.get("n")
            if not name:
                continue
            if "e" in el:
                # Directory
                subdir = f"{current_path}/{name}" if current_path else name
                flat.extend(self._flatten_files(el["e"], subdir))
            else:
                # File
                flat.append({
                    "name": name,
                    "size": el.get("s", 0),
                    "link": el.get("l"),
                    "path": f"{current_path}/{name}" if current_path else name
                })
        return flat

    async def unlock_link(self, link: str) -> str:
        """Unlocks a debrid link to resolve direct download streaming URL."""
        if not self.api_key:
            raise ValueError("ALLDEBRID_API_KEY is not configured.")

        url = f"{self.base_url}/link/unlock"
        params = {
            "agent": self.agent,
            "apikey": self.api_key,
            "link": link
        }

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("status") == "success":
                return res_json.get("data", {}).get("link", "")
            raise RuntimeError(f"AllDebrid error: {res_json.get('error', {}).get('message', 'Unknown error')}")

