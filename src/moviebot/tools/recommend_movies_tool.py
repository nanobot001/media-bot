import datetime
from typing import Dict, Any, Optional

from moviebot.db.connection import get_db_connection
from moviebot.core.taste_profiler import recommend_movies


async def recommend_movies_tool(
    user: Optional[str] = None,
    limit: int = 10
) -> Dict[str, Any]:
    """
    Runs the taste recommender algorithm to rank owned, unwatched library items using taste vectors.

    Args:
        user: Filter watch history by viewer username.
        limit: Max number of recommendation entries to return.
    """
    tool_name = "recommend_movies_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        with get_db_connection() as conn:
            recommendations = await recommend_movies(conn, user=user, limit=limit)

        # Redact/sanitize any potential file_path fields
        for rec in recommendations:
            rec.pop("file_path", None)
            # Remove raw vector from recommendations output if it's there
            rec.pop("vector", None)

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "recommendations": recommendations
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "RECOMMENDATIONS_FAILED",
                "message": f"Error generating recommendations: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
