import datetime
from typing import Dict, Any
from moviebot.db.repositories import DownloadJobRepository


async def get_download_jobs_tool(active_only: bool = True, limit: int = 50) -> Dict[str, Any]:
    """
    Retrieve active or historical download jobs from the local database.
    """
    tool_name = "get_download_jobs_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        if active_only:
            jobs = DownloadJobRepository.get_active_jobs()
        else:
            jobs = DownloadJobRepository.get_all_jobs(limit=limit)

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "jobs": jobs
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "JOBS_RETRIEVAL_FAILED",
                "message": f"Error retrieving download jobs: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }
