import datetime
from typing import Dict, Any, List
from moviebot.config import settings
from moviebot.db.repositories import DownloadJobRepository
from moviebot.adapters.alldebrid_client import AllDebridClient
from moviebot.adapters.idm_adapter import IdmAdapter
from moviebot.core.file_selection import select_primary_video_file


async def resolve_pending_jobs_tool(dry_run: bool = False) -> Dict[str, Any]:
    """
    Sweeps database for jobs in 'pending' status, queries AllDebrid,
    resolves direct links, sends to IDM, and updates database statuses.
    """
    tool_name = "resolve_pending_jobs_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    resolved_list: List[Dict[str, Any]] = []
    ambiguous_list: List[Dict[str, Any]] = []
    still_pending_list: List[Dict[str, Any]] = []
    failed_list: List[Dict[str, Any]] = []

    try:
        active_jobs = DownloadJobRepository.get_active_jobs()
        pending_jobs = [j for j in active_jobs if j["status"] == "pending"]

        if not pending_jobs:
            return {
                "ok": True,
                "tool": tool_name,
                "timestamp": timestamp,
                "data": {
                    "resolved": [],
                    "ambiguous_requires_selection": [],
                    "still_pending": [],
                    "failed": []
                }
            }

        debrid = AllDebridClient()
        idm = IdmAdapter()

        for job in pending_jobs:
            job_id = job["id"]
            magnet_id = job["alldebrid_magnet_id"]
            target_dir = job["target_dir"]

            if not magnet_id:
                failed_list.append({
                    "job_id": job_id,
                    "error": "No AllDebrid magnet ID stored for this pending job."
                })
                if not dry_run:
                    DownloadJobRepository.update_status(job_id, "failed")
                continue

            try:
                # Query AllDebrid status
                status_res = await debrid.get_magnet_status(magnet_id)
                if status_res.get("statusCode") == 4:
                    files_list = await debrid.get_magnet_files(magnet_id)
                else:
                    files_list = []

                # If AllDebrid has not resolved the file listing yet, keep it pending
                if not files_list:
                    still_pending_list.append({
                        "job_id": job_id,
                        "magnet_id": magnet_id
                    })
                    continue

                # Run file selection heuristics
                try:
                    is_resolved, chosen_files = select_primary_video_file(files_list)
                except ValueError as ve:
                    failed_list.append({
                        "job_id": job_id,
                        "error": f"File selection error: {str(ve)}"
                    })
                    if not dry_run:
                        DownloadJobRepository.update_status(job_id, "failed")
                    continue

                if not is_resolved:
                    # Ambigous files require user selection
                    ambiguous_list.append({
                        "job_id": job_id,
                        "magnet_id": magnet_id,
                        "candidates": chosen_files
                    })
                    if not dry_run:
                        DownloadJobRepository.update_status(job_id, "requires_selection")
                    continue

                selected_file = chosen_files[0]

                # Under v4.1, the selected file's direct link is retrieved from the flattened list
                target_debrid_link = None
                for f in files_list:
                    name = f.get("name") or f.get("n")
                    if name == selected_file["name"]:
                        target_debrid_link = f.get("link") or f.get("l")
                        break

                if not target_debrid_link:
                    failed_list.append({
                        "job_id": job_id,
                        "error": "Could not locate debrid link for selected file."
                    })
                    if not dry_run:
                        DownloadJobRepository.update_status(job_id, "failed")
                    continue

                # Resolve direct download stream link
                unlocked_url = await debrid.unlock_link(target_debrid_link)

                # Send link to IDM
                await idm.send_to_idm(
                    download_url=unlocked_url,
                    output_folder=target_dir,
                    file_name=selected_file["name"],
                    dry_run=dry_run
                )

                resolved_list.append({
                    "job_id": job_id,
                    "magnet_id": magnet_id,
                    "selected_file": selected_file["name"]
                })

                if not dry_run:
                    DownloadJobRepository.update_job_details(
                        id=job_id,
                        status="downloading",
                        selected_file_name=selected_file["name"]
                    )

            except Exception as e:
                failed_list.append({
                    "job_id": job_id,
                    "error": f"Exception encountered during resolution: {str(e)}"
                })
                # We do not mark as failed immediately if it's a transient network error, just skip it

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "resolved": resolved_list,
                "ambiguous_requires_selection": ambiguous_list,
                "still_pending": still_pending_list,
                "failed": failed_list
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "RESOLVE_PENDING_FAILED",
                "message": f"Failed to execute pending jobs resolution sweep: {str(e)}",
                "retryable": True,
                "severity": "critical"
            }
        }
