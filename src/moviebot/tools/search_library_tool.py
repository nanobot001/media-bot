import datetime
from typing import Dict, Any, Optional
from moviebot.core.dedupe import normalize_title
from moviebot.db.repositories import LibraryItemRepository


async def search_library_tool(title: str, year: Optional[int] = None) -> Dict[str, Any]:
    """
    Search the local SQLite state mirror for a movie.
    """
    tool_name = "search_library_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        norm_title = normalize_title(title)
        
        # If year is provided, try exact match first
        if year:
            db_matches = LibraryItemRepository.get_by_normalized_title_and_year(norm_title, year)
        else:
            db_matches = LibraryItemRepository.search_by_normalized_title(norm_title)

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "matches": db_matches
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "LIBRARY_SEARCH_FAILED",
                "message": f"Error searching database: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
