"""Port of src/agents/exploratory.ts."""

import asyncio
import importlib
import importlib.util
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

from langchain_core.messages import HumanMessage, SystemMessage
from playwright.async_api import async_playwright

from src.database.database import AppDatabase
from src.services.llm import getDefaultModel
from src.types.index import OrderedSet
from src.utils.logger import createLogger
from src.utils.locale import BROKEN_IMAGE_REASONS, display_label

ConsoleMonitor = importlib.import_module("src.tools.console-errors").ConsoleMonitor
NetworkMonitor = importlib.import_module("src.tools.network-errors").NetworkMonitor
findBrokenImages = importlib.import_module("src.tools.broken-images").findBrokenImages
crawlSite = importlib.import_module("src.tools.crawler").crawlSite
findValidationErrors = importlib.import_module("src.tools.validation-errors").findValidationErrors
AuthenticationManager = importlib.import_module("src.auth.auth-manager").AuthenticationManager
_repo_spec = importlib.util.spec_from_file_location(
    "src.repositories.session_repository", Path(__file__).parents[1] / "repositories" / "session.repository.py")
_repo_module = importlib.util.module_from_spec(_repo_spec)
_repo_spec.loader.exec_module(_repo_module)
SessionRepository = _repo_module.SessionRepository
TestGenerator = importlib.import_module("src.services.test-generator").TestGenerator
TestExecutor = importlib.import_module("src.services.test-executor").TestExecutor

logger = createLogger("agent:exploratory")

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
      selector = `#${el.id}`;
    } else if (tagName === "a" && el.href) {
      const href = el.getAttribute("href");
      const absoluteHref = el.href;
      if (href)
        selector = `a[href="${href}"]`;
      const normalizedHref = absoluteHref.replace(/\/$/, "");
      const isVisited = visitedUrls.includes(absoluteHref) || visitedUrls.includes(normalizedHref);
      if (isVisited)
        extra += " [VISITED]";
    } else if (el.className) {
      selector = `${tagName}.${el.className.split(" ").join(".")}`;
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

_SYSTEM_PROMPT = r'''
你是网站质量测试代理。探索 ${this.config.baseUrl}，操作页面并发现问题。
请用简体中文填写所有面向用户的内容，包括 reason、record_finding 的 description；保留 JSON 字段名、动作名、问题类型、严重程度、URL 和 CSS 选择器的原值。

目标：访问可发现页面，点击按钮、填写表单，尝试登录、购物等主要流程；检查功能、校验、图片、错误提示和体验问题。
记录问题前先观察实际结果。按钮无响应、无效输入被接受、缺少反馈或流程异常时，可用 record_finding；不要仅凭猜测认定问题。
优先访问待办队列中的新页面，不要重复点击标记为 [VISITED] 的链接。尝试空表单、无效输入和边界值；避免在同一页面循环。

当前状态：
- 页面地址：${url}
- 页面标题：${title}
- 已访问页面数：${this.state.visitedUrls.size}
- 待办队列：${JSON.stringify(this.state.todoQueue)}

最近三步：
${recentHistory || "None"}

可用动作：
- navigate(url)：访问指定页面。
- click(selector)：点击元素。
- fill_form(selector, value)：填写输入框。
- add_to_queue(urls)：把同站页面加入待办队列。
- find_broken_images()：检查当前页面的破损图片。
- record_finding(type, description, severity)：记录问题。type 使用 functional_bug、validation_error、ux_issue、bug 或 other；severity 使用 low、medium、high 或 critical；description 必须用中文。
- finish()：待办队列为空、陷入循环或主要流程已充分测试时结束。

只返回有效 JSON 对象，包含 action、params、reason；reason 必须用中文说明本步假设或目标。看到登录表单时尝试有效和无效凭据；有购物流程时尝试加入购物车并结账。每次点击或填表后观察结果，如有明确异常则记录。队列有新页面时优先使用 navigate。
'''


class ExploratoryAgent:
    def __init__(self, config):
        self.browser = None
        self.page = None
        self.playwright = None
        self.consoleMonitor = None
        self.networkMonitor = None
        self.config = config
        self.model = config.get("model") or getDefaultModel()
        self.db = AppDatabase.getInstance()
        database = self.db.getDatabase()
        self.sessionRepo = SessionRepository(database)
        self.authManager = AuthenticationManager(database, {"storageType": "sqlite"})
        self.state = {"visitedUrls": OrderedSet(), "findings": [], "steps": 0,
                      "history": [], "todoQueue": []}
        self.testGenerator = None
        self.testExecutor = None
        if config.get("enableTestGeneration"):
            testConfig = {"outputDir": config.get("testOutputDir") or "./generated-tests",
                          "includeE2E": config.get("includeE2ETests") is not False}
            self.testGenerator = TestGenerator(self.model, testConfig)
            executionConfig = {"dryRun": config.get("testDryRun") or False,
                "parallel": config.get("testParallelExecution") or False,
                "maxConcurrency": config.get("testMaxConcurrency") or 4,
                "timeout": config.get("testTimeout") or 30000,
                "retryCount": config.get("testRetryCount") or 2}
            self.testExecutor = TestExecutor(executionConfig)

    async def start(self):
        logger.log("正在启动探索测试代理……")
        if self.config.get("sessionId"):
            loadedState = self.sessionRepo.loadState(self.config["sessionId"])
            if loadedState:
                self.state = loadedState
                logger.info(f"已恢复会话 {self.config['sessionId']}，当前为第 {self.state['steps']} 步")
            else:
                logger.info(f"未找到会话 {self.config['sessionId']} 的状态，开始新测试")
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=True, args=["--no-sandbox", "--disable-setuid-sandbox"])
        self.page = await self.browser.new_page()
        self.consoleMonitor = ConsoleMonitor(self.page)
        self.networkMonitor = NetworkMonitor(self.page)
        logger.log("控制台与网络监视器已启动")
        if self.state["steps"] == 0:
            logger.log("正在预先发现页面……")
            discoveredUrls = await crawlSite(self.page, self.config["baseUrl"])
            self.state["todoQueue"] = list(discoveredUrls)
            logger.log(f"已将发现的 {len(discoveredUrls)} 个页面加入待办队列")
            auth = self.config.get("auth") or {}
            if auth.get("required"):
                if auth.get("credentials"):
                    await self.authManager.storeCredentials(auth["appIdentifier"], auth["credentials"])
                    logger.log("已保存或更新本次会话的凭据")
                logger.log("目标网站需要登录，正在尝试登录……")
                authRes = await self.authManager.authenticate(self.page, auth["appIdentifier"])
                if authRes["success"]:
                    logger.log(f"✓ 已通过 {authRes['method']} 登录")
                else:
                    logger.error(f"✗ 登录失败：{authRes.get('error')}")
                    raise RuntimeError(f"登录失败：{authRes.get('error')}")
            await self.page.goto(self.config["baseUrl"])
            logger.log(f"已访问 {self.config['baseUrl']}")
        else:
            lastUrl = self.state["history"][-1].get("url") if self.state["history"] else None
            if lastUrl:
                await self.page.goto(lastUrl)
                logger.log(f"已从 {lastUrl} 恢复访问")
            else:
                await self.page.goto(self.config["baseUrl"])

    async def stop(self):
        if self.browser:
            await self.browser.close()
            self.browser = None
            self.page = None
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None
        logger.log("探索测试代理已停止")

    async def step(self, guidance=None):
        if not self.page:
            raise RuntimeError("测试代理尚未启动")
        self.state["steps"] += 1
        url = self.page.url
        title = await self.page.title()
        self.state["visitedUrls"].add(url)
        visitedList = list(self.state["visitedUrls"])
        snapshot = await self.page.evaluate(_SNAPSHOT_CALLBACK, visitedList)
        history = self.state["history"]
        historySlice = history[-3:]
        historyStartIndex = max(0, len(history) - 3)
        recentHistory = "\n".join(
            f"第 {historyStartIndex + i + 1} 步：{h['action']}（原因：{h['reason']}）→ 结果：{h.get('result') or '无'}"
            for i, h in enumerate(historySlice))
        systemPrompt = (_SYSTEM_PROMPT
            .replace("${\n            this.config.baseUrl\n        }", self.config["baseUrl"])
            .replace("${this.config.baseUrl}", self.config["baseUrl"])
            .replace("${url}", url).replace("${title}", title)
            .replace("${this.state.visitedUrls.size}", str(len(self.state["visitedUrls"])))
            .replace("${JSON.stringify(this.state.todoQueue)}", json.dumps(self.state["todoQueue"], separators=(",", ":")))
            .replace('${recentHistory || "None"}', recentHistory or "None"))
        stepsOnCurrentUrl = 0
        for historyStep in reversed(history):
            if historyStep and historyStep["url"] == url:
                stepsOnCurrentUrl += 1
            else:
                break
        last3Steps = history[-3:]
        firstOfLast3 = last3Steps[0] if last3Steps else None
        isRepeatingAction = len(last3Steps) == 3 and firstOfLast3 and all(
            s["action"] == firstOfLast3["action"] and
            json.dumps(s.get("params"), separators=(",", ":")) == json.dumps(firstOfLast3.get("params"), separators=(",", ":"))
            for s in last3Steps)
        recentFindings = len([f for f in self.state["findings"] if f["url"] == url])
        if isRepeatingAction:
            systemPrompt += "\n\n### 检测到重复操作 ###\n你连续三次执行了完全相同的操作。请选择其他元素、访问新页面，或在无法继续时调用 finish()。"
        elif stepsOnCurrentUrl > 10 and recentFindings == 0:
            uniqueInteractions = len({s["action"] + json.dumps(s.get("params"), separators=(",", ":"))
                                      for s in history[-stepsOnCurrentUrl:]})
            if uniqueInteractions < stepsOnCurrentUrl * 0.5:
                systemPrompt += f"\n\n### 检测到停滞 ###\n你已在当前页面重复操作 {stepsOnCurrentUrl} 步。如不能立即发现具体新问题，请访问其他页面或结束。"
        if not self.state["todoQueue"]:
            systemPrompt += "\n\n### 待办队列为空 ###\n可发现页面已经探索完毕。除非当前页面还有明确的测试目标，否则下一步调用 finish()。"
        if guidance:
            systemPrompt += f'\n\n### 用户指导 ###\n请优先遵循："{guidance}"'
        userMessage = f"\n当前页面元素（简化）：\n{json.dumps(snapshot, indent=2, ensure_ascii=False)}\n\n下一步做什么？只返回原始 JSON 对象。\n    "
        timeoutMs = 30000
        maxRetries = 3
        response = None
        for attempt in range(1, maxRetries + 1):
            try:
                response = await asyncio.wait_for(self.model.ainvoke([
                    SystemMessage(content=systemPrompt), HumanMessage(content=userMessage)]),
                    timeout=timeoutMs / 1000)
                break
            except Exception as error:
                isRateLimit = "429" in str(error) or getattr(error, "status", None) == 429
                if isRateLimit and attempt < maxRetries:
                    waitTime = 2 ** attempt * 2000
                    logger.warn(f"触发模型请求限流，等待 {waitTime} 毫秒……")
                    await asyncio.sleep(waitTime / 1000)
                    continue
                logger.error(f"模型调用失败（第 {attempt} 次尝试）：{error}")
                if attempt == maxRetries:
                    return {"action": "error", "reason": f"模型调用失败：{error}", "completed": False}
        content = response.content if isinstance(response.content, str) else json.dumps(response.content)
        try:
            cleaned = content.replace("```json", "").replace("```", "").strip()
            parsed = json.loads(cleaned)
        except Exception:
            logger.error("无法解析模型响应", content)
            return {"action": "error", "reason": "模型返回的 JSON 无效", "completed": False}
        logger.log(f"代理决策：{parsed.get('reason')}")
        logger.log(f"执行操作：{parsed.get('action')} {json.dumps(parsed.get('params'), ensure_ascii=False) if parsed.get('params') else ''}")
        await self.executeAction(parsed["action"], parsed.get("params"))
        self.state["history"].append({"action": parsed["action"], "reason": parsed["reason"],
                                      "url": self.page.url, "params": parsed.get("params")})
        stats = {"currentUrl": self.page.url, "queueLength": len(self.state["todoQueue"]),
                 "visitedCount": len(self.state["visitedUrls"]), "findingsCount": len(self.state["findings"])}
        if self.config.get("sessionId"):
            self.sessionRepo.saveState(self.config["sessionId"], self.state)
        return {"action": parsed["action"], "reason": parsed["reason"],
                "completed": parsed["action"] == "finish", "stats": stats}

    async def executeAction(self, action, params):
        if not self.page:
            return None
        try:
            if action == "add_to_queue":
                newUrls = params if isinstance(params, list) else [params] if isinstance(params, str) else (params or {}).get("urls", [])
                addedCount = 0
                baseHostname = urlparse(self.config["baseUrl"]).hostname
                for u in newUrls:
                    try:
                        absoluteUrl = urljoin(self.page.url, u)
                        if urlparse(absoluteUrl).hostname != baseHostname:
                            continue
                        if absoluteUrl not in self.state["visitedUrls"] and absoluteUrl not in self.state["todoQueue"]:
                            self.state["todoQueue"].append(absoluteUrl)
                            addedCount += 1
                    except Exception:
                        pass
                msg = f"已将 {addedCount} 个新页面加入待办队列。"
                logger.log(msg)
                return msg
            if action == "navigate":
                targetUrl = params if isinstance(params, str) else (params or {}).get("url")
                if not targetUrl or not isinstance(targetUrl, str):
                    err = f"访问失败：URL 参数无效。收到的参数：{json.dumps(params, ensure_ascii=False)}"
                    logger.error(err)
                    return err
                logger.log(f"正在访问：{targetUrl}")
                self.state["todoQueue"] = [u for u in self.state["todoQueue"] if u != targetUrl]
                await self.page.goto(targetUrl)
                return f"已访问 {targetUrl}"
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
                findings = await findBrokenImages(self.page)
                brokenImgScreenshot = await self.takeScreenshot("broken-images") if findings else ""
                for f in findings:
                    self.recordUniqueFinding({"type": "broken_image",
                        "description": f"图片加载异常：{f['src']}（原因：{display_label(f['reason'], BROKEN_IMAGE_REASONS)}）",
                        "url": self.page.url, "selector": f["selector"],
                        "severity": "medium", "screenshot": brokenImgScreenshot})
                return f"发现 {len(findings)} 张加载异常的图片"
            if action == "record_finding":
                bugScreenshot = await self.takeScreenshot("bug")
                self.recordUniqueFinding({"type": params.get("type") or "bug",
                    "description": params["description"], "url": self.page.url,
                    "severity": params.get("severity") or "medium", "screenshot": bugScreenshot})
                return f"已记录问题：{params['description']}"
            if action == "finish":
                logger.log("模型决定结束探索")
                return "已完成"
            logger.warn(f"未知操作：{action}")
            return f"未知操作：{action}"
        except Exception as error:
            logger.error(f"执行操作失败：{error}")
            return f"执行操作失败：{error}"
        finally:
            if action in ("navigate", "click", "fill_form"):
                await self.performAutomaticBugScanning()

    async def performAutomaticBugScanning(self):
        if not self.page:
            return
        try:
            await self.page.wait_for_timeout(500)
            if self.consoleMonitor:
                for error in self.consoleMonitor.getErrors():
                    self.recordUniqueFinding({"type": "console_error",
                        "description": f"控制台{'错误' if error['type'] == 'error' else '警告'}：{error['message']}",
                        "url": error["url"], "severity": "medium" if error["type"] == "error" else "low",
                        "metadata": {"timestamp": error["timestamp"], "stackTrace": error.get("stackTrace")}})
            if self.networkMonitor:
                for error in self.networkMonitor.getErrors():
                    severity = "high" if error["status"] >= 500 else "medium" if error["status"] >= 400 else "low"
                    self.recordUniqueFinding({"type": "network_error",
                        "description": f"网络请求异常：{error['status']} {error['method']} {error['url']}",
                        "url": error["pageUrl"], "severity": severity,
                        "metadata": {"requestUrl": error["url"], "method": error["method"],
                                     "status": error["status"], "statusText": error["statusText"],
                                     "responseBody": error.get("responseBody")}})
            for error in await findValidationErrors(self.page):
                self.recordUniqueFinding({"type": "validation_error",
                    "description": f"表单校验提示：{error['message']}",
                    "url": self.page.url, "selector": error["selector"], "severity": "low",
                    "metadata": {"location": error.get("location")}})
        except Exception as error:
            logger.warn(f"自动问题扫描失败：{error}")

    async def takeScreenshot(self, prefix):
        if not self.page:
            return ""
        timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z").replace(":", "-").replace(".", "-")
        filename = f"{prefix}-{timestamp}.png"
        path = f"reports/screenshots/{filename}"
        try:
            await self.page.screenshot(path=path, full_page=True)
            return f"screenshots/{filename}"
        except Exception as error:
            logger.warn(f"截图失败，已跳过：{error}")
            return ""

    def recordUniqueFinding(self, finding):
        existingFinding = next((f for f in self.state["findings"]
            if f["type"] == finding["type"] and f["description"] == finding["description"]
            and f.get("selector") == finding.get("selector")), None)
        if existingFinding:
            existingFinding["count"] = (existingFinding.get("count") or 1) + 1
            if not existingFinding.get("occurrences"):
                existingFinding["occurrences"] = []
            if finding["url"] not in existingFinding["occurrences"] and existingFinding["url"] != finding["url"]:
                existingFinding["occurrences"].append(finding["url"])
            logger.info(f"已合并重复问题：{finding['description']}（累计 {existingFinding['count']} 次）")
        else:
            finding["count"] = 1
            self.state["findings"].append(finding)
            logger.info(f"已记录新问题：{finding['description']}")

    def getFindings(self):
        return self.state["findings"]

    def getVisitedUrls(self):
        return list(self.state["visitedUrls"])

    async def generateTests(self):
        if not self.testGenerator:
            logger.warn("未启用测试生成")
            return []
        logger.info(f"正在根据 {len(self.state['findings'])} 条发现生成测试")
        try:
            generatedTests = await self.testGenerator.generateTestsFromFindings(
                self.state["findings"], self.state, self.config["baseUrl"])
            if self.testExecutor:
                savedFiles = await self.testExecutor.saveTests(generatedTests)
                logger.info(f"已保存 {len(savedFiles)} 个测试文件")
                results = await self.testExecutor.executeTests(generatedTests)
                logger.info(f"已执行 {len(results)} 个测试")
                timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z").replace(":", "-").replace(".", "-")
                reportPath = f"reports/test-execution-{timestamp}.md"
                await self.testExecutor.saveTestReport(results, reportPath)
            return generatedTests
        except Exception as error:
            logger.error("生成测试失败：", error)
            return []
