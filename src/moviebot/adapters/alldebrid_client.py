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
        """Checks cache status of infohashes/magnets against AllDebrid v4.1."""
        if not self.api_key or self.api_key.lower() == "mock":
            return {
                "magnets": [
                    {"magnet": h, "hash": h.lower(), "instant": True, "ready": True}
                    for h in hashes
                ]
            }

        cleaned_magnets = []
        for h in hashes:
            if not h:
                continue
            if h.startswith("magnet:"):
                cleaned_magnets.append(h)
            elif len(h) in (32, 40):
                cleaned_magnets.append(f"magnet:?xt=urn:btih:{h}")
            else:
                cleaned_magnets.append(h)

        if not cleaned_magnets:
            return {"magnets": []}

        # AllDebrid v4.1 /magnet/upload accepts batch magnets[] and returns ready: True/False for instant cache
        url = f"{self.base_url}/magnet/upload"
        params = [("agent", self.agent), ("apikey", self.api_key)] + [("magnets[]", m) for m in cleaned_magnets]

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=15.0)
            response.raise_for_status()
            res_json = response.json()
            
            # Handle account limit auto-recovery
            if res_json.get("status") == "error" and res_json.get("error", {}).get("code") == "MAGNET_TOO_MANY_ACTIVE":
                try:
                    # Clean stagnant/downloading magnets from account queue
                    status_url = f"{self.base_url}/magnet/status"
                    st_res = await client.get(status_url, params={"agent": self.agent, "apikey": self.api_key})
                    st_data = st_res.json().get("data", {}).get("magnets", [])
                    unready_to_del = [m["id"] for m in st_data if m.get("id") and m.get("statusCode") != 4]
                    del_url = f"{self.base_url}/magnet/delete"
                    await asyncio.gather(*(
                        client.get(del_url, params={"agent": self.agent, "apikey": self.api_key, "id": m_id})
                        for m_id in unready_to_del[:30]
                    ), return_exceptions=True)
                    # Retry upload
                    response = await client.get(url, params=params, timeout=15.0)
                    response.raise_for_status()
                    res_json = response.json()
                except Exception:
                    pass

            if res_json.get("status") == "success":
                data_magnets = res_json.get("data", {}).get("magnets", [])
                out = []
                unready_ids = []
                for m in data_magnets:
                    if isinstance(m, dict):
                        is_ready = bool(m.get("ready", False))
                        m_id = m.get("id")
                        if m_id and not is_ready:
                            unready_ids.append(m_id)
                        out.append({
                            "magnet": m.get("magnet", ""),
                            "hash": (m.get("hash") or "").lower(),
                            "instant": is_ready,
                            "ready": is_ready,
                            "id": m_id
                        })

                # Immediately delete unready check magnets so account queue stays clean at 0/30
                if unready_ids:
                    del_url = f"{self.base_url}/magnet/delete"
                    try:
                        await asyncio.gather(*(
                            client.get(del_url, params={"agent": self.agent, "apikey": self.api_key, "id": mid})
                            for mid in unready_ids
                        ), return_exceptions=True)
                    except Exception:
                        pass

                return {"magnets": out}
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

    async def unlock_links(self, links: List[str]) -> List[str]:
        """
        Unlocks multiple debrid links in batch to resolve direct download streaming URLs.
        Handles empty inputs gracefully and maintains input ordering.
        """
        if not links:
            return []

        if not self.api_key or self.api_key.lower() == "mock":
            return [f"https://alldebrid.mock/stream/{i}" for i in range(len(links))]

        unlocked = []
        for link in links:
            if not link:
                unlocked.append("")
                continue
            try:
                direct_url = await self.unlock_link(link)
                unlocked.append(direct_url)
            except Exception:
                unlocked.append("")
        return unlocked


