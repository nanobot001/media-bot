import datetime
from typing import Dict, Any, Optional

from moviebot.core.conversational_rag import query_library_conversational

async def ask_library_tool(
    question: str,
    discord_user_id: Optional[str] = None,
    known_users: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Ask conversational questions about your movie library using natural language (RAG).

    Args:
        question: Natural language question/description about the library items.
        discord_user_id: Optional Discord user ID for personalized memory extraction and retrieval.
        known_users: Optional dictionary mapping names/nicknames to Discord IDs for cross-user memory.
    """
    tool_name = "ask_library_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    if not question or not question.strip():
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "MISSING_QUESTION",
                "message": "Question argument cannot be empty.",
                "retryable": False,
                "severity": "error"
            }
        }

    try:
        result = await query_library_conversational(
            question,
            discord_user_id=discord_user_id,
            known_users=known_users
        )
        if "ok" in result and not result["ok"]:
            rag_error = result.get("error", {})
            return {
                "ok": False,
                "tool": tool_name,
                "timestamp": timestamp,
                "error": {
                    "code": rag_error.get("code", "RAG_QUERY_FAILED"),
                    "message": rag_error.get("message", "RAG query failed"),
                    "retryable": bool(rag_error.get("retryable", False)),
                    "severity": "error"
                }
            }

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "answer": result["answer"],
                "cited_movie_ids": result["cited_movie_ids"],
                "external_recommendations": result.get("external_recommendations", []),
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "ASK_LIBRARY_FAILED",
                "message": f"Error running ask_library: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
