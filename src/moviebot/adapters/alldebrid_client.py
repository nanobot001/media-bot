from typing import List, Dict, Any, Optional, Set, Tuple
import httpx
import re
import logging
from moviebot.config import settings


logger = logging.getLogger(__name__)


class AllDebridProbeCleanupError(RuntimeError):
    """A newly-created probe could not be cleaned up safely."""

    code = "PROBE_CLEANUP_FAILED"
    retryable = True


class AllDebridClient:
    def __init__(self):
        self.api_key = settings.alldebrid_api_key
        self.base_url = "https://api.alldebrid.com/v4.1"
        self.agent = "moviebot"

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}"
        }

    @staticmethod
    def _magnet_identities(value: Any) -> Set[str]:
        """Return stable hash/magnet identities without retaining private URLs."""
        text = str(value or "").strip().lower()
        if not text:
            return set()
        identities = {text}
        match = re.search(r"btih:([a-z0-9]+)", text, re.IGNORECASE)
        if match:
            identities.add(match.group(1).lower())
        return identities

    async def _get_provider_magnets(self) -> Optional[List[Dict[str, Any]]]:
        """Fetch provider state; None means ownership preflight is unknown."""
        if not self.api_key or self.api_key.lower() == "mock":
            return []
        url = f"{self.base_url}/magnet/status"
        params = {"agent": self.agent, "apikey": self.api_key}
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, timeout=10.0)
                response.raise_for_status()
                payload = response.json()
            if payload.get("status") != "success":
                return None
            magnets = payload.get("data", {}).get("magnets", [])
            if isinstance(magnets, dict):
                magnets = [magnets]
            return [m for m in magnets if isinstance(m, dict)]
        except Exception:
            return None

    @classmethod
    def _probe_ownership(cls, before: Optional[List[Dict[str, Any]]]) -> Tuple[Set[str], Set[str], bool]:
        """Build known provider IDs/identities and whether the snapshot is trustworthy."""
        if before is None:
            return set(), set(), False
        known_ids = {str(item.get("id")) for item in before if item.get("id") is not None}
        known_identity_values: Set[str] = set()
        for item in before:
            known_identity_values.update(cls._magnet_identities(item.get("hash")))
            known_identity_values.update(cls._magnet_identities(item.get("magnet")))
        return known_ids, known_identity_values, True

    @classmethod
    def _is_probe_owned(
        cls,
        magnet_info: Dict[str, Any],
        known_ids: Set[str],
        known_identities: Set[str],
        snapshot_known: bool,
    ) -> bool:
        if not snapshot_known:
            return False
        provider_id = str(magnet_info.get("id") or "")
        if not provider_id or provider_id in known_ids:
            return False
        identities = set()
        identities.update(cls._magnet_identities(magnet_info.get("hash")))
        identities.update(cls._magnet_identities(magnet_info.get("magnet")))
        if not identities:
            return False
        return not identities.intersection(known_identities)

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

        # Chunk cleaned magnets into batches of 20 to prevent URL length limit errors
        chunk_size = 20
        all_out = []
        cleanup_errors = []

        async with httpx.AsyncClient() as client:
            for i in range(0, len(cleaned_magnets), chunk_size):
                chunk = cleaned_magnets[i:i + chunk_size]
                provider_before = await self._get_provider_magnets()
                known_ids, known_identities, snapshot_known = self._probe_ownership(provider_before)
                url = f"{self.base_url}/magnet/upload"
                params = [("agent", self.agent), ("apikey", self.api_key)] + [("magnets[]", m) for m in chunk]

                try:
                    response = await client.get(url, params=params, timeout=15.0)
                    response.raise_for_status()
                    res_json = response.json()
                except Exception as e:
                    logger.warning("[AllDebrid instant_check] Error on chunk %d-%d: %s", i, i + len(chunk), e)
                    continue

                # Handle account limit auto-recovery
                if res_json.get("status") == "error" and res_json.get("error", {}).get("code") == "MAGNET_TOO_MANY_ACTIVE":
                    try:
                        status_url = f"{self.base_url}/magnet/status"
                        st_res = await client.get(status_url, params={"agent": self.agent, "apikey": self.api_key})
                        st_data = st_res.json().get("data", {}).get("magnets", [])
                        # Provider-wide queue cleanup is unsafe here: these
                        # magnets may belong to another caller. Retry the
                        # request without deleting account-wide state.
                        response = await client.get(url, params=params, timeout=15.0)
                        response.raise_for_status()
                        res_json = response.json()
                    except Exception:
                        pass

                if res_json.get("status") == "success":
                    data_magnets = res_json.get("data", {}).get("magnets", [])
                    for m in data_magnets:
                        if isinstance(m, dict):
                            is_ready = bool(m.get("ready", False))
                            m_id = m.get("id")
                            all_out.append({
                                "magnet": m.get("magnet", ""),
                                "hash": (m.get("hash") or "").lower(),
                                "instant": is_ready,
                                "ready": is_ready,
                                "id": m_id
                            })

                            if (
                                m_id
                                and not is_ready
                                and self._is_probe_owned(
                                    m, known_ids, known_identities, snapshot_known
                                )
                            ):
                                try:
                                    deleted = await self.delete_cloud_transfer(str(m_id))
                                    if not deleted:
                                        raise RuntimeError("provider did not confirm deletion")
                                except Exception:
                                    cleanup_errors.append({
                                        "code": "PROBE_CLEANUP_FAILED",
                                        "transfer_id": str(m_id),
                                        "retryable": True,
                                    })
                                    logger.warning("Unable to clean up owned AllDebrid probe magnet")

        return {"magnets": all_out, "cleanup_errors": cleanup_errors}

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

    async def unlock_magnet_stream(
        self,
        magnet_link: str,
        file_id: Optional[int] = None,
        season: Optional[int] = None,
        episode: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Unlocks an instant-cached magnet to resolve a direct video streaming URL,
        matching requested season/episode or largest video file.
        """
        if not self.api_key or self.api_key.lower() == "mock":
            return {
                "stream_url": "https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
                "filename": "Mock.Stream.Video.1080p.mkv",
                "filesize": 1073741824,
                "mime_type": "video/mp4",
                "file_id": 1,
                "all_files": [
                    {"id": 1, "name": "Mock.Stream.Video.1080p.mkv", "size": 1073741824, "is_video": True}
                ],
                "subtitles": []
            }

        # 1. Upload/check magnet on AllDebrid.  The preflight snapshot is the
        # ownership boundary for any cleanup on an unready probe.
        provider_before = await self._get_provider_magnets()
        known_ids, known_identities, snapshot_known = self._probe_ownership(provider_before)
        magnet_info = await self.upload_magnet(magnet_link)
        magnet_id = str(magnet_info.get("id") or "")
        if not magnet_id:
            raise RuntimeError("Failed to obtain AllDebrid magnet ID for streaming.")

        is_ready = bool(magnet_info.get("ready", False))
        if not is_ready:
            if self._is_probe_owned(
                magnet_info, known_ids, known_identities, snapshot_known
            ):
                try:
                    deleted = await self.delete_cloud_transfer(magnet_id)
                    if not deleted:
                        raise RuntimeError("provider did not confirm deletion")
                except Exception as cleanup_error:
                    raise AllDebridProbeCleanupError(
                        "The unready browser probe was created by this request, "
                        f"but cleanup failed: {cleanup_error}"
                    ) from cleanup_error
            raise ValueError(f"Torrent '{magnet_info.get('name') or 'release'}' is not instant-cached on AllDebrid yet.")

        # 2. Get files tree
        files = await self.get_magnet_files(magnet_id)
        if not files:
            raise RuntimeError("No files found in torrent payload for streaming.")

        video_extensions = (".mkv", ".mp4", ".avi", ".mov", ".m4v", ".webm", ".ts")
        sub_extensions = (".srt", ".vtt", ".sub", ".ass")

        video_files = []
        sub_files = []
        for f in files:
            fn_lower = f["name"].lower()
            if fn_lower.endswith(video_extensions):
                f["is_video"] = True
                video_files.append(f)
            elif fn_lower.endswith(sub_extensions):
                f["is_sub"] = True
                sub_files.append(f)

        if not video_files:
            raise RuntimeError("No playable video files found in torrent archive.")

        # 3. Select target video file
        chosen_file = None
        if file_id is not None:
            for vf in video_files:
                if vf.get("id") == file_id:
                    chosen_file = vf
                    break

        if not chosen_file and season is not None and episode is not None:
            pattern = re.compile(rf's0*{season}e0*{episode}\b|\b{season}x0*{episode}\b', re.IGNORECASE)
            for vf in video_files:
                if pattern.search(vf["name"]):
                    chosen_file = vf
                    break

        if not chosen_file:
            chosen_file = max(video_files, key=lambda x: x.get("size", 0))

        # 4. Unlock direct stream URL
        stream_link = chosen_file.get("link")
        if not stream_link:
            raise RuntimeError(f"File '{chosen_file['name']}' does not contain an AllDebrid download link.")

        direct_stream_url = await self.unlock_link(stream_link)

        # 5. Unlock subtitle links if available
        unlocked_subs = []
        for sf in sub_files[:5]:
            if sf.get("link"):
                try:
                    s_url = await self.unlock_link(sf["link"])
                    unlocked_subs.append({
                        "name": sf["name"],
                        "url": s_url,
                        "lang": "en" if "eng" in sf["name"].lower() or "en." in sf["name"].lower() else "und"
                    })
                except Exception:
                    pass

        fn = chosen_file["name"]
        mime = "video/mp4" if fn.lower().endswith(".mp4") else "video/x-matroska"

        return {
            "stream_url": direct_stream_url,
            "filename": fn,
            "filesize": chosen_file.get("size", 0),
            "mime_type": mime,
            "file_id": chosen_file.get("id"),
            "provider_magnet_id": magnet_id,
            "probe_created": self._is_probe_owned(
                magnet_info, known_ids, known_identities, snapshot_known
            ),
            "subtitles": unlocked_subs,
            "all_files": [
                {
                    "id": f["id"],
                    "name": f["name"],
                    "size": f["size"],
                    "is_video": f.get("is_video", False)
                }
                for f in files if f.get("is_video")
            ]
        }

    async def cache_to_cloud(self, magnet_link: str) -> Dict[str, Any]:
        """
        Uploads an uncached magnet to AllDebrid cloud queue for background downloading.
        Leaves the download in cloud queue so it finishes in AllDebrid storage.
        """
        if not self.api_key or self.api_key.lower() == "mock":
            return {"id": "mock-cloud-id-123", "name": "Mock Cloud Download", "status": "Downloading", "ready": False}

        magnet_info = await self.upload_magnet(magnet_link)
        return {
            "id": magnet_info.get("id"),
            "name": magnet_info.get("name") or magnet_info.get("filename"),
            "status": magnet_info.get("status") or ("Ready" if magnet_info.get("ready") else "Downloading"),
            "ready": bool(magnet_info.get("ready", False)),
            "size": magnet_info.get("size", 0)
        }

    async def get_cloud_transfers(self) -> List[Dict[str, Any]]:
        """Retrieves active cloud downloads from AllDebrid with progress %, speed, and ETA."""
        if not self.api_key or self.api_key.lower() == "mock":
            return [
                {
                    "id": "mock-transfer-1",
                    "name": "Dune.Part.Two.2024.1080p.WEBRip",
                    "status": "Downloading",
                    "status_code": 2,
                    "ready": False,
                    "size": 5368709120,
                    "downloaded": 2684354560,
                    "progress_percent": 50.0,
                    "speed": 15728640,
                    "speed_formatted": "15.0 MB/s",
                    "size_formatted": "5.00 GB",
                    "downloaded_formatted": "2.50 GB",
                    "seeders": 48,
                    "eta_seconds": 170,
                    "eta_formatted": "~2m 50s remaining",
                    "stage_label": "Downloading from Swarm"
                }
            ]

        url = f"{self.base_url}/magnet/status"
        params = {"agent": self.agent, "apikey": self.api_key}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            res_json = response.json()
            if res_json.get("status") == "success":
                magnets = res_json.get("data", {}).get("magnets", [])
                out = []
                for m in magnets:
                    if isinstance(m, dict):
                        status_code = m.get("statusCode", 0)
                        is_ready = status_code == 4 or bool(m.get("ready"))
                        size = m.get("size", 0) or 0
                        downloaded = m.get("downloaded", 0) or 0
                        speed = m.get("downloadSpeed", 0) or 0
                        seeders = m.get("seeders", 0) or 0

                        pct = 0.0
                        if is_ready:
                            pct = 100.0
                        elif size > 0:
                            pct = min(99.9, round((downloaded / size) * 100, 1))

                        eta_sec = 0
                        eta_fmt = "Ready" if is_ready else "Calculating..."
                        if not is_ready and speed > 0 and size > downloaded:
                            eta_sec = max(0, int((size - downloaded) / speed))
                            if eta_sec < 60:
                                eta_fmt = f"~{eta_sec}s remaining"
                            elif eta_sec < 3600:
                                eta_fmt = f"~{eta_sec // 60}m {eta_sec % 60}s remaining"
                            else:
                                eta_fmt = f"~{eta_sec // 3600}h {(eta_sec % 3600) // 60}m remaining"

                        # Stage label
                        stage_map = {
                            0: "Contacting P2P Trackers",
                            1: "In Cloud Queue",
                            2: "Downloading from Swarm",
                            3: "Moving to High-Speed Cloud RAM",
                            4: "Ready in Cloud (⚡ Instant Cached)"
                        }
                        stage_label = stage_map.get(status_code, "Downloading from Swarm" if not is_ready else "Ready in Cloud")

                        speed_fmt = "0 KB/s"
                        if speed >= 1048576:
                            speed_fmt = f"{speed / 1048576:.1f} MB/s"
                        elif speed >= 1024:
                            speed_fmt = f"{speed / 1024:.0f} KB/s"

                        size_fmt = f"{size / 1073741824:.2f} GB" if size >= 1073741824 else f"{size / 1048576:.1f} MB"
                        dl_fmt = f"{downloaded / 1073741824:.2f} GB" if downloaded >= 1073741824 else f"{downloaded / 1048576:.1f} MB"

                        out.append({
                            "id": m.get("id"),
                            "name": m.get("filename") or m.get("name") or "Unknown Media",
                            "status": m.get("status") or ("Ready" if is_ready else "Downloading"),
                            "status_code": status_code,
                            "ready": is_ready,
                            "size": size,
                            "size_formatted": size_fmt,
                            "downloaded": downloaded,
                            "downloaded_formatted": dl_fmt,
                            "progress_percent": pct,
                            "speed": speed,
                            "speed_formatted": speed_fmt,
                            "seeders": seeders,
                            "eta_seconds": eta_sec,
                            "eta_formatted": eta_fmt,
                            "stage_label": stage_label
                        })
                return out
            return []

    async def delete_cloud_transfer(self, id: str) -> bool:
        """Deletes a magnet transfer from AllDebrid cloud queue."""
        if not self.api_key or self.api_key.lower() == "mock":
            return True

        url = f"{self.base_url}/magnet/delete"
        params = {"agent": self.agent, "apikey": self.api_key, "id": id}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            res_json = response.json()
            return res_json.get("status") == "success"


