import datetime
import os
import yaml
from typing import Dict, Any

async def get_tool_manifest_tool() -> Dict[str, Any]:
    """
    Load and parse the tool-manifest.yaml file.
    """
    tool_name = "get_tool_manifest_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    manifest_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "docs", "tool-manifest.yaml"))
    
    # Fallback to current working directory docs/tool-manifest.yaml if path does not exist
    if not os.path.exists(manifest_path):
        manifest_path = os.path.abspath(os.path.join("docs", "tool-manifest.yaml"))

    try:
        if not os.path.exists(manifest_path):
            raise FileNotFoundError(f"Tool manifest not found at: {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest_data = yaml.safe_load(f)

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": manifest_data
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "MANIFEST_LOAD_FAILED",
                "message": f"Error loading manifest: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
