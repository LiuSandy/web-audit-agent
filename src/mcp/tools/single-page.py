"""MCP tool for single-page test runs."""

import asyncio
import importlib
import time

from src.database.database import AppDatabase
from src.mcp.types import toTextContent
from src.utils.logger import createLogger

SinglePageTestingAgent = importlib.import_module("src.agents.single-page").SinglePageTestingAgent
logger = createLogger("mcp:single-page")
backgroundTasks = set()


def _activeTests():
    return importlib.import_module("src.mcp.server").activeTests


async def handleRunSinglePageTest(args):
    sessionId = args.get("sessionId") or f"sp-{int(time.time() * 1000)}"
    initialState = {"sessionId": sessionId, "testPlan": None, "results": [],
        "currentTestIndex": -1, "status": "planning",
        "currentAction": "正在初始化浏览器……", "lastError": None,
        "startTime": int(time.time() * 1000)}
    _activeTests()[sessionId] = {"sessionId": sessionId, "state": initialState,
                               "abortController": {"abort": lambda: None}}
    task = asyncio.create_task(_runSinglePageInBackground(sessionId, args))
    backgroundTasks.add(task)
    task.add_done_callback(backgroundTasks.discard)
    return {"content": toTextContent({"sessionId": sessionId,
        "status": "planning", "statusText": "规划中",
        "targetUrl": args.get("targetUrl"), "authConfigured": bool(args.get("authRequired")),
        "message": f'已开始测试页面 {args.get("targetUrl")}。可用 get_test_status 查询会话 "{sessionId}" 的进度。'})}


async def _runSinglePageInBackground(sessionId, args):
    try:
        AppDatabase.getInstance()
        auth = None
        if args.get("authRequired"):
            auth = {"required": True, "appIdentifier": args.get("authAppIdentifier") or "mcp-test"}
            if args.get("authEmail"):
                auth["credentials"] = {"email": args["authEmail"],
                                       "password": args.get("authPassword") or ""}
        agent = SinglePageTestingAgent({"targetUrl": args["targetUrl"],
            "maxTestCases": args.get("maxTestCases") or 20,
            "strategy": args.get("strategy") or "comprehensive",
            "sessionId": sessionId, "auth": auth})
        entry = _activeTests().get(sessionId)
        if entry:
            entry["abortController"] = {"abort": lambda: (logger.info(f"已请求停止单页测试 {sessionId}"), agent.stop())}
            entry["state"] = {**entry["state"], "currentAction": "浏览器已启动，正在发现页面元素……"}
        finalState = await agent.start()
        entry2 = _activeTests().get(sessionId)
        if entry2:
            entry2["state"] = finalState
    except Exception as error:
        logger.error(f"单页测试 {sessionId} 失败：", error)
        entry = _activeTests().get(sessionId)
        if entry:
            entry["state"] = {**entry["state"], "status": "failed",
                "lastError": str(error), "currentAction": "执行失败",
                "endTime": int(time.time() * 1000)}
