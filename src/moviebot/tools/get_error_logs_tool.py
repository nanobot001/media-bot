import datetime
from typing import Dict, Any
from moviebot.db.repositories import ErrorLogRepository


async def get_error_logs_tool(limit: int = 50) -> Dict[str, Any]:
    """
    Retrieve recent diagnostic error logs from the database.
    """
    tool_name = "get_error_logs_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        errors = ErrorLogRepository.get_all()
        sliced_errors = errors[:limit]

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "errors": sliced_errors
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "ERROR_LOGS_RETRIEVAL_FAILED",
                "message": f"Error retrieving error logs: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }
