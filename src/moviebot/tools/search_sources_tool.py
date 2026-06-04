import datetime
from typing import Dict, Any, Optional
from moviebot.adapters.prowlarr_client import ProwlarrClient


async def search_sources_tool(query: str, imdb_id: Optional[str] = None) -> Dict[str, Any]:
    """
    Search Prowlarr indexers for movies, filtering to category 2000 and obfuscating URLs.
    """
    tool_name = "search_sources_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        client = ProwlarrClient()
        results = await client.search_movies(query=query, imdb_id=imdb_id)
        
        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "results": results
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "SOURCE_SEARCH_FAILED",
                "message": f"Indexer search failed: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }
