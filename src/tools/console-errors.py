"""Port of src/tools/console-errors.ts."""

from __future__ import annotations

import re
import time
from typing import Literal, NotRequired, TypedDict

from playwright.async_api import Page

from src.utils.logger import createLogger

logger = createLogger("tool:console-errors")


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
        self.attachListeners()

    def attachListeners(self) -> None:
        def onConsole(msg):
            msgType = msg.type
            if msgType not in ("error", "warning"):
                return
            text = msg.text
            if self.isNoise(text):
                return
            finding: ConsoleErrorFinding = {
                "type": msgType, "message": text, "url": self.page.url,
                "timestamp": int(time.time() * 1000),
            }
            self.errors.append(finding)
            logger.log(f"控制台{'错误' if msgType == 'error' else '警告'}：{text}")

        def onPageError(error):
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

        self.page.on("console", onConsole)
        self.page.on("pageerror", onPageError)

    def isNoise(self, message: str) -> bool:
        return any(re.search(pattern, message, re.IGNORECASE) for pattern in (
            r"favicon\.ico", r"chrome-extension", r"third-party",
        ))

    def getErrors(self) -> list[ConsoleErrorFinding]:
        errors = self.errors[:]
        self.errors = []
        return errors

    def peekErrors(self) -> list[ConsoleErrorFinding]:
        return self.errors[:]

    def clear(self) -> None:
        self.errors = []
