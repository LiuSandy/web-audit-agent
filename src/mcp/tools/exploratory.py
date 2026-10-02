"""MCP tools for exploratory test runs."""

import asyncio
from contextlib import aclosing
import importlib
import time
from datetime import datetime, timezone
from urllib.parse import urlparse

from src.agents.exploratory import ExploratoryAgent
from src.database.database import AppDatabase
from src.services.llm import get_default_model
from src.utils.logger import create_logger
from src.utils.locale import ACTIONS, display_label
from src.cli.core.runner import explore, finish_session
from src.runtime import validate_identifier

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
    max_steps = args.get("maxSteps", 50)
    if type(max_steps) is not int or max_steps < 1:
        raise ValueError("maxSteps 必须是正整数")
    test_session_id = args.get("sessionId", "").strip() if isinstance(args.get("sessionId"), str) and args["sessionId"].strip() else f"exp-{int(time.time() * 1000)}"
    validate_identifier(test_session_id)
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
    model = get_default_model()
    db = AppDatabase.get_instance()
    _active_tests()[test_session_id] = {"sessionId": test_session_id, "baseUrl": base_url,
        "status": "pending", "startTime": datetime.now(timezone.utc),
        "findingsCount": 0, "visitedUrlsCount": 0, "progress": 0}
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
    agent = None
    report_saved = False
    execution = _active_tests().get(session_id)
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
        async with aclosing(explore(agent, max_steps=max_steps, pause=0.5)) as steps:
            async for result in steps:
                if execution:
                    execution["progress"] = min(100, round(agent.run_summary["steps"] / max_steps * 100))
                    execution["currentAction"] = display_label(result["action"], ACTIONS)
                    execution["visitedUrlsCount"] = len(agent.get_visited_urls())
                    execution["findingsCount"] = len(agent.get_findings())
                current = _active_tests().get(session_id)
                if current and current.get("status") == "stopped":
                    agent.run_summary["terminationReason"] = "cancelled"
                    break
        report_path, _ = await finish_session(agent, agent.config, False)
        report_saved = True
        if execution:
            execution.update({"status": "stopped" if execution.get("status") == "stopped" else "completed",
                              "endTime": datetime.now(timezone.utc), "reportPath": report_path,
                              "runId": agent.config["runId"], "terminationReason": agent.run_summary["terminationReason"]})
    except Exception as error:
        logger.error(f"测试 {session_id} 失败：{error}")
        execution = _active_tests().get(session_id)
        if execution:
            execution["status"] = "failed"
            execution["endTime"] = datetime.now(timezone.utc)
            execution["lastError"] = str(error)
    finally:
        if agent and agent.session_ready and not report_saved:
            try:
                await finish_session(agent, agent.config, False)
            except Exception as error:
                logger.error(f"保存 MCP 运行结果失败：{error}")
        agent_instances.pop(session_id, None)


def get_agent_instance(session_id):
    return agent_instances.get(session_id)
