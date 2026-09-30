"""SQLite schema and singleton database access."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import ClassVar


class AppDatabase:
    instance: ClassVar[AppDatabase | None] = None

    def __init__(self, db_path: str = "qa-agent.sqlite") -> None:
        directory = Path(db_path).parent
        if str(directory) != "." and not directory.exists():
            directory.mkdir(parents=True)
        self.db = sqlite3.connect(db_path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.initialize_schema()

    @classmethod
    def get_instance(cls, db_path: str | None = None) -> AppDatabase:
        if cls.instance is None:
            cls.instance = cls(db_path if db_path is not None else "qa-agent.sqlite")
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
