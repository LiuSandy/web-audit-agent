"""MCP tools for exploratory test runs."""

import asyncio
import importlib
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from src.agents.exploratory import ExploratoryAgent
from src.database.database import AppDatabase
from src.services.llm import get_default_model
from src.utils.logger import create_logger
from src.utils.locale import ACTIONS, display_label

from src.mcp.types import to_text_content

logger = create_logger("mcp:exploratory")
agent_instances = {}
background_tasks = set()


def _active_tests():
    return importlib.import_module("src.mcp.server").active_tests


async def handle_run_exploratory_test(args):
    base_url = str(args.get("baseUrl", "")).strip()
    parsed = urlparse(base_url)
    if not base_url or not parsed.scheme or not parsed.netloc:
        raise ValueError(f'无效的 baseUrl："{args.get("baseUrl")}"')
    max_steps = args.get("maxSteps") if isinstance(args.get("maxSteps"), (int, float)) else 50
    test_session_id = args.get("sessionId", "").strip() if isinstance(args.get("sessionId"), str) and args["sessionId"].strip() else f"exp-{int(time.time() * 1000)}"
    auth_config = None
    if args.get("authRequired"):
        email = (args.get("authEmail") or "").strip()
        password = (args.get("authPassword") or "").strip()
        app_id = (args.get("authAppIdentifier") or "").strip() or "mcp-test"
        if not email or not password:
            raise ValueError("authRequired 为 true，但缺少 authEmail 或 authPassword")
        auth_config = {"required": True, "appIdentifier": app_id,
                      "credentials": {"email": email, "password": password}}
        logger.info(f"会话 {test_session_id} 已配置登录凭据，应用标识：{app_id}")
    _active_tests()[test_session_id] = {"sessionId": test_session_id, "baseUrl": base_url,
        "status": "pending", "startTime": datetime.now(timezone.utc),
        "findingsCount": 0, "visitedUrlsCount": 0, "progress": 0}
    db = AppDatabase.get_instance()
    model = get_default_model()
    task = asyncio.create_task(start_test_in_background({"baseUrl": base_url, "maxSteps": max_steps,
        "sessionId": test_session_id, "model": model, "db": db, "auth": auth_config}))
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return {"content": to_text_content({"sessionId": test_session_id, "status": "started",
        "message": f"已开始对 {base_url} 进行探索性测试", "authConfigured": bool(auth_config),
        "stats": {"visitedPages": 0, "findingsCount": 0, "queueLength": 0}})}


async def start_test_in_background(options):
    base_url = options["baseUrl"]
    max_steps = options["maxSteps"]
    session_id = options["sessionId"]
    try:
        config = {"baseUrl": base_url, "maxSteps": max_steps, "sessionId": session_id,
                  "model": options["model"], "auth": options.get("auth")}
        agent = ExploratoryAgent(config)
        agent_instances[session_id] = agent
        logger.info(f"正在启动后台测试 {session_id}")
        execution = _active_tests().get(session_id)
        if execution:
            execution["status"] = "running"
            execution["currentAction"] = "正在启动浏览器……"
        await agent.start()
        logger.info(f"会话 {session_id} 的测试代理已启动")
        completed = False
        steps = 0
        while not completed and steps < max_steps:
            current = _active_tests().get(session_id)
            if current and current.get("status") == "stopped":
                logger.info(f"测试 {session_id} 已从外部停止")
                break
            result = await agent.step()
            steps += 1
            completed = result["completed"]
            if execution:
                execution["progress"] = min(100, round(steps / max_steps * 100))
                execution["currentAction"] = display_label(result["action"], ACTIONS)
                execution["visitedUrlsCount"] = len(agent.get_visited_urls())
                execution["findingsCount"] = len(agent.get_findings())
            if completed:
                logger.info(f"测试 {session_id} 已在 {steps} 步后完成")
                break
            await asyncio.sleep(0.5)
        if execution:
            execution["status"] = "completed" if completed else "stopped"
            execution["endTime"] = datetime.now(timezone.utc)
            execution["progress"] = 100
            execution["currentAction"] = "已完成" if completed else "已停止"
        await agent.stop()
        logger.info(f"会话 {session_id} 的测试代理已停止")
    except Exception as error:
        logger.error(f"测试 {session_id} 失败：{error}")
        execution = _active_tests().get(session_id)
        if execution:
            execution["status"] = "failed"
            execution["endTime"] = datetime.now(timezone.utc)
            execution["lastError"] = str(error)
    finally:
        agent_instances.pop(session_id, None)


def get_agent_instance(session_id):
    return agent_instances.get(session_id)
