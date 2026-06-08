import datetime
from typing import Dict, Any
from moviebot.adapters.plex_client import PlexClient

async def plex_section_preview_tool() -> Dict[str, Any]:
    """
    Preview Plex sections mapping to canonical domains (movies, anime, tv, tv_classic) with item counts.
    """
    tool_name = "plex_section_preview"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        client = PlexClient()
        sections = await client.fetch_sections_preview()

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "sections": sections
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "PREVIEW_FAILED",
                "message": f"Error generating Plex section preview: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }
