"""MCP tools for exploratory test runs."""

import asyncio
import importlib
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from src.database.database import AppDatabase
from src.services.llm import getDefaultModel
from src.utils.logger import createLogger
from src.utils.locale import ACTIONS, display_label

from src.mcp.types import toTextContent

ExploratoryAgent = importlib.import_module("src.agents.exploratory").ExploratoryAgent
logger = createLogger("mcp:exploratory")
agentInstances = {}
backgroundTasks = set()


def _activeTests():
    return importlib.import_module("src.mcp.server").activeTests


async def handleRunExploratoryTest(args):
    baseUrl = str(args.get("baseUrl", "")).strip()
    parsed = urlparse(baseUrl)
    if not baseUrl or not parsed.scheme or not parsed.netloc:
        raise ValueError(f'无效的 baseUrl："{args.get("baseUrl")}"')
    maxSteps = args.get("maxSteps") if isinstance(args.get("maxSteps"), (int, float)) else 50
    testSessionId = args.get("sessionId", "").strip() if isinstance(args.get("sessionId"), str) and args["sessionId"].strip() else f"exp-{int(time.time() * 1000)}"
    authConfig = None
    if args.get("authRequired"):
        email = (args.get("authEmail") or "").strip()
        password = (args.get("authPassword") or "").strip()
        appId = (args.get("authAppIdentifier") or "").strip() or "mcp-test"
        if not email or not password:
            raise ValueError("authRequired 为 true，但缺少 authEmail 或 authPassword")
        authConfig = {"required": True, "appIdentifier": appId,
                      "credentials": {"email": email, "password": password}}
        logger.info(f"会话 {testSessionId} 已配置登录凭据，应用标识：{appId}")
    _activeTests()[testSessionId] = {"sessionId": testSessionId, "baseUrl": baseUrl,
        "status": "pending", "startTime": datetime.now(timezone.utc),
        "findingsCount": 0, "visitedUrlsCount": 0, "progress": 0}
    db = AppDatabase.getInstance()
    model = getDefaultModel()
    task = asyncio.create_task(startTestInBackground({"baseUrl": baseUrl, "maxSteps": maxSteps,
        "sessionId": testSessionId, "model": model, "db": db, "auth": authConfig}))
    backgroundTasks.add(task)
    task.add_done_callback(backgroundTasks.discard)
    return {"content": toTextContent({"sessionId": testSessionId, "status": "started",
        "message": f"已开始对 {baseUrl} 进行探索性测试", "authConfigured": bool(authConfig),
        "stats": {"visitedPages": 0, "findingsCount": 0, "queueLength": 0}})}


async def startTestInBackground(options):
    baseUrl = options["baseUrl"]
    maxSteps = options["maxSteps"]
    sessionId = options["sessionId"]
    try:
        config = {"baseUrl": baseUrl, "maxSteps": maxSteps, "sessionId": sessionId,
                  "model": options["model"], "auth": options.get("auth")}
        agent = ExploratoryAgent(config)
        agentInstances[sessionId] = agent
        logger.info(f"正在启动后台测试 {sessionId}")
        execution = _activeTests().get(sessionId)
        if execution:
            execution["status"] = "running"
            execution["currentAction"] = "正在启动浏览器……"
        await agent.start()
        logger.info(f"会话 {sessionId} 的测试代理已启动")
        completed = False
        steps = 0
        while not completed and steps < maxSteps:
            current = _activeTests().get(sessionId)
            if current and current.get("status") == "stopped":
                logger.info(f"测试 {sessionId} 已从外部停止")
                break
            result = await agent.step()
            steps += 1
            completed = result["completed"]
            if execution:
                execution["progress"] = min(100, round(steps / maxSteps * 100))
                execution["currentAction"] = display_label(result["action"], ACTIONS)
                execution["visitedUrlsCount"] = len(agent.getVisitedUrls())
                execution["findingsCount"] = len(agent.getFindings())
            if completed:
                logger.info(f"测试 {sessionId} 已在 {steps} 步后完成")
                break
            await asyncio.sleep(0.5)
        if execution:
            execution["status"] = "completed" if completed else "stopped"
            execution["endTime"] = datetime.now(timezone.utc)
            execution["progress"] = 100
            execution["currentAction"] = "已完成" if completed else "已停止"
        await agent.stop()
        logger.info(f"会话 {sessionId} 的测试代理已停止")
    except Exception as error:
        logger.error(f"测试 {sessionId} 失败：{error}")
        execution = _activeTests().get(sessionId)
        if execution:
            execution["status"] = "failed"
            execution["endTime"] = datetime.now(timezone.utc)
            execution["lastError"] = str(error)
    finally:
        agentInstances.pop(sessionId, None)


def getAgentInstance(sessionId):
    return agentInstances.get(sessionId)
