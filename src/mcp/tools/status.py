"""Port of src/mcp/tools/status.ts."""

import importlib
from datetime import datetime, timezone

from src.mcp.types import toTextContent
from src.utils.logger import createLogger
from src.utils.locale import STATUSES, display_label

logger = createLogger("mcp:status")


def _activeTests():
    return importlib.import_module("src.mcp.server").activeTests


def _getAgentInstance(sessionId):
    return importlib.import_module("src.mcp.tools.exploratory").getAgentInstance(sessionId)


async def handleGetTestStatus(args):
    sessionId = str(args.get("sessionId", "")).strip()
    if not sessionId:
        raise ValueError("必须提供 sessionId")
    execution = _activeTests().get(sessionId) or {}
    singlePageState = execution.get("state") if isinstance(execution.get("state"), dict) else None
    agent = _getAgentInstance(sessionId)
    if singlePageState:
        findings = [finding for case in singlePageState.get("results", [])
                    for finding in case.get("findings", [])]
    else:
        findings = agent.getFindings() if agent else []
    recentFindings = sorted(findings,
        key=lambda f: float((f.get("metadata") or {}).get("timestamp") or 0),
        reverse=True)[:10]
    state = singlePageState or execution
    status = state.get("status", "unknown")
    startTime = state.get("startTime")
    endTime = state.get("endTime")
    plan = state.get("testPlan") or {}
    totalCases = plan.get("totalTests") or 0
    progress = (min(100, round(len(state.get("results", [])) / totalCases * 100))
                if singlePageState and totalCases else state.get("progress", 0))
    if status in ("completed", "stopped", "failed"):
        progress = 100
    result = {"sessionId": sessionId, "status": status,
        "statusText": display_label(status, STATUSES),
        "progress": progress,
        "currentAction": state.get("currentAction", "暂无"),
        "stats": {"visitedPages": 1 if singlePageState and state.get("results") else state.get("visitedUrlsCount", 0),
                  "findingsCount": state.get("findingsCount", len(findings)),
                  "queueLength": 0},
        "recentFindings": [{k: f.get(k) for k in ("type", "description", "severity", "url")}
                           for f in recentFindings]}
    if startTime:
        result["startTime"] = _iso(startTime)
    if endTime:
        result["endTime"] = _iso(endTime)
    return {"content": toTextContent(result)}


def _iso(value):
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value / 1000, timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


async def handleStopTest(args):
    sessionId = str(args.get("sessionId", "")).strip()
    if not sessionId:
        raise ValueError("必须提供 sessionId")
    execution = _activeTests().get(sessionId)
    if not execution:
        return {"content": toTextContent({"sessionId": sessionId, "status": "not_found", "statusText": "未找到",
            "message": f"没有找到会话 {sessionId} 的运行中测试"})}
    state = execution.get("state") if isinstance(execution.get("state"), dict) else execution
    if state.get("status") in ("completed", "stopped"):
        return {"content": toTextContent({"sessionId": sessionId,
            "status": state["status"], "statusText": display_label(state["status"], STATUSES),
            "message": f"测试已经{'完成' if state['status'] == 'completed' else '停止'}"})}
    state["status"] = "stopped"
    abort = (execution.get("abortController") or {}).get("abort")
    if callable(abort):
        abort()
    logger.info(f"已向测试 {sessionId} 发送停止信号")
    return {"content": toTextContent({"sessionId": sessionId, "status": "stopping", "statusText": "正在停止",
        "message": "已发送停止信号，测试将在当前操作后结束"})}
