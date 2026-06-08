import datetime
from typing import Dict, Any
from moviebot.config import settings
from moviebot.db.repositories import BotSettingsRepository

async def get_bot_persona_tool() -> Dict[str, Any]:
    """
    Retrieve the active conversational persona configuration for the bot.
    """
    tool_name = "get_bot_persona_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        db_val = BotSettingsRepository.get("rag_persona")
        default_val = settings.rag_persona
        
        active_persona = db_val if db_val is not None else default_val
        is_override = db_val is not None
        
        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "active_persona": active_persona,
                "is_override": is_override,
                "default_persona": default_val
            }
        }
    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "RETRIEVAL_FAILED",
                "message": f"Failed to retrieve persona configuration: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }
