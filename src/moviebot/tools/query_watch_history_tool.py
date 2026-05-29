import datetime
from typing import Dict, Any, Optional
from moviebot.adapters.tautulli_client import TautulliClient


async def query_watch_history_tool(
    user: Optional[str] = None,
    title: Optional[str] = None,
    limit: int = 50
) -> Dict[str, Any]:
    """
    Query Plex watch history logs from Tautulli to answer who watched what, when, and how.
    """
    tool_name = "query_watch_history_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        client = TautulliClient()
        
        # Build query parameters
        params = {"length": limit}
        resolved_user_name = None

        if user:
            try:
                users_list = await client._query("get_users")
                if isinstance(users_list, list):
                    user_lower = user.lower()
                    matched_user = None

                    # 1. Exact case-insensitive match on username or friendly_name
                    for u in users_list:
                        uname = u.get("username")
                        fname = u.get("friendly_name")
                        if (uname and uname.lower() == user_lower) or (fname and fname.lower() == user_lower):
                            matched_user = u
                            break

                    # 2. Prefix match if no exact match found
                    if not matched_user:
                        for u in users_list:
                            uname = u.get("username")
                            fname = u.get("friendly_name")
                            if (uname and uname.lower().startswith(user_lower)) or (fname and fname.lower().startswith(user_lower)):
                                matched_user = u
                                break

                    # 3. Substring match if no prefix match found
                    if not matched_user:
                        for u in users_list:
                            uname = u.get("username")
                            fname = u.get("friendly_name")
                            if (uname and user_lower in uname.lower()) or (fname and user_lower in fname.lower()):
                                matched_user = u
                                break

                    if matched_user:
                        params["user_id"] = matched_user.get("user_id")
                        resolved_user_name = matched_user.get("friendly_name") or matched_user.get("username")
                    else:
                        # Fallback to passing the string directly as a user parameter
                        params["user"] = user
                else:
                    params["user"] = user
            except Exception as e:
                # Log warning and fall back to querying with raw user string
                print(f"[Watch History Tool] Warning: Tautulli user list lookup failed: {str(e)}")
                params["user"] = user

        if title:
            params["search"] = title

        # Execute query via Tautulli's generic _query helper
        history_data = await client._query("get_history", params)
        
        # Extract the list of history entries
        entries = history_data.get("data", [])
        
        # Simplify entries for tool friendly consumption
        formatted_history = []
        for item in entries:
            formatted_history.append({
                "title": item.get("title") or item.get("full_title"),
                "year": item.get("year"),
                "user": item.get("user") or item.get("friendly_name"),
                "date": datetime.datetime.fromtimestamp(item.get("date", 0)).isoformat() if item.get("date") else "Unknown",
                "duration_minutes": round(item.get("duration", 0) / 60, 1) if item.get("duration") else 0,
                "percent_complete": item.get("percent_complete", 0),
                "player": item.get("player"),
                "media_type": item.get("media_type")
            })

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "history": formatted_history,
                "resolved_user": resolved_user_name
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "WATCH_HISTORY_QUERY_FAILED",
                "message": f"Failed to retrieve watch history: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }
