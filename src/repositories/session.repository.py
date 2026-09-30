"""SQLite-backed persistence for exploration sessions."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from src.types.index import OrderedSet
from src.utils.logger import createLogger

logger = createLogger("repository:session")


class SessionRepository:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    def saveState(self, sessionId: str, state: dict[str, Any]) -> None:
        try:
            def encode(value: Any) -> Any:
                if isinstance(value, set):
                    return {"_type": "Set", "values": list(value)}
                raise TypeError(f"类型 {type(value).__name__} 无法序列化为 JSON")

            serializedState = json.dumps(
                state, default=encode, ensure_ascii=False, separators=(",", ":")
            )
            self.db.execute("""
                INSERT INTO agent_sessions (id, state, updated_at)
                VALUES (:id, :state, CURRENT_TIMESTAMP)
                ON CONFLICT(id) DO UPDATE SET
                    state = excluded.state,
                    updated_at = excluded.updated_at
            """, {"id": sessionId, "state": serializedState})
            logger.info(f"已保存会话状态：{sessionId}")
        except Exception as error:  # noqa: BLE001 - preserve source catch
            logger.error(f"保存会话 {sessionId} 的状态失败：{error}")

    def loadState(self, sessionId: str) -> dict[str, Any] | None:
        try:
            row = self.db.execute(
                "SELECT state FROM agent_sessions WHERE id = :id", {"id": sessionId}
            ).fetchone()
            if row is None:
                return None

            def revive(value: dict[str, Any]) -> Any:
                if value.get("_type") == "Set":
                    return OrderedSet(value["values"])
                return value

            state = json.loads(row["state"], object_hook=revive)
            logger.info(f"已加载会话状态：{sessionId}")
            return state
        except Exception as error:  # noqa: BLE001 - preserve source catch
            logger.error(f"加载会话 {sessionId} 的状态失败：{error}")
            return None

    def listSessions(self) -> list[str]:
        try:
            rows = self.db.execute(
                "SELECT id FROM agent_sessions ORDER BY updated_at DESC"
            ).fetchall()
            return [row["id"] for row in rows]
        except Exception as error:  # noqa: BLE001 - preserve source catch
            logger.error(f"列出会话失败：{error}")
            return []
