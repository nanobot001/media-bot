import datetime
from typing import Dict, Any
from moviebot.db.repositories import EventRepository

async def get_recent_events_tool(limit: int = 50) -> Dict[str, Any]:
    """
    Retrieves the most recent events from the events table.
    """
    tool_name = "get_recent_events_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        events = EventRepository.get_recent(limit)
        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "events": events
            }
        }
    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "EVENTS_FETCH_FAILED",
                "message": f"Error retrieving events: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }
