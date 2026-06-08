import datetime
from typing import Dict, Any, Optional
from moviebot.config import settings
from moviebot.db.repositories import BotSettingsRepository

async def set_bot_persona_tool(persona: Optional[str] = None, reset: bool = False) -> Dict[str, Any]:
    """
    Configure or reset the active conversational persona for the bot.

    Args:
        persona: The custom system instruction/persona string to apply.
        reset: Set to True to clear the custom override and revert to default settings.
    """
    tool_name = "set_bot_persona_tool"
    timestamp = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None).isoformat() + "Z"

    try:
        if reset:
            BotSettingsRepository.delete("rag_persona")
            updated_persona = settings.rag_persona
            action = "reset"
        else:
            if not persona or not persona.strip():
                return {
                    "ok": False,
                    "tool": tool_name,
                    "timestamp": timestamp,
                    "error": {
                        "code": "MISSING_PERSONA",
                        "message": "Persona text cannot be empty unless resetting.",
                        "retryable": False,
                        "severity": "error"
                    }
                }
            
            clean_persona = persona.strip()
            BotSettingsRepository.set("rag_persona", clean_persona)
            updated_persona = clean_persona
            action = "set"

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "action": action,
                "updated_persona": updated_persona,
                "is_override": not reset
            }
        }
    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "UPDATE_FAILED",
                "message": f"Failed to update persona configuration: {str(e)}",
                "retryable": True,
                "severity": "error"
            }
        }
