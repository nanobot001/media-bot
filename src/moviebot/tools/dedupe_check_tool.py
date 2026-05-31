import datetime
from typing import Dict, Any, Optional
from moviebot.core.dedupe import evaluate_deduplication


async def dedupe_check_tool(
    title: str,
    year: int,
    imdb_id: Optional[str] = None,
    incoming_resolution: Optional[str] = None,
    incoming_size_bytes: Optional[int] = None,
    incoming_bitrate_kbps: Optional[int] = None
) -> Dict[str, Any]:
    """
    Applies the tiered normalization engine to classify input titles against the library mirror.
    """
    tool_name = "dedupe_check_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        tier, action, details, matched_item = evaluate_deduplication(
            title=title,
            year=year,
            imdb_id=imdb_id,
            incoming_resolution=incoming_resolution,
            incoming_size_bytes=incoming_size_bytes,
            incoming_bitrate_kbps=incoming_bitrate_kbps
        )

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "match_rating": tier,
                "action": action,
                "details": details,
                "matched_item": matched_item
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "DEDUPE_CHECK_FAILED",
                "message": f"Error running dedupe check: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
