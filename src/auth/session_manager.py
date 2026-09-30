"""Browser session persistence."""

from __future__ import annotations

import json
import sqlite3
import time

from playwright.async_api import Page


class SessionManager:
    def __init__(self, db: sqlite3.Connection) -> None:
        self.db = db

    async def save_session(self, page: Page, app_identifier: str) -> None:
        context = page.context
        cookies = await context.cookies()
        storage_state = await context.storage_state()
        now = int(time.time() * 1000)
        expires_at = now + 24 * 60 * 60 * 1000
        self.db.execute("""
            INSERT OR REPLACE INTO browser_sessions
            (app_identifier, cookies, storage_state, expires_at, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            app_identifier,
            json.dumps(cookies, ensure_ascii=False, separators=(",", ":")),
            json.dumps(storage_state, ensure_ascii=False, separators=(",", ":")),
            expires_at, now, now,
        ))

    async def restore_session(self, page: Page, app_identifier: str) -> bool:
        row = self.db.execute("""
            SELECT cookies, storage_state, expires_at FROM browser_sessions
            WHERE app_identifier = ? AND expires_at > ?
        """, (app_identifier, int(time.time() * 1000))).fetchone()
        if row is None:
            return False

        try:
            context = page.context
            cookies = json.loads(row["cookies"])
            await context.add_cookies(cookies)
            if row["storage_state"]:
                state = json.loads(row["storage_state"])
                if state.get("origins"):
                    await page.evaluate("""(origins) => {
                        for (const origin of origins) {
                            if (origin.origin === window.location.origin) {
                                for (const item of origin.localStorage) {
                                    localStorage.setItem(item.name, item.value);
                                }
                            }
                        }
                    }""", state["origins"])
            return True
        except Exception as error:  # noqa: BLE001 - preserve source catch
            print("恢复会话失败：", error)
            return False

    def close(self) -> None:
        self.db.close()
