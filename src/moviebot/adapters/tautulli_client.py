from typing import List, Dict, Any, Optional
import httpx
from moviebot.config import settings


class TautulliClient:
    def __init__(self):
        self.url = settings.tautulli_url.rstrip('/')
        self.api_key = settings.tautulli_api_key

    async def _query(self, cmd: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Queries Tautulli API with specified command."""
        if not self.api_key:
            raise ValueError("TAUTULLI_API_KEY is not configured.")

        url = f"{self.url}/api/v2"
        query_params = {
            "apikey": self.api_key,
            "cmd": cmd
        }
        if params:
            query_params.update(params)

        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=query_params, timeout=10.0)
            response.raise_for_status()
            res_json = response.json()
            # Tautulli api returns results nested inside response -> data
            res_body = res_json.get("response", {})
            if res_body.get("result") == "success":
                return res_body.get("data", {})
            raise RuntimeError(f"Tautulli command '{cmd}' failed: {res_body.get('message', 'Unknown error')}")

    async def get_active_streams(self) -> List[Dict[str, Any]]:
        """Checks currently active streams on Plex."""
        data = await self._query("get_activity")
        return data.get("sessions", [])

    async def get_watch_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves watch history logs from Tautulli."""
        params = {"length": limit}
        data = await self._query("get_history", params)
        return data.get("data", [])
