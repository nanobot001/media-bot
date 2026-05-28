#!/usr/bin/env python3
"""Initialize the local SQLite state database for this tool-friendly project."""

from __future__ import annotations

import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "state"
SCHEMA_PATH = STATE_DIR / "schema.sql"
DB_PATH = STATE_DIR / "project.sqlite"


def main() -> int:
    if not SCHEMA_PATH.exists():
        raise SystemExit(f"Missing schema file: {SCHEMA_PATH}")
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    print(f"Initialized SQLite state database: {DB_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
