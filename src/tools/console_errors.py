"""Console error monitoring for a page."""

from __future__ import annotations

import re
import time
from typing import Literal, NotRequired, TypedDict

from playwright.async_api import Page

from src.utils.logger import create_logger

logger = create_logger("tool:console-errors")


class ConsoleErrorFinding(TypedDict):
    type: Literal["error", "warning"]
    message: str
    url: str
    timestamp: int
    stackTrace: NotRequired[str]


class ConsoleMonitor:
    def __init__(self, page: Page) -> None:
        self.errors: list[ConsoleErrorFinding] = []
        self.page = page
        self.attach_listeners()

    def attach_listeners(self) -> None:
        def on_console(msg):
            msg_type = msg.type
            if msg_type not in ("error", "warning"):
                return
            text = msg.text
            if self.is_noise(text):
                return
            finding: ConsoleErrorFinding = {
                "type": msg_type, "message": text, "url": self.page.url,
                "timestamp": int(time.time() * 1000),
            }
            self.errors.append(finding)
            logger.log(f"控制台{'错误' if msg_type == 'error' else '警告'}：{text}")

        def on_page_error(error):
            message = getattr(error, "message", str(error))
            finding: ConsoleErrorFinding = {
                "type": "error", "message": message, "url": self.page.url,
                "timestamp": int(time.time() * 1000),
            }
            stack = getattr(error, "stack", None)
            if stack:
                finding["stackTrace"] = stack
            self.errors.append(finding)
            logger.log(f"页面异常：{message}")

        self.page.on("console", on_console)
        self.page.on("pageerror", on_page_error)

    def is_noise(self, message: str) -> bool:
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in (
            r"favicon\.ico", r"chrome-extension", r"third-party",
        ))

    def get_errors(self) -> list[ConsoleErrorFinding]:
        errors = self.errors[:]
        self.errors = []
        return errors

    def peek_errors(self) -> list[ConsoleErrorFinding]:
        return self.errors[:]

    def clear(self) -> None:
        self.errors = []
