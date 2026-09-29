"""SQLite schema and singleton behavior of src/database/database.ts."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import ClassVar


class AppDatabase:
    instance: ClassVar[AppDatabase | None] = None

    def __init__(self, dbPath: str = "qa-agent.sqlite") -> None:
        directory = Path(dbPath).parent
        if str(directory) != "." and not directory.exists():
            directory.mkdir(parents=True)
        self.db = sqlite3.connect(dbPath, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.initializeSchema()

    @classmethod
    def getInstance(cls, dbPath: str | None = None) -> AppDatabase:
        if cls.instance is None:
            cls.instance = cls(dbPath if dbPath is not None else "qa-agent.sqlite")
        return cls.instance

    def initializeSchema(self) -> None:
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

    def getDatabase(self) -> sqlite3.Connection:
        return self.db

    def close(self) -> None:
        self.db.close()
        AppDatabase.instance = None

    @staticmethod
    def reset() -> None:
        if AppDatabase.instance is not None:
            AppDatabase.instance.close()
        AppDatabase.instance = None
