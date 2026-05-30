from __future__ import annotations
import json
import logging
from pathlib import Path
from typing import Any, Optional, Union
from moviebot.config import settings

logger = logging.getLogger(__name__)


class MediaWatcherClient:
    """Client for reading state shared by media-watcher."""

    def __init__(self, state_path: Optional[Union[str, Path]] = None) -> None:
        self.state_path = Path(state_path or settings.media_watcher_state_path)

    def get_state(self) -> dict[str, Any]:
        """Safely reads and parses the JSON state file."""
        if not self.state_path.exists():
            logger.debug(f"Media watcher state file does not exist at {self.state_path}")
            return {"last_scan": None, "tracked_files": [], "last_batch": {"processed_at": None, "results": []}}

        try:
            with open(self.state_path, "r", encoding="utf-8-sig") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Error reading media watcher state file at {self.state_path}: {e}")
            return {"last_scan": None, "tracked_files": [], "last_batch": {"processed_at": None, "results": []}}

    def get_tracked_files(self) -> list[dict[str, Any]]:
        """Returns the list of currently tracked files."""
        state = self.get_state()
        return state.get("tracked_files", [])

    def get_last_batch(self) -> dict[str, Any]:
        """Returns the results of the last FileBot batch run."""
        state = self.get_state()
        return state.get("last_batch") or {"processed_at": None, "results": []}

    def is_file_tracked(self, filename: str) -> bool:
        """Checks if a file is currently being tracked (not processed or failed yet)."""
        filename_lower = filename.lower()
        for tf in self.get_tracked_files():
            tf_name = tf.get("filename", "")
            if tf_name.lower() == filename_lower:
                return True
        return False

    def get_file_status(self, filename: str) -> tuple[str, Optional[str]]:
        """Checks the status of a file against tracked files and the last batch.
        
        Returns:
            A tuple of (status, error_message)
            Status can be: "tracking", "processed", "failed", "unknown"
        """
        filename_lower = filename.lower()
        
        # 1. Check if actively tracked (downloading/stabilizing/renaming)
        for tf in self.get_tracked_files():
            tf_name = tf.get("filename", "")
            if tf_name.lower() == filename_lower:
                return "tracking", None

        # 2. Check if in the last processed batch
        last_batch = self.get_last_batch()
        results = last_batch.get("results", [])
        for res in results:
            src_file = res.get("source_file", "")
            if src_file.lower() == filename_lower:
                if res.get("success", False):
                    return "processed", None
                else:
                    return "failed", res.get("error")

        return "unknown", None
