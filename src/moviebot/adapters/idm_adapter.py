import sys
import subprocess
from pathlib import Path
from typing import Dict, Any
import httpx
from moviebot.config import settings


class IdmAdapter:
    def __init__(self):
        self.bridge_url = settings.idm_bridge_url.rstrip('/')
        self.bridge_secret = settings.idm_bridge_secret
        self.local_idm_exe = r"C:\Program Files (x86)\Internet Download Manager\IDMan.exe"

    async def send_to_idm(
        self,
        download_url: str,
        output_folder: str,
        file_name: str,
        dry_run: bool = False
    ) -> Dict[str, Any]:
        """
        Routes the download request to Internet Download Manager (IDM).
        Tries the HTTP bridge first, falling back to local subprocess if on Windows.
        """
        payload = {
            "url": download_url,
            "output_dir": output_folder,
            "filename": file_name,
            "dry_run": dry_run
        }

        # 1. Attempt Bridge Routing (if configured)
        if self.bridge_url and self.bridge_secret:
            try:
                headers = {
                    "X-Bridge-Secret": self.bridge_secret,
                    "Content-Type": "application/json"
                }
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.bridge_url}/downloads",
                        json=payload,
                        headers=headers,
                        timeout=5.0
                    )
                    if response.status_code == 200:
                        return {
                            "routed_via": "bridge",
                            "status": "success",
                            "message": f"Successfully queued via IDM Bridge: {file_name}",
                            "details": response.json()
                        }
            except Exception as e:
                # Log and fall through to local fallback
                pass

        # 2. Local Fallback (if running on Windows host directly)
        if sys.platform == "win32" and Path(self.local_idm_exe).exists():
            # IDM Flags:
            # /d link - Download a file
            # /p folder - Define local destination folder
            # /f file - Define local filename
            # /q - Start download immediately and close dialog
            # /n - Non-interactive/silent download mode
            args = [
                self.local_idm_exe,
                "/d", download_url,
                "/p", output_folder,
                "/f", file_name,
                "/n",
                "/q"
            ]
            
            if dry_run:
                return {
                    "routed_via": "local_subprocess_dryrun",
                    "status": "dry_run",
                    "message": f"[Dry-Run] Subprocess would run: {' '.join(args)}"
                }
                
            try:
                subprocess.Popen(args)
                return {
                    "routed_via": "local_subprocess",
                    "status": "success",
                    "message": f"Successfully launched local IDM process for: {file_name}"
                }
            except Exception as e:
                raise RuntimeError(f"Failed to execute local IDMan.exe subprocess: {str(e)}")

        # 3. No connection / invalid host platform
        if dry_run:
            return {
                "routed_via": "none_dryrun",
                "status": "dry_run",
                "message": f"[Dry-Run] Queue request: {file_name}"
            }
            
        raise ConnectionError(
            "IDM is unreachable. Neither the Host-side HTTP Bridge nor a local Windows IDM installation was found."
        )
