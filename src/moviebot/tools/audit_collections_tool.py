import datetime
from typing import Dict, Any

from moviebot.db.connection import get_db_connection
from moviebot.core.collection_audit import audit_collections


async def audit_collections_tool() -> Dict[str, Any]:
    """
    Scans the database for movies tagged with collections, groups them, and audits them
    for sequence gaps or missing sequels.
    """
    tool_name = "audit_collections_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    try:
        with get_db_connection() as conn:
            reports = audit_collections(conn)

        # Redact/sanitize any potential file_path fields from owned movies
        for report in reports:
            for item in report.get("owned", []):
                item.pop("file_path", None)

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "reports": reports
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "COLLECTION_AUDIT_FAILED",
                "message": f"Error running collection audit: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
