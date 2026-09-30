"""MCP tool result types and text-content helpers."""

import json
from typing import Any, NotRequired, TypedDict


class TestExecution(TypedDict):
    sessionId: str
    status: str
    startTime: Any
    findingsCount: int
    visitedUrlsCount: int
    progress: int
    baseUrl: NotRequired[str]
    strategy: NotRequired[str]
    endTime: NotRequired[Any]
    currentAction: NotRequired[str]
    lastError: NotRequired[str]


class TestStatusResult(TypedDict):
    sessionId: str
    status: str
    statusText: NotRequired[str]
    progress: int
    currentAction: str
    stats: dict[str, Any]
    recentFindings: list[dict[str, Any]]


class ExploratoryTestResult(TypedDict):
    sessionId: str
    status: str
    message: str
    stats: dict[str, Any]


class SinglePageTestResult(TypedDict):
    sessionId: str
    status: str
    testPlan: dict[str, Any]
    progress: dict[str, Any]


class SessionSummary(TypedDict):
    sessionId: str
    status: str
    statusText: NotRequired[str]
    findingsCount: int
    visitedUrlsCount: int
    startTime: NotRequired[str]
    endTime: NotRequired[str]


class ListSessionsResult(TypedDict):
    sessions: list[SessionSummary]
    total: int


def toTextContent(data):
    return [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}]
