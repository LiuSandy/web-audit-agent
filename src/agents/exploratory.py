"""LLM-driven exploratory testing agent."""

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.prompts import PromptTemplate
from langsmith import traceable
from playwright.async_api import async_playwright

from src.auth.auth_manager import AuthenticationManager
from src.database.database import AppDatabase
from src.runtime import get_runtime, new_run_id, private_directory
from src.repositories.session_repository import SessionRepository
from src.services.llm import get_default_model
from src.services.test_executor import TestExecutor
from src.services.test_generator import TestGenerator
from src.tools.broken_images import find_broken_images
from src.tools.console_errors import ConsoleMonitor
from src.tools.crawler import crawl_site
from src.tools.network_errors import NetworkMonitor
from src.tools.validation_errors import find_validation_errors
from src.types.index import OrderedSet
from src.utils.logger import create_logger
from src.utils.locale import BROKEN_IMAGE_REASONS, display_label

logger = create_logger("agent:exploratory")


def build_step_metadata(session_id, state, url):
    """Builds LangSmith metadata describing one agent step."""
    return {"sessionId": session_id or "", "step": state["steps"], "url": url,
            "visitedCount": len(state["visitedUrls"]), "queueLength": len(state["todoQueue"])}

_SNAPSHOT_CALLBACK = r'''
(visitedUrls) => {
  const elements = document.querySelectorAll("a, button, input, select, textarea, img, label");
  return Array.from(elements).map((el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0)
      return null;
    let text = "";
    let extra = "";
    const tagName = el.tagName.toLowerCase();
    if (tagName === "img") {
      text = `[Image: ${el.alt || el.src}]`;
    } else if (tagName === "input") {
      const input = el;
      extra = `[Type: ${input.type}, Name: ${input.name}, ID: ${input.id}]`;
      if (input.placeholder)
        extra += ` [Placeholder: ${input.placeholder}]`;
    } else if (tagName === "select") {
      const select = el;
      extra = `[ID: ${select.id}, Name: ${select.name}]`;
    } else {
      text = el.textContent?.trim() || "";
    }
    let selector = "";
    if (el.id) {
      selector = `#${CSS.escape(el.id)}`;
    } else if (tagName === "a" && el.href) {
      const href = el.getAttribute("href");
      const absoluteHref = el.href;
      if (href)
        selector = `a[href="${CSS.escape(href)}"]`;
      const normalizedHref = absoluteHref.replace(/\/$/, "");
      const isVisited = visitedUrls.includes(absoluteHref) || visitedUrls.includes(normalizedHref);
      if (isVisited)
        extra += " [VISITED]";
    } else if (el.classList.length) {
      selector = `${tagName}.${Array.from(el.classList, cls => CSS.escape(cls)).join(".")}`;
    } else {
      selector = tagName;
    }
    return {
      tag: tagName,
      text: text.substring(0, 100),
      extra,
      selector
    };
  }).filter(Boolean);
}
'''

# 系统提示词模板：jinja2 渲染——字面单大括号免转义，变量值单趟注入、不被二次
# 解析。jinja2 对缺变量静默渲染为空串，因此新增或改名占位符时必须同步两处：
# _step 里的 format 调用与 tests/agents/exploratory-prompt.test.py 的变量钉死测试。
# 另：jinja2 渲染默认丢弃模板结尾的单个换行（keep_trailing_newline=False），
# 故模板文本以两个换行结尾补回一个——黄金测试锁定渲染结果与迁移前逐字节一致。
_SYSTEM_PROMPT_TEMPLATE = PromptTemplate.from_template(r'''
你是 Web Audit Agent。探索 {{baseUrl}}，操作页面并发现问题。
请用简体中文填写所有面向用户的内容，包括 reason、record_finding 的 description；保留 JSON 字段名、动作名、问题类型、严重程度、URL 和 CSS 选择器的原值。

目标：访问可发现页面，点击按钮、填写表单，尝试登录、购物等主要流程；检查功能、校验、图片、错误提示和体验问题。
记录问题前先观察实际结果。按钮无响应、无效输入被接受、缺少反馈或流程异常时，可用 record_finding；不要仅凭猜测认定问题。
优先访问待办队列中的新页面，不要重复点击标记为 [VISITED] 的链接。尝试空表单、无效输入和边界值；避免在同一页面循环。

当前状态：
- 页面地址：{{url}}
- 页面标题：{{title}}
- 已访问页面数：{{visitedCount}}
- 待办队列：{{todoQueueJson}}

最近三步：
{{recentHistory}}

可用动作：
- navigate(url)：访问指定页面。
- click(selector)：点击元素。
- fill_form(selector, value)：填写输入框。
- add_to_queue(urls)：把同站页面加入待办队列。
- find_broken_images()：检查当前页面的破损图片。
- record_finding(type, description, severity)：记录问题。type 使用 functional_bug、validation_error、ux_issue、bug 或 other；severity 使用 low、medium、high 或 critical；description 必须用中文。
- finish()：待办队列为空、陷入循环或主要流程已充分测试时结束。

只返回一个 JSON 对象（不要 Markdown 代码块、不要解释文字），每个返回都必含 action 与 reason；params 按动作而定，无参数的动作传 {}：

{"action": "click", "params": {"selector": "#login-submit"}, "reason": "提交登录表单，先用错误凭据观察校验反馈"}

各动作的 params 结构：
{"action": "navigate", "params": {"url": "https://example.com/pricing"}}
{"action": "click", "params": {"selector": "#add-to-cart"}}
{"action": "fill_form", "params": {"selector": "#username", "value": "demo-user"}}
{"action": "add_to_queue", "params": {"urls": ["https://example.com/help"]}}
{"action": "record_finding", "params": {"type": "functional_bug", "description": "点击结账按钮后无任何响应", "severity": "high"}}
{"action": "find_broken_images", "params": {}}
{"action": "finish", "params": {}}

reason 必须用中文说明本步假设或目标。看到登录表单时尝试有效和无效凭据；有购物流程时尝试加入购物车并结账。每次点击或填表后观察结果，如有明确异常则记录。队列有新页面时优先使用 navigate。

''', template_format="jinja2")


class SessionTargetError(ValueError):
    """Saved exploration target conflicts with this invocation."""


class ExploratoryAgent:
    """Web Audit Agent：LLM 驱动的探索式测试，在真实浏览器中逐步决策并发现问题。"""

    def __init__(self, config):
        """初始化 Agent。config 为扁平 dict，键名保持 camelCase 协议契约。

        Args:
            baseUrl: 探索目标站点，必填。用于系统提示词、预爬起点与首次导航；
                恢复会话时按 scheme + 主机 + 端口校验目标一致，不一致即拒绝。
            model: LLM 模型对象，缺省用 get_default_model()。只存在于内存，
                永不写入会话状态。
            sessionId: 会话 ID，恢复与落库的键；缺省由入口层生成。
            auth: 认证选项（required / appIdentifier / credentials）；恢复会话
                时若未传，依据落库的 authAppIdentifier 重建以复用已存凭据。
            runId: 本次运行 ID，缺省自动生成。
            artifactDir: 本次运行产物目录 runs/<sessionId>/<runId>/，缺省自动生成。
            exportDir: 结束后产物导出目标（由 runner.py 消费），缺省不导出。
            maxSteps: 步数预算。仅作为 runConfig 快照随会话落库；真正的循环
                预算由 explore(max_steps=...) 传入（见 runner.py）。
            maxFailures: 连续失败阈值。同上，仅快照。
            maxPages: 预发现阶段最多访问的页面数（start() 直接消费，是真实
                预算而非快照），默认 20；显式传 0 合法生效（跳过预爬）。
            enableTestGeneration: 是否在结束时从发现的问题生成测试；同时门控
                下方全部 test* 参数，关闭时 TestGenerator/TestExecutor 均不实例化。
            testOutputDir: 生成测试落盘目录，缺省为运行产物目录下 generated-tests/。
            includeE2ETests: 是否额外生成 pytest E2E 版本；仅显式 False 才关闭
                （`is not False` 判断），当前 CLI 固定传 True。
            testDryRun: 试运行：跳过 pytest 子进程，直接返回成功桩结果。
            testParallelExecution: 并行执行生成测试（按 testMaxConcurrency 分块）。
            testMaxConcurrency: 并行块大小，默认 4。
            testTimeout: 单个测试的子进程超时（毫秒），默认 30000。
            testRetryCount: 单个测试失败重试次数，默认 2；显式传 0 合法生效。
        """
        self.session_ready = False
        self.browser = None
        self.page = None
        self.playwright = None
        self.console_monitor = None
        self.network_monitor = None
        self.config = dict(config)
        # 身份默认值：不传时自动生成，产物落在 runs/<sessionId>/<runId>/ 下。
        self.config.setdefault("runId", new_run_id())
        self.config.setdefault("artifactDir", str(get_runtime().run_dir(self.config.get("sessionId") or "anonymous", self.config["runId"])))
        self.config.setdefault("testOutputDir", str(get_runtime().run_dir(self.config.get("sessionId") or "anonymous", self.config["runId"]) / "generated-tests"))
        config = self.config
        self.model = config.get("model") or get_default_model()
        self.db = AppDatabase.get_instance()
        database = self.db.get_database()
        self.session_repo = SessionRepository(database)
        self.auth_manager = AuthenticationManager(database, {"storageType": "sqlite"})
        # 会话状态整体随 save_state() 落库、start() 恢复。history 是行为日志
        # （情景记忆）：每步追加动作/理由/页面/参数/结果，既作为提示词里的
        # 短期记忆，也支撑停滞检测与断点恢复。
        self.state = {"visitedUrls": OrderedSet(), "findings": [], "steps": 0,
                      "history": [], "todoQueue": []}
        # test* 配置项属于 TestGenerator/TestExecutor 子系统，这里只做装配转发；
        # enableTestGeneration 同时门控两者，纯探索运行不触测试生成。
        self.test_generator = None
        self.test_executor = None
        if config.get("enableTestGeneration"):
            test_config = {"outputDir": config.get("testOutputDir") or "./generated-tests",
                          "includeE2E": config.get("includeE2ETests") is not False}
            self.test_generator = TestGenerator(self.model, test_config)
            execution_config = {"dryRun": config.get("testDryRun") or False,
                "parallel": config.get("testParallelExecution") or False,
                "maxConcurrency": config.get("testMaxConcurrency") or 4,
                "timeout": config.get("testTimeout") or 30000,
                # 用 get(默认值) 而非 `or`：显式传 0 次重试会生效保留；其余键
                # 经 `or` 读取，传 0 会被吞掉并落到默认值。
                "retryCount": config.get("testRetryCount", 2)}
            self.test_executor = TestExecutor(execution_config)

    async def start(self):
        logger.log("正在启动 Web Audit Agent……")
        if self.config.get("sessionId"):
            loaded_state = self.session_repo.load_state(self.config["sessionId"])
            if loaded_state:
                if loaded_state.get("agentType") == "single_page":
                    raise SessionTargetError("单页测试会话不能恢复为探索会话，请使用新的会话 ID")
                self.state = loaded_state
                logger.info(f"已恢复会话 {self.config['sessionId']}，当前为第 {self.state['steps']} 步")
            else:
                logger.info(f"未找到会话 {self.config['sessionId']} 的状态，开始新测试")
        saved_config = self.state.get("runConfig") or {}
        saved_url = self.state.get("baseUrl")
        if not saved_url:
            # 兜底推断目标站点：baseUrl 缺失时，从已访问页面、行为日志与
            # 问题记录里取第一个带主机的 URL 做一致性校验。
            urls = list(self.state.get("visitedUrls") or [])
            urls += [h.get("url") for h in self.state.get("history", []) if h.get("url")]
            urls += [f.get("url") for f in self.state.get("findings", []) if f.get("url")]
            saved_url = next((u for u in urls if urlparse(u).netloc), None)
        if saved_url:
            old, new = urlparse(saved_url), urlparse(self.config["baseUrl"])
            if (old.scheme.lower(), old.hostname, old.port or (443 if old.scheme == "https" else 80)) != (
                new.scheme.lower(), new.hostname, new.port or (443 if new.scheme == "https" else 80)):
                raise SessionTargetError(f"会话目标 {saved_url} 与本次目标 {self.config['baseUrl']} 不一致")
        elif self.state["steps"]:
            raise SessionTargetError("旧会话无法确定目标站点，请开始新会话")
        if not self.config.get("auth") and saved_config.get("authAppIdentifier"):
            self.config["auth"] = {"required": True, "appIdentifier": saved_config["authAppIdentifier"]}
        self.state["baseUrl"] = self.state.get("baseUrl") or self.config["baseUrl"]
        # 只落库引用与非敏感选项；model 对象与凭据绝不写入状态。
        # maxSteps/maxFailures 仅为会话快照：本次运行的真实预算来自
        # explore() 的参数（见 runner.py），与这两个键无关。
        # authAppIdentifier 是恢复会话复用已存凭据的依据。
        self.state["runId"] = self.config["runId"]
        self.state["artifactDir"] = self.config["artifactDir"]
        self.state["runConfig"] = {key: self.config.get(key) for key in (
            "maxSteps", "maxFailures", "maxPages", "enableTestGeneration", "testDryRun", "testParallelExecution",
            "testMaxConcurrency", "testTimeout", "testRetryCount")}
        self.state["runConfig"]["authAppIdentifier"] = (self.config.get("auth") or {}).get("appIdentifier")
        self.state["visitedUrls"] = OrderedSet(self.state.get("visitedUrls") or [])
        self.session_ready = True
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        self.page = await self.browser.new_page()
        self.console_monitor = ConsoleMonitor(self.page)
        self.network_monitor = NetworkMonitor(self.page)
        logger.log("控制台与网络监视器已启动")
        auth = self.config.get("auth") or {}
        if auth.get("required"):
            await self.page.goto(self.config["baseUrl"])
            if auth.get("credentials"):
                await self.auth_manager.store_credentials(auth["appIdentifier"], auth["credentials"])
                logger.log("已保存或更新本次会话的凭据")
            logger.log("目标网站需要登录，正在尝试登录……")
            auth_res = await self.auth_manager.authenticate(self.page, auth["appIdentifier"])
            if auth_res["success"]:
                logger.log(f"✓ 已通过 {auth_res['method']} 登录")
            else:
                logger.error(f"✗ 登录失败：{auth_res.get('error')}")
                raise RuntimeError(f"登录失败：{auth_res.get('error')}")
        if self.state["steps"] == 0:
            logger.log("正在预先发现页面……")
            # 用 get(默认值) 而非 `or`：显式传 0（跳过预爬）会生效保留。
            discovered_urls = await crawl_site(self.page, self.config["baseUrl"],
                                               max_pages=self.config.get("maxPages", 20))
            self.state["todoQueue"] = list(discovered_urls)
            logger.log(f"已将发现的 {len(discovered_urls)} 个页面加入待办队列")
            await self.page.goto(self.config["baseUrl"])
            logger.log(f"已访问 {self.config['baseUrl']}")
        else:
            # 断点续测：回到行为日志最后一步所在的页面，而不是从首页重来。
            last_url = self.state["history"][-1].get("url") if self.state["history"] else None
            if last_url:
                await self.page.goto(last_url)
                logger.log(f"已从 {last_url} 恢复访问")
            else:
                await self.page.goto(self.config["baseUrl"])

    def save_run(self, report_path=None):
        if self.session_ready and self.config.get("sessionId"):
            self.session_repo.save_run(self.config["sessionId"], self.config["runId"],
                                       self.config["artifactDir"], report_path,
                                       self.state.get("lastRun") or getattr(self, "run_summary", {}))

    def save_state(self):
        if self.config.get("sessionId") and self.session_ready:
            self.session_repo.save_state(self.config["sessionId"], self.state)

    async def stop(self):
        errors = []
        if self.browser:
            try:
                await self.browser.close()
            except Exception as error:
                errors.append(str(error))
            finally:
                self.browser = None
                self.page = None
        if self.playwright:
            try:
                await self.playwright.stop()
            except Exception as error:
                errors.append(str(error))
            finally:
                self.playwright = None
        if errors:
            raise RuntimeError("清理浏览器失败：" + "；".join(errors))
        logger.log("Web Audit Agent 已停止")

    async def step(self, guidance=None):
        if not self.page:
            raise RuntimeError("Web Audit Agent 尚未启动")
        self.state["steps"] += 1
        url = self.page.url
        self.state["visitedUrls"].add(url)
        metadata = build_step_metadata(self.config.get("sessionId"), self.state, url)
        try:
            result = await self._step(guidance, url, langsmith_extra={"metadata": metadata})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            result = {"action": "error", "reason": str(error), "result": str(error),
                      "success": False, "completed": False}
        if result.get("action") == "error":
            result["success"] = False
            # 失败步同样入行为日志：下一轮模型才能看到上一步为何失败。
            self.state["history"].append({"action": "error", "reason": result["reason"],
                                          "url": url, "success": False, "result": result.get("result", result["reason"])})
        self.save_state()
        return result

    @traceable(name="agent.step", run_type="chain")
    async def _step(self, guidance=None, url=None):
        title = await self.page.title()
        visited_list = list(self.state["visitedUrls"])
        snapshot = await self.page.evaluate(_SNAPSHOT_CALLBACK, visited_list)
        # 短期记忆：把最近 3 步格式化后注入提示词——模型无状态，据此才知道
        # 上一步做了什么、结果如何，才能连贯决策。
        history = self.state["history"]
        history_slice = history[-3:]
        history_start_index = max(0, len(history) - 3)
        recent_history = "\n".join(
            f"第 {history_start_index + i + 1} 步：{h['action']}（原因：{h['reason']}）→ 结果：{h.get('result') or '无'}"
            for i, h in enumerate(history_slice))
        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(
            baseUrl=self.config["baseUrl"], url=url, title=title,
            visitedCount=str(len(self.state["visitedUrls"])),
            todoQueueJson=json.dumps(self.state["todoQueue"], separators=(",", ":")),
            recentHistory=recent_history or "None")
        # 反循环启发式：以下统计都从行为日志尾部回溯，命中时向提示词追加
        # 警告，促使模型换页面或结束。
        steps_on_current_url = 0
        for history_step in reversed(history):
            if history_step and history_step["url"] == url:
                steps_on_current_url += 1
            else:
                break
        last3_steps = history[-3:]
        first_of_last3 = last3_steps[0] if last3_steps else None
        is_repeating_action = len(last3_steps) == 3 and first_of_last3 and all(
            s["action"] == first_of_last3["action"] and
            json.dumps(s.get("params"), separators=(",", ":")) == json.dumps(first_of_last3.get("params"), separators=(",", ":"))
            for s in last3_steps)
        recent_findings = len([f for f in self.state["findings"] if f["url"] == url])
        if is_repeating_action:
            system_prompt += "\n\n### 检测到重复操作 ###\n你连续三次执行了完全相同的操作。请选择其他元素、访问新页面，或在无法继续时调用 finish()。"
        elif steps_on_current_url > 10 and recent_findings == 0:
            unique_interactions = len({s["action"] + json.dumps(s.get("params"), separators=(",", ":"))
                                      for s in history[-steps_on_current_url:]})
            if unique_interactions < steps_on_current_url * 0.5:
                system_prompt += f"\n\n### 检测到停滞 ###\n你已在当前页面重复操作 {steps_on_current_url} 步。如不能立即发现具体新问题，请访问其他页面或结束。"
        if not self.state["todoQueue"]:
            system_prompt += "\n\n### 待办队列为空 ###\n可发现页面已经探索完毕。除非当前页面还有明确的测试目标，否则下一步调用 finish()。"
        if guidance:
            system_prompt += f'\n\n### 用户指导 ###\n请优先遵循："{guidance}"'
        user_message = f"\n当前页面元素（简化）：\n{json.dumps(snapshot, indent=2, ensure_ascii=False)}\n\n下一步做什么？只返回原始 JSON 对象。\n    "
        timeout_ms = 30000
        max_retries = 3
        response = None
        for attempt in range(1, max_retries + 1):
            try:
                response = await asyncio.wait_for(self.model.ainvoke([
                    SystemMessage(content=system_prompt), HumanMessage(content=user_message)]),
                    timeout=timeout_ms / 1000)
                break
            except Exception as error:
                is_rate_limit = "429" in str(error) or getattr(error, "status", None) == 429
                if is_rate_limit and attempt < max_retries:
                    wait_time = 2 ** attempt * 2000
                    logger.warn(f"触发模型请求限流，等待 {wait_time} 毫秒……")
                    await asyncio.sleep(wait_time / 1000)
                    continue
                logger.error(f"模型调用失败（第 {attempt} 次尝试）：{error}")
                if attempt == max_retries:
                    return {"action": "error", "reason": f"模型调用失败：{error}", "completed": False}
        content = response.content if isinstance(response.content, str) else json.dumps(response.content)
        try:
            cleaned = content.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(cleaned)
        except Exception:
            logger.error("无法解析模型响应", content)
            return {"action": "error", "reason": "模型返回的 JSON 无效", "completed": False}
        if not isinstance(parsed, dict) or not isinstance(parsed.get("action"), str) or not isinstance(parsed.get("reason"), str):
            return {"action": "error", "reason": "模型响应缺少有效 action/reason", "completed": False, "success": False}
        logger.log(f"Agent 决策：{parsed.get('reason')}")
        logger.log(f"执行操作：{parsed.get('action')}")
        action_result = await self.execute_action(parsed["action"], parsed.get("params"))
        # 行为日志条目：action/reason 为本轮决策，url 为执行后的落点页面
        # （停滞检测据此统计在同一页面的连续步数），其余为执行结果。
        self.state["history"].append({"action": parsed["action"], "reason": parsed["reason"],
                                      "url": self.page.url, "params": parsed.get("params"),
                                      **action_result})
        stats = {"currentUrl": self.page.url, "queueLength": len(self.state["todoQueue"]),
                 "visitedCount": len(self.state["visitedUrls"]), "findingsCount": len(self.state["findings"])}
        return {"action": parsed["action"], "reason": parsed["reason"],
                "completed": parsed["action"] == "finish" and action_result["success"], "stats": stats, **action_result}

    @traceable(name="execute_action", run_type="tool")
    async def execute_action(self, action, params):
        result = await self._execute_action(action, params)
        return result if isinstance(result, dict) else {"success": True, "result": result}

    async def _execute_action(self, action, params):
        if not self.page:
            return {"success": False, "result": "Web Audit Agent 尚未启动"}
        try:
            if action == "add_to_queue":
                new_urls = params if isinstance(params, list) else [params] if isinstance(params, str) else (params or {}).get("urls", [])
                added_count = 0
                base_hostname = urlparse(self.config["baseUrl"]).hostname
                for u in new_urls:
                    try:
                        absolute_url = urljoin(self.page.url, u)
                        if urlparse(absolute_url).hostname != base_hostname:
                            continue
                        if absolute_url not in self.state["visitedUrls"] and absolute_url not in self.state["todoQueue"]:
                            self.state["todoQueue"].append(absolute_url)
                            added_count += 1
                    except Exception:
                        pass
                msg = f"已将 {added_count} 个新页面加入待办队列。"
                logger.log(msg)
                return msg
            if action == "navigate":
                target_url = params if isinstance(params, str) else (params or {}).get("url")
                if not target_url or not isinstance(target_url, str):
                    err = f"访问失败：URL 参数无效。收到的参数：{json.dumps(params, ensure_ascii=False)}"
                    logger.error(err)
                    return {"success": False, "result": err}
                logger.log(f"正在访问：{target_url}")
                self.state["todoQueue"] = [u for u in self.state["todoQueue"] if u != target_url]
                await self.page.goto(target_url)
                return f"已访问 {target_url}"
            if action == "click":
                selector = params if isinstance(params, str) else (params or {}).get("selector")
                if not selector:
                    raise ValueError("点击操作需要选择器（params.selector 或字符串）")
                logger.log(f"正在点击选择器：{selector}")
                await self.page.click(selector)
                return f"已点击 {selector}"
            if action == "fill_form":
                if not isinstance(params, dict) or not params.get("selector") or "value" not in params:
                    raise ValueError("填写表单需要 params.selector 和 params.value")
                logger.log(f"正在填写表单：{params['selector']} = {params['value']}")
                await self.page.fill(params["selector"], params["value"])
                return f"已填写 {params['selector']}"
            if action == "find_broken_images":
                self.state["visitedUrls"].add(self.page.url)
                findings = await find_broken_images(self.page)
                broken_img_screenshot = await self.take_screenshot("broken-images") if findings else ""
                for f in findings:
                    self.record_unique_finding({"type": "broken_image",
                        "description": f"图片加载异常：{f['src']}（原因：{display_label(f['reason'], BROKEN_IMAGE_REASONS)}）",
                        "url": self.page.url, "selector": f["selector"],
                        "severity": "medium", "screenshot": broken_img_screenshot})
                return f"发现 {len(findings)} 张加载异常的图片"
            if action == "record_finding":
                bug_screenshot = await self.take_screenshot("bug")
                self.record_unique_finding({"type": params.get("type") or "bug",
                    "description": params["description"], "url": self.page.url,
                    "severity": params.get("severity") or "medium", "screenshot": bug_screenshot})
                return f"已记录问题：{params['description']}"
            if action == "finish":
                logger.log("模型决定结束探索")
                return "已完成"
            logger.warn(f"未知操作：{action}")
            return {"success": False, "result": f"未知操作：{action}"}
        except Exception as error:
            logger.error(f"执行操作失败：{error}")
            return {"success": False, "result": f"执行操作失败：{error}"}
        finally:
            if action in ("navigate", "click", "fill_form"):
                await self.perform_automatic_bug_scanning()

    @traceable(name="automatic_bug_scanning", run_type="tool")
    async def perform_automatic_bug_scanning(self):
        if not self.page:
            return
        try:
            await self.page.wait_for_timeout(500)
            if self.console_monitor:
                for error in self.console_monitor.get_errors():
                    self.record_unique_finding({"type": "console_error",
                        "description": f"控制台{'错误' if error['type'] == 'error' else '警告'}：{error['message']}",
                        "url": error["url"], "severity": "medium" if error["type"] == "error" else "low",
                        "metadata": {"timestamp": error["timestamp"], "stackTrace": error.get("stackTrace")}})
            if self.network_monitor:
                for error in self.network_monitor.get_errors():
                    severity = "high" if error["status"] >= 500 else "medium" if error["status"] >= 400 else "low"
                    self.record_unique_finding({"type": "network_error",
                        "description": f"网络请求异常：{error['status']} {error['method']} {error['url']}",
                        "url": error["pageUrl"], "severity": severity,
                        "metadata": {"requestUrl": error["url"], "method": error["method"],
                                     "status": error["status"], "statusText": error["statusText"],
                                     "responseBody": error.get("responseBody")}})
            for error in await find_validation_errors(self.page):
                self.record_unique_finding({"type": "validation_error",
                    "description": f"表单校验提示：{error['message']}",
                    "url": self.page.url, "selector": error["selector"], "severity": "low",
                    "metadata": {"location": error.get("location")}})
        except Exception as error:
            logger.warn(f"自动问题扫描失败：{error}")

    async def take_screenshot(self, prefix):
        if not self.page:
            return ""
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z").replace(":", "-").replace(".", "-")
        filename = f"{prefix}-{timestamp}.png"
        path = Path(self.config["artifactDir"]) / "screenshots" / filename
        private_directory(path.parent)
        try:
            await self.page.screenshot(path=str(path), full_page=True)
            return str(path)
        except Exception as error:
            logger.warn(f"截图失败，已跳过：{error}")
            return ""

    def record_unique_finding(self, finding):
        existing_finding = next((f for f in self.state["findings"]
            if f["type"] == finding["type"] and f["description"] == finding["description"]
            and f.get("selector") == finding.get("selector")), None)
        if existing_finding:
            existing_finding["count"] = (existing_finding.get("count") or 1) + 1
            if not existing_finding.get("occurrences"):
                existing_finding["occurrences"] = []
            if finding["url"] not in existing_finding["occurrences"] and existing_finding["url"] != finding["url"]:
                existing_finding["occurrences"].append(finding["url"])
            logger.info(f"已合并重复问题：{finding['description']}（累计 {existing_finding['count']} 次）")
        else:
            finding["count"] = 1
            self.state["findings"].append(finding)
            logger.info(f"已记录新问题：{finding['description']}")

    def get_findings(self):
        return self.state["findings"]

    def get_visited_urls(self):
        return list(self.state["visitedUrls"])

    @traceable(name="agent.generate_tests", run_type="chain")
    async def generate_tests(self):
        if not self.test_generator:
            logger.warn("未启用测试生成")
            return []
        logger.info(f"正在根据 {len(self.state['findings'])} 条发现生成测试")
        try:
            generated_tests = await self.test_generator.generate_tests_from_findings(
                self.state["findings"], self.state, self.config["baseUrl"])
            if self.test_executor:
                saved_files = await self.test_executor.save_tests(generated_tests)
                logger.info(f"已保存 {len(saved_files)} 个测试文件")
                results = await self.test_executor.execute_tests(generated_tests)
                logger.info(f"已执行 {len(results)} 个测试")
                timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z").replace(":", "-").replace(".", "-")
                report_path = str(Path(self.config["artifactDir"]) / f"test-execution-{timestamp}.md")
                await self.test_executor.save_test_report(results, report_path)
            return generated_tests
        except Exception as error:
            logger.error("生成测试失败：", error)
            return []
