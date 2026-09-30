"""MCP tool for single-page test runs."""

import asyncio
import importlib
import time

from src.agents.single_page import SinglePageTestingAgent
from src.database.database import AppDatabase
from src.mcp.types import to_text_content
from src.utils.logger import create_logger

logger = create_logger("mcp:single-page")
background_tasks = set()


def _active_tests():
    return importlib.import_module("src.mcp.server").active_tests


async def handle_run_single_page_test(args):
    session_id = args.get("sessionId") or f"sp-{int(time.time() * 1000)}"
    initial_state = {"sessionId": session_id, "testPlan": None, "results": [],
        "currentTestIndex": -1, "status": "planning",
        "currentAction": "正在初始化浏览器……", "lastError": None,
        "startTime": int(time.time() * 1000)}
    _active_tests()[session_id] = {"sessionId": session_id, "state": initial_state,
                               "abortController": {"abort": lambda: None}}
    task = asyncio.create_task(_run_single_page_in_background(session_id, args))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return {"content": to_text_content({"sessionId": session_id,
        "status": "planning", "statusText": "规划中",
        "targetUrl": args.get("targetUrl"), "authConfigured": bool(args.get("authRequired")),
        "message": f'已开始测试页面 {args.get("targetUrl")}。可用 get_test_status 查询会话 "{session_id}" 的进度。'})}


async def _run_single_page_in_background(session_id, args):
    try:
        AppDatabase.get_instance()
        auth = None
        if args.get("authRequired"):
            auth = {"required": True, "appIdentifier": args.get("authAppIdentifier") or "mcp-test"}
            if args.get("authEmail"):
                auth["credentials"] = {"email": args["authEmail"],
                                       "password": args.get("authPassword") or ""}
        agent = SinglePageTestingAgent({"targetUrl": args["targetUrl"],
            "maxTestCases": args.get("maxTestCases") or 20,
            "strategy": args.get("strategy") or "comprehensive",
            "sessionId": session_id, "auth": auth})
        entry = _active_tests().get(session_id)
        if entry:
            entry["abortController"] = {"abort": lambda: (logger.info(f"已请求停止单页测试 {session_id}"), agent.stop())}
            entry["state"] = {**entry["state"], "currentAction": "浏览器已启动，正在发现页面元素……"}
        final_state = await agent.start()
        entry2 = _active_tests().get(session_id)
        if entry2:
            entry2["state"] = final_state
    except Exception as error:
        logger.error(f"单页测试 {session_id} 失败：", error)
        entry = _active_tests().get(session_id)
        if entry:
            entry["state"] = {**entry["state"], "status": "failed",
                "lastError": str(error), "currentAction": "执行失败",
                "endTime": int(time.time() * 1000)}
