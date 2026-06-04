import datetime
import json
import uuid
from typing import Dict, Any, Optional
from moviebot.config import settings
from moviebot.db.repositories import SearchResultRepository, DownloadJobRepository
from moviebot.adapters.alldebrid_client import AllDebridClient
from moviebot.adapters.idm_adapter import IdmAdapter
from moviebot.core.file_selection import select_primary_video_file


async def enqueue_download_tool(
    reference_id: str,
    dry_run: bool = False,
    selected_file_id: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Downloads torrent/magnet from Prowlarr via AllDebrid and delegates to IDM.
    """
    tool_name = "enqueue_download_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    # 1. Retrieve the cached search result
    search_record = SearchResultRepository.get_by_id(reference_id)
    if not search_record:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "SEARCH_RECORD_NOT_FOUND",
                "message": f"No cached search result found for reference ID: {reference_id}",
                "retryable": False,
                "severity": "error"
            }
        }

    try:
        raw_payload = json.loads(search_record["raw_json_payload"])
    except Exception:
        raw_payload = {}
        
    download_url = raw_payload.get("downloadUrl") or raw_payload.get("guid") or ""
    if not download_url:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "DOWNLOAD_URL_MISSING",
                "message": "No valid download URL could be resolved from cached search record.",
                "retryable": False,
                "severity": "error"
            }
        }

    try:
        # 2. Upload link to debrid layer
        debrid = AllDebridClient()
        
        if dry_run:
            # Mock debrid responses for dry_run to allow testing the downstream file heuristics and IDM routing
            magnet_id = "dry_run_magnet_id"
            files_list = [{"id": 1, "name": f"{search_record['title']}.mkv" if not search_record['title'].endswith(('.mkv', '.mp4')) else search_record['title'], "size": search_record["size_bytes"]}]
        else:
            # Real execution: upload magnet/torrent link
            upload_res = await debrid.upload_magnet(download_url)
            magnet_id = upload_res.get("id")
            
            # 3. Retrieve debrid magnet status/files
            status_res = await debrid.get_magnet_status(magnet_id)
            
            # Wait until files are ready/resolved in the torrent info (statusCode == 4)
            if status_res.get("statusCode") == 4:
                files_list = await debrid.get_magnet_files(magnet_id)
            else:
                files_list = []

            if not files_list:
                # If debrid is currently downloading the torrent metadata or files are not ready, return pending status
                job_id = str(uuid.uuid4())
                DownloadJobRepository.create_job(
                    id=job_id,
                    alldebrid_magnet_id=str(magnet_id),
                    selected_file_name="Resolving metadata...",
                    target_dir=settings.output_dir,
                    status="pending"
                )
                return {
                    "ok": True,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "data": {
                        "job_id": job_id,
                        "magnet_id": str(magnet_id),
                        "status": "pending",
                        "message": "Torrent metadata is being resolved by AllDebrid. Check status later."
                    }
                }

        # 4. Perform Heuristic File Pruning
        try:
            is_resolved, chosen_files = select_primary_video_file(files_list)
        except ValueError as ve:
            return {
                "ok": False,
                "tool": tool_name,
                "timestamp": timestamp,
                "error": {
                    "code": "FILE_SELECTION_FAILED",
                    "message": str(ve),
                    "retryable": False,
                    "severity": "error"
                }
            }

        # 5. Handle Selection Ambiguity
        selected_file = None
        if not is_resolved:
            # Multiple files exist within a 10% size window
            if selected_file_id is not None:
                # User has provided their selection
                for f in chosen_files:
                    if str(f["id"]) == str(selected_file_id):
                        selected_file = f
                        break
                if not selected_file:
                    return {
                        "ok": False,
                        "tool": tool_name,
                        "timestamp": timestamp,
                        "error": {
                            "code": "INVALID_FILE_SELECTION",
                            "message": f"Provided selected_file_id '{selected_file_id}' did not match any files in the 10% variance group.",
                            "retryable": False,
                            "severity": "error"
                        }
                    }
            else:
                # Return candidates lists for Discord drop-down selection
                return {
                    "ok": True,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "data": {
                        "status": "requires_file_selection",
                        "magnet_id": str(magnet_id),
                        "reference_id": reference_id,
                        "candidates": chosen_files,
                        "message": "Multiple large video files detected within 10% size variance. User input required."
                    }
                }
        else:
            selected_file = chosen_files[0]

        # 6. Resolve Direct Link
        if dry_run:
            unlocked_url = f"https://alldebrid.mock/dry_run_stream/{selected_file['name']}"
        else:
            # Under v4.1, the selected file's direct link is retrieved from the flattened list
            target_debrid_link = None
            for f in files_list:
                name = f.get("name") or f.get("n")
                if name == selected_file["name"]:
                    target_debrid_link = f.get("link") or f.get("l")
                    break
                    
            if not target_debrid_link:
                return {
                    "ok": False,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "error": {
                        "code": "DEBRID_LINK_RESOLUTION_FAILED",
                        "message": "Failed to map selected file to AllDebrid stream links array.",
                        "retryable": True,
                        "severity": "error"
                    }
                }

            # Unlock the debrid direct download stream link
            unlocked_url = await debrid.unlock_link(target_debrid_link)

        # 7. Queue to IDM
        idm = IdmAdapter()
        idm_res = await idm.send_to_idm(
            download_url=unlocked_url,
            output_folder=settings.output_dir,
            file_name=selected_file["name"],
            dry_run=dry_run
        )

        # 8. Record download job
        job_id = str(uuid.uuid4())
        DownloadJobRepository.create_job(
            id=job_id,
            alldebrid_magnet_id=str(magnet_id),
            selected_file_name=selected_file["name"],
            target_dir=settings.output_dir,
            status="dry_run" if dry_run else "downloading"
        )

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "job_id": job_id,
                "magnet_id": str(magnet_id),
                "selected_file": selected_file["name"],
                "target_dir": settings.output_dir,
                "status": "dry_run" if dry_run else "downloading",
                "idm_routing": idm_res
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "ENQUEUE_DOWNLOAD_FAILED",
                "message": f"Failed to process and enqueue download: {str(e)}",
                "retryable": True,
                "severity": "critical"
            }
        }

