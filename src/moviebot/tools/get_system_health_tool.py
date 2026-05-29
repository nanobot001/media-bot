import datetime
import os
import shutil
import subprocess
import json
import httpx
from typing import Dict, Any
from moviebot.config import settings

async def get_system_health_tool() -> Dict[str, Any]:
    """
    Monitor stack connectivity, PM2 process states, and disk/mount availability.
    """
    tool_name = "get_system_health_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    health_report = {
        "disks": {},
        "pm2": {},
        "services": {}
    }

    # 1. Disk & Mount Health Check
    for drive_name, path in [("C", "C:\\"), ("F", "F:\\")]:
        if os.path.exists(path):
            try:
                total, used, free = shutil.disk_usage(path)
                test_file = os.path.join(path, f".health_check_temp_{int(datetime.datetime.utcnow().timestamp())}")
                writeable = False
                try:
                    with open(test_file, "w") as f:
                        f.write("health_check")
                    os.remove(test_file)
                    writeable = True
                except Exception:
                    pass

                health_report["disks"][drive_name] = {
                    "path": path,
                    "exists": True,
                    "total_gb": round(total / (1024**3), 1),
                    "used_gb": round(used / (1024**3), 1),
                    "free_gb": round(free / (1024**3), 1),
                    "percent_free": round((free / total) * 100, 1) if total else 0,
                    "writeable": writeable
                }
            except Exception as e:
                health_report["disks"][drive_name] = {
                    "path": path,
                    "exists": True,
                    "error": str(e),
                    "writeable": False
                }
        else:
            health_report["disks"][drive_name] = {
                "path": path,
                "exists": False,
                "writeable": False
            }

    # 2. PM2 Process Health Check
    try:
        res = subprocess.run(["pm2", "jlist"], shell=True, capture_output=True, text=True)
        if res.returncode == 0:
            stdout = res.stdout.strip()
            start = stdout.find('[')
            end = stdout.rfind(']')
            if start != -1 and end != -1:
                stdout = stdout[start:end+1]
            
            data = json.loads(stdout)
            processes = []
            for proc in data:
                pm2_env = proc.get("pm2_env", {})
                status = pm2_env.get("status") or proc.get("status")
                restarts = pm2_env.get("restart_time") if pm2_env.get("restart_time") is not None else proc.get("restart_time", 0)
                pm_uptime = pm2_env.get("pm_uptime") or proc.get("pm_uptime")
                processes.append({
                    "name": proc.get("name"),
                    "pm_id": proc.get("pm_id"),
                    "status": status,
                    "memory_mb": round((proc.get("monit", {}).get("memory") or 0) / (1024**2), 1),
                    "cpu_percent": proc.get("monit", {}).get("cpu", 0),
                    "restarts": restarts,
                    "uptime_sec": int((int(datetime.datetime.utcnow().timestamp() * 1000) - pm_uptime) / 1000) if pm_uptime else 0
                })
            health_report["pm2"] = {
                "ok": True,
                "processes": processes
            }
        else:
            health_report["pm2"] = {
                "ok": False,
                "error": res.stderr or "pm2 command failed"
            }
    except Exception as e:
        health_report["pm2"] = {
            "ok": False,
            "error": str(e)
        }

    # 3. External API & Integration Health Checks
    async with httpx.AsyncClient() as client:
        # Plex Connectivity
        if settings.plex_url:
            plex_url = settings.plex_url.rstrip("/")
            try:
                # Use X-Plex-Token if configured
                headers = {"Accept": "application/json"}
                if settings.plex_token:
                    headers["X-Plex-Token"] = settings.plex_token
                
                resp = await client.get(f"{plex_url}/identity", headers=headers, timeout=5.0)
                health_report["services"]["plex"] = {
                    "configured": True,
                    "connected": resp.status_code == 200,
                    "status_code": resp.status_code
                }
            except Exception as e:
                health_report["services"]["plex"] = {
                    "configured": True,
                    "connected": False,
                    "error": str(e)
                }
        else:
            health_report["services"]["plex"] = {"configured": False}

        # Tautulli Connectivity
        if settings.tautulli_url and settings.tautulli_api_key:
            tautulli_url = settings.tautulli_url.rstrip("/")
            try:
                resp = await client.get(
                    f"{tautulli_url}/api/v2",
                    params={"apikey": settings.tautulli_api_key, "cmd": "status"},
                    timeout=5.0
                )
                success = False
                if resp.status_code == 200:
                    data = resp.json()
                    success = data.get("response", {}).get("result") == "success"
                
                health_report["services"]["tautulli"] = {
                    "configured": True,
                    "connected": success,
                    "status_code": resp.status_code
                }
            except Exception as e:
                health_report["services"]["tautulli"] = {
                    "configured": True,
                    "connected": False,
                    "error": str(e)
                }
        else:
            health_report["services"]["tautulli"] = {"configured": False}

        # Prowlarr Connectivity
        if settings.prowlarr_url and settings.prowlarr_api_key:
            prowlarr_url = settings.prowlarr_url.rstrip("/")
            try:
                resp = await client.get(
                    f"{prowlarr_url}/api/v1/system/status",
                    params={"apikey": settings.prowlarr_api_key},
                    timeout=5.0
                )
                health_report["services"]["prowlarr"] = {
                    "configured": True,
                    "connected": resp.status_code == 200,
                    "status_code": resp.status_code
                }
            except Exception as e:
                health_report["services"]["prowlarr"] = {
                    "configured": True,
                    "connected": False,
                    "error": str(e)
                }
        else:
            health_report["services"]["prowlarr"] = {"configured": False}

        # AllDebrid Connectivity
        if settings.alldebrid_api_key:
            try:
                resp = await client.get(
                    "https://api.alldebrid.com/v4.1/user/links",
                    params={"agent": "moviebot", "apikey": settings.alldebrid_api_key},
                    timeout=5.0
                )
                success = False
                if resp.status_code == 200:
                    data = resp.json()
                    success = data.get("status") == "success"

                health_report["services"]["alldebrid"] = {
                    "configured": True,
                    "connected": success,
                    "status_code": resp.status_code
                }
            except Exception as e:
                health_report["services"]["alldebrid"] = {
                    "configured": True,
                    "connected": False,
                    "error": str(e)
                }
        else:
            health_report["services"]["alldebrid"] = {"configured": False}

        # IDM Bridge Connectivity
        if settings.idm_bridge_url:
            bridge_url = settings.idm_bridge_url.rstrip("/")
            try:
                resp = await client.get(f"{bridge_url}/health", timeout=3.0)
                connected = False
                if resp.status_code == 200:
                    try:
                        connected = resp.json().get("status") == "ok"
                    except Exception:
                        connected = True  # Fallback if raw text/other JSON
                
                health_report["services"]["idm_bridge"] = {
                    "configured": True,
                    "connected": connected,
                    "status_code": resp.status_code
                }
            except Exception as e:
                health_report["services"]["idm_bridge"] = {
                    "configured": True,
                    "connected": False,
                    "error": str(e)
                }
        else:
            health_report["services"]["idm_bridge"] = {"configured": False}

    return {
        "ok": True,
        "tool": tool_name,
        "timestamp": timestamp,
        "data": health_report
    }
