"""MCP tools for test status and stopping runs."""

import importlib
from datetime import datetime, timezone

from src.mcp.types import to_text_content
from src.utils.logger import create_logger
from src.utils.locale import STATUSES, display_label

logger = create_logger("mcp:status")


def _active_tests():
    return importlib.import_module("src.mcp.server").active_tests


def _get_agent_instance(session_id):
    return importlib.import_module("src.mcp.tools.exploratory").get_agent_instance(session_id)


async def handle_get_test_status(args):
    session_id = str(args.get("sessionId", "")).strip()
    if not session_id:
        raise ValueError("必须提供 sessionId")
    execution = _active_tests().get(session_id) or {}
    single_page_state = execution.get("state") if isinstance(execution.get("state"), dict) else None
    agent = _get_agent_instance(session_id)
    if single_page_state:
        findings = [finding for case in single_page_state.get("results", [])
                    for finding in case.get("findings", [])]
    else:
        findings = agent.get_findings() if agent else []
    recent_findings = sorted(findings,
        key=lambda f: float((f.get("metadata") or {}).get("timestamp") or 0),
        reverse=True)[:10]
    state = single_page_state or execution
    status = state.get("status", "unknown")
    start_time = state.get("startTime")
    end_time = state.get("endTime")
    plan = state.get("testPlan") or {}
    total_cases = plan.get("totalTests") or 0
    progress = (min(100, round(len(state.get("results", [])) / total_cases * 100))
                if single_page_state and total_cases else state.get("progress", 0))
    if status in ("completed", "stopped", "failed"):
        progress = 100
    result = {"sessionId": session_id, "status": status,
        "statusText": display_label(status, STATUSES),
        "progress": progress,
        "currentAction": state.get("currentAction", "暂无"),
        "stats": {"visitedPages": 1 if single_page_state and state.get("results") else state.get("visitedUrlsCount", 0),
                  "findingsCount": state.get("findingsCount", len(findings)),
                  "queueLength": 0},
        "recentFindings": [{k: f.get(k) for k in ("type", "description", "severity", "url")}
                           for f in recent_findings]}
    if start_time:
        result["startTime"] = _iso(start_time)
    if end_time:
        result["endTime"] = _iso(end_time)
    return {"content": to_text_content(result)}


def _iso(value):
    if isinstance(value, (int, float)):
        value = datetime.fromtimestamp(value / 1000, timezone.utc)
    return value.isoformat().replace("+00:00", "Z")


async def handle_stop_test(args):
    session_id = str(args.get("sessionId", "")).strip()
    if not session_id:
        raise ValueError("必须提供 sessionId")
    execution = _active_tests().get(session_id)
    if not execution:
        return {"content": to_text_content({"sessionId": session_id, "status": "not_found", "statusText": "未找到",
            "message": f"没有找到会话 {session_id} 的运行中测试"})}
    state = execution.get("state") if isinstance(execution.get("state"), dict) else execution
    if state.get("status") in ("completed", "stopped"):
        return {"content": to_text_content({"sessionId": session_id,
            "status": state["status"], "statusText": display_label(state["status"], STATUSES),
            "message": f"测试已经{'完成' if state['status'] == 'completed' else '停止'}"})}
    state["status"] = "stopped"
    abort = (execution.get("abortController") or {}).get("abort")
    if callable(abort):
        abort()
    logger.info(f"已向测试 {session_id} 发送停止信号")
    return {"content": to_text_content({"sessionId": session_id, "status": "stopping", "statusText": "正在停止",
        "message": "已发送停止信号，测试将在当前操作后结束"})}
