"""Failed network request monitoring for a page."""

from __future__ import annotations

import re
import time
from typing import NotRequired, TypedDict

from playwright.async_api import Page

from src.utils.logger import create_logger

logger = create_logger("tool:network-errors")


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
        self.attach_listeners()

    def attach_listeners(self) -> None:
        async def on_response(response):
            status = response.status
            if status < 400:
                return
            url = response.url
            if self.is_noise(url):
                return
            response_body = None
            try:
                content_type = response.headers.get("content-type", "")
                if "json" in content_type or "text" in content_type:
                    response_body = await response.text()
                    if len(response_body) > 500:
                        response_body = response_body[:500] + "..."
            except Exception:  # noqa: BLE001, S110 - source ignores unreadable response bodies
                pass
            finding: NetworkErrorFinding = {
                "url": url, "method": response.request.method, "status": status,
                "statusText": response.status_text,
                "timestamp": int(time.time() * 1000), "pageUrl": self.page.url,
            }
            if response_body is not None:
                finding["responseBody"] = response_body
            self.errors.append(finding)
            logger.log(f"网络请求异常：{status} {response.request.method} {url}")

        def on_request_failed(request):
            url = request.url
            if self.is_noise(url):
                return
            failure = request.failure
            finding: NetworkErrorFinding = {
                "url": url, "method": request.method, "status": 0,
                "statusText": failure or "Request failed",
                "timestamp": int(time.time() * 1000), "pageUrl": self.page.url,
            }
            self.errors.append(finding)
            logger.log(f"请求失败：{request.method} {url}，原因：{failure}")

        self.page.on("response", on_response)
        self.page.on("requestfailed", on_request_failed)

    def is_noise(self, url: str) -> bool:
        return any(re.search(pattern, url, re.IGNORECASE) for pattern in (
            r"favicon\.ico", r"chrome-extension", r"analytics", r"tracking",
            r"\.woff2?$", r"\.map$",
        ))

    def get_errors(self) -> list[NetworkErrorFinding]:
        errors = self.errors[:]
        self.errors = []
        return errors

    def peek_errors(self) -> list[NetworkErrorFinding]:
        return self.errors[:]

    def clear(self) -> None:
        self.errors = []
