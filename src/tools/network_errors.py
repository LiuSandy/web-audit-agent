"""Failed network request monitoring for a page."""

from __future__ import annotations

import re
import time
from typing import NotRequired, TypedDict

from playwright.async_api import Page

from src.utils.logger import createLogger

logger = createLogger("tool:network-errors")


class NetworkErrorFinding(TypedDict):
    url: str
    method: str
    status: int
    statusText: str
    timestamp: int
    pageUrl: str
    responseBody: NotRequired[str]


class NetworkMonitor:
    def __init__(self, page: Page) -> None:
        self.errors: list[NetworkErrorFinding] = []
        self.page = page
        self.attachListeners()

    def attachListeners(self) -> None:
        async def onResponse(response):
            status = response.status
            if status < 400:
                return
            url = response.url
            if self.isNoise(url):
                return
            responseBody = None
            try:
                contentType = response.headers.get("content-type", "")
                if "json" in contentType or "text" in contentType:
                    responseBody = await response.text()
                    if len(responseBody) > 500:
                        responseBody = responseBody[:500] + "..."
            except Exception:  # noqa: BLE001, S110 - source ignores unreadable response bodies
                pass
            finding: NetworkErrorFinding = {
                "url": url, "method": response.request.method, "status": status,
                "statusText": response.status_text,
                "timestamp": int(time.time() * 1000), "pageUrl": self.page.url,
            }
            if responseBody is not None:
                finding["responseBody"] = responseBody
            self.errors.append(finding)
            logger.log(f"网络请求异常：{status} {response.request.method} {url}")

        def onRequestFailed(request):
            url = request.url
            if self.isNoise(url):
                return
            failure = request.failure
            finding: NetworkErrorFinding = {
                "url": url, "method": request.method, "status": 0,
                "statusText": failure or "Request failed",
                "timestamp": int(time.time() * 1000), "pageUrl": self.page.url,
            }
            self.errors.append(finding)
            logger.log(f"请求失败：{request.method} {url}，原因：{failure}")

        self.page.on("response", onResponse)
        self.page.on("requestfailed", onRequestFailed)

    def isNoise(self, url: str) -> bool:
        return any(re.search(pattern, url, re.IGNORECASE) for pattern in (
            r"favicon\.ico", r"chrome-extension", r"analytics", r"tracking",
            r"\.woff2?$", r"\.map$",
        ))

    def getErrors(self) -> list[NetworkErrorFinding]:
        errors = self.errors[:]
        self.errors = []
        return errors

    def peekErrors(self) -> list[NetworkErrorFinding]:
        return self.errors[:]

    def clear(self) -> None:
        self.errors = []
