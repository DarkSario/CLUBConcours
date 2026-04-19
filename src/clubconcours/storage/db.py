from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

SCHEMA_PATH = Path(__file__).with_name("schema.sql")

def default_db_filename(prefix: str = "CLUBConcours") -> str:
    ts = datetime.now().strftime("%Y-%m-%d_%H%M")
    return f"{prefix}_{ts}.db"

def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db(conn: sqlite3.Connection) -> None:
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES('schema_version', '1');")
    conn.commit()
