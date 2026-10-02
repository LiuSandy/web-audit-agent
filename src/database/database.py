"""SQLite schema and singleton database access."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import ClassVar

from src.runtime import get_runtime, ensure_home, private_directory


class AppDatabase:
    instance: ClassVar[AppDatabase | None] = None

    def __init__(self, db_path: str | None = None) -> None:
        if db_path is None:
            ensure_home()
            db_path = str(get_runtime().database)
        self.db_path = db_path
        directory = Path(db_path).parent
        if str(directory) != "." and not directory.exists():
            private_directory(directory)
        self.db = sqlite3.connect(db_path, isolation_level=None)
        if db_path != ":memory:":
            Path(db_path).chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.initialize_schema()

    @classmethod
    def get_instance(cls, db_path: str | None = None) -> AppDatabase:
        expected = db_path or str(get_runtime().database)
        if cls.instance is not None and cls.instance.db_path not in (expected, ":memory:"):
            cls.instance.close()
        if cls.instance is None:
            cls.instance = cls(db_path)
        return cls.instance

    def initialize_schema(self) -> None:
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id TEXT PRIMARY KEY,
                state TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS agent_runs (
                id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                artifact_dir TEXT NOT NULL,
                report_path TEXT,
                summary TEXT NOT NULL,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS credentials (
                app_identifier TEXT PRIMARY KEY,
                encrypted_data TEXT NOT NULL,
                iv TEXT NOT NULL,
                metadata TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        self.db.execute("""
            CREATE TABLE IF NOT EXISTS browser_sessions (
                app_identifier TEXT PRIMARY KEY,
                cookies TEXT NOT NULL,
                storage_state TEXT,
                expires_at INTEGER,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)

    def get_database(self) -> sqlite3.Connection:
        return self.db

    def close(self) -> None:
        self.db.close()
        AppDatabase.instance = None

    @staticmethod
    def reset() -> None:
        if AppDatabase.instance is not None:
            AppDatabase.instance.close()
        AppDatabase.instance = None
