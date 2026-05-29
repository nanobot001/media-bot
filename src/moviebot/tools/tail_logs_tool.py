import datetime
import os
from typing import Dict, Any

async def tail_logs_tool(source: str, lines: int = 100) -> Dict[str, Any]:
    """
    Retrieve the last N lines of a named log source.
    Sources: 'watcher', 'bot-out', 'bot-err'
    """
    tool_name = "tail_logs_tool"
    timestamp = datetime.datetime.utcnow().isoformat() + "Z"

    # Enforce limits
    lines = min(max(1, lines), 500)

    source_map = {
        "watcher": r"c:\Users\antho\Code\media-watcher\logs\media-watcher.log",
        "bot-out": r"C:\Users\antho\.pm2\logs\media-bot-out.log",
        "bot-err": r"C:\Users\antho\.pm2\logs\media-bot-error.log"
    }

    if source not in source_map:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "INVALID_LOG_SOURCE",
                "message": f"Log source '{source}' is invalid. Valid sources: {list(source_map.keys())}",
                "retryable": False,
                "severity": "error"
            }
        }

    log_path = source_map[source]

    try:
        if not os.path.exists(log_path):
            return {
                "ok": True,
                "tool": tool_name,
                "timestamp": timestamp,
                "data": {
                    "source": source,
                    "path": log_path,
                    "lines": [f"Log file does not exist at: {log_path}"]
                }
            }

        # Safe and memory-friendly tailing
        file_size = os.path.getsize(log_path)
        log_lines = []

        if file_size > 5 * 1024 * 1024:  # > 5MB, read the end chunk
            try:
                with open(log_path, "rb") as f:
                    f.seek(-min(file_size, 100 * 1024), os.SEEK_END)
                    chunk = f.read()
                    try:
                        text = chunk.decode("utf-8-sig")
                    except Exception:
                        text = chunk.decode("latin-1", errors="replace")
                    raw_lines = text.splitlines()
                    log_lines = [rl.rstrip("\r\n") for rl in raw_lines[-lines:]]
            except Exception as e:
                log_lines = [f"Error tailing large file: {str(e)}"]
        else:
            try:
                with open(log_path, "r", encoding="utf-8-sig") as f:
                    raw_lines = f.readlines()
                    log_lines = [rl.rstrip("\r\n") for rl in raw_lines[-lines:]]
            except Exception:
                try:
                    with open(log_path, "r", encoding="latin-1") as f:
                        raw_lines = f.readlines()
                        log_lines = [rl.rstrip("\r\n") for rl in raw_lines[-lines:]]
                except Exception as e:
                    log_lines = [f"Error reading file: {str(e)}"]

        return {
            "ok": True,
            "tool": tool_name,
            "timestamp": timestamp,
            "data": {
                "source": source,
                "path": log_path,
                "lines": log_lines
            }
        }

    except Exception as e:
        return {
            "ok": False,
            "tool": tool_name,
            "timestamp": timestamp,
            "error": {
                "code": "LOG_TAIL_FAILED",
                "message": f"Error tailing logs: {str(e)}",
                "retryable": False,
                "severity": "error"
            }
        }
