import datetime
import os
from typing import Dict, Any, Optional, List
from moviebot.core.dedupe import normalize_title
from moviebot.db.repositories import LibraryItemRepository, DownloadJobRepository
from moviebot.config import settings
from moviebot.adapters.alldebrid_client import AllDebridClient

async def check_movie_state_tool(title: str, year: Optional[int] = None) -> Dict[str, Any]:
    """
    Tracks a movie's lifecycle status across Plex, AllDebrid, IDM, file storage, and FileBot logs.
    """
    tool_name = "check_movie_state_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        norm_title = normalize_title(title)
        
        # 1. Plex Database Mirror Search
        db_matches = LibraryItemRepository.search_by_normalized_title(norm_title)
        if year:
            db_matches = [m for m in db_matches if m.get("year") == year]
        
        plex_matches = []
        for m in db_matches:
            plex_matches.append({
                "title": m["title"],
                "year": m["year"],
                "imdb_id": m.get("imdb_id"),
                "file_path": m.get("file_path"),
                "size_bytes": m.get("size_bytes")
            })

        # 2. Local Download Jobs & AllDebrid Status
        jobs = DownloadJobRepository.search_by_title(title)
        jobs_info = []
        for job in jobs:
            job_info = {
                "id": job["id"],
                "status": job["status"],
                "selected_file_name": job["selected_file_name"],
                "alldebrid_magnet_id": job["alldebrid_magnet_id"],
                "created_at": job["created_at"],
                "alldebrid_status": None,
                "alldebrid_error": None
            }
            magnet_id = job.get("alldebrid_magnet_id")
            if magnet_id and magnet_id != "None" and job["status"] in ("pending", "downloading", "requires_selection"):
                try:
                    ad = AllDebridClient()
                    status_res = await ad.get_magnet_status(magnet_id)
                    job_info["alldebrid_status"] = status_res
                except Exception as e:
                    job_info["alldebrid_error"] = str(e)
            jobs_info.append(job_info)

        # 3. Intake Storage (F:\_temp\movies)
        intake_dir = settings.output_dir or r"F:\_temp\movies"
        intake_matches = []
        if os.path.exists(intake_dir):
            try:
                for entry in os.scandir(intake_dir):
                    if norm_title in normalize_title(entry.name):
                        full_path = os.path.join(intake_dir, entry.name)
                        is_dir = entry.is_dir()
                        size = None
                        if not is_dir:
                            size = entry.stat().st_size
                        intake_matches.append({
                            "name": entry.name,
                            "path": full_path,
                            "is_dir": is_dir,
                            "size_bytes": size
                        })
            except Exception:
                pass

        # 4. Destination Storage (F:\Media)
        dest_dir = r"F:\Media"
        dest_matches = []
        if os.path.exists(dest_dir):
            try:
                # Walk F:\Media max 2 levels deep to prevent slow scans
                for root, dirs, files in os.walk(dest_dir):
                    # Compute current depth relative to dest_dir
                    depth = root[len(dest_dir):].count(os.path.sep)
                    if depth > 2:
                        # Clear dirs to prevent walking deeper
                        dirs.clear()
                        continue
                    
                    for name in dirs + files:
                        if norm_title in normalize_title(name):
                            full_path = os.path.join(root, name)
                            dest_matches.append({
                                "name": name,
                                "path": full_path,
                                "is_dir": os.path.isdir(full_path),
                                "size_bytes": os.path.getsize(full_path) if os.path.isfile(full_path) else None
                            })
            except Exception:
                pass

        # 5. FileBot Watcher Logs (media-watcher.log)
        log_path = r"c:\Users\antho\Code\media-watcher\logs\media-watcher.log"
        watcher_matches = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r", encoding="utf-8-sig") as f:
                    for line in f:
                        if norm_title in normalize_title(line):
                            watcher_matches.append(line.strip())
            except Exception:
                try:
                    with open(log_path, "r", encoding="latin-1") as f:
                        for line in f:
                            if norm_title in normalize_title(line):
                                watcher_matches.append(line.strip())
                except Exception:
                    pass
        
        # Format watcher matches to last 10 lines
        watcher_matches = watcher_matches[-10:]

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "in_plex": len(plex_matches) > 0,
                "plex_matches": plex_matches,
                "jobs": jobs_info,
                "intake_files": intake_matches,
                "destination_files": dest_matches,
                "watcher_logs": watcher_matches
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "CHECK_MOVIE_STATE_FAILED",
                "message": f"Error checking movie state: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
