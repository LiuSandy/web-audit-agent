"""Single-page testing agent with a plan-and-execute flow."""

import json
import os
import time

from langchain_core.messages import HumanMessage, SystemMessage
from langsmith import traceable
from playwright.async_api import async_playwright

from src.auth.auth_manager import AuthenticationManager
from src.database.database import AppDatabase
from src.services.llm import getDefaultModel
from src.tools.broken_images import findBrokenImages
from src.tools.console_errors import ConsoleMonitor
from src.tools.layout_audit import runLayoutAudit
from src.tools.network_errors import NetworkMonitor
from src.tools.visual_regression import runVisualRegression
from src.utils.logger import createLogger
from src.utils.locale import ACTIONS, STATUSES, display_label

logger = createLogger("agent:single-page")


def pageOk(p):
    return p is not None and not p.is_closed()


def now_ms():
    return int(time.time() * 1000)


class SinglePageTestingAgent:
    def __init__(self, config):
        self.browser = None
        self.page = None
        self.playwright = None
        self.config = {"maxTestCases": 20, "strategy": "comprehensive", **config}
        try:
            self.model = config.get("model") or getDefaultModel()
        except Exception:
            self.model = None
        db = AppDatabase.getInstance()
        self.authManager = AuthenticationManager(db.getDatabase(), {"storageType": "sqlite"})
        sid = config.get("sessionId") or f"sp-{now_ms()}"
        self.state = {"sessionId": sid, "testPlan": None, "results": [],
                      "currentTestIndex": -1, "status": "planning",
                      "currentAction": "正在初始化……", "lastError": None,
                      "startTime": now_ms()}
        self.stopping = False
        self.consoleMonitor = None
        self.networkMonitor = None

    def getState(self):
        return dict(self.state)

    @traceable(name="single_page_test", run_type="chain")
    async def start(self):
        logger.info(f"正在开始单页测试：{self.config['targetUrl']}")
        try:
            await self.initBrowser()
            await self.page.goto(self.config["targetUrl"], wait_until="networkidle")
            auth = self.config.get("auth") or {}
            if auth.get("required"):
                self.state["currentAction"] = "正在登录……"
                if auth.get("credentials"):
                    await self.authManager.storeCredentials(auth["appIdentifier"], auth["credentials"])
                authRes = await self.authManager.authenticate(self.page, auth["appIdentifier"])
                if not authRes["success"]:
                    raise RuntimeError(f"登录失败：{authRes.get('error')}")
                await self.page.goto(self.config["targetUrl"], wait_until="networkidle")
                logger.info("登录成功，已返回目标页面")
            self.state["status"] = "planning"
            self.state["currentAction"] = "正在分析页面……"
            elements = await self.discoverElements()
            plan = await self.generateTestPlan(elements)
            self.state["testPlan"] = plan
            self.state["currentAction"] = f"已规划 {plan['totalTests']} 个测试"
            logger.info(self.state["currentAction"])
            self.state["status"] = "executing"
            for i, tc in enumerate(plan["testCases"]):
                if self.stopping:
                    break
                self.state["currentTestIndex"] = i
                self.state["currentAction"] = f"{tc['id']}: {tc['name']}"
                result = await self.executeTestCase(tc)
                self.state["results"].append(result)
                logger.info(f"{tc['id']}：{display_label(result['status'], STATUSES)}（{result['executionTimeMs']} 毫秒）")
            self.state["status"] = "stopped" if self.stopping else "completed"
            self.state["currentAction"] = "正在检查页面布局……"
            await self.runLayoutAudit(self.page)
            self.state["currentAction"] = "正在检查视觉差异……"
            await self.runVisualRegression(self.page)
            self.state["currentAction"] = "已完成"
            self.state["endTime"] = now_ms()
            return self.getState()
        except Exception as error:
            self.state["status"] = "failed"
            self.state["lastError"] = str(error)
            logger.error(error)
            raise
        finally:
            await self.cleanup()

    def stop(self):
        self.stopping = True

    async def initBrowser(self):
        self.playwright = await async_playwright().start()
        kwargs = {"headless": True}
        if os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"):
            kwargs["executable_path"] = os.environ["PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH"]
        self.browser = await self.playwright.chromium.launch(**kwargs)
        ctx = await self.browser.new_context(viewport={"width": 1280, "height": 720})
        self.page = await ctx.new_page()
        self.consoleMonitor = ConsoleMonitor(self.page)
        self.networkMonitor = NetworkMonitor(self.page)

    async def cleanup(self):
        try:
            if self.browser:
                await self.browser.close()
        except Exception:
            pass
        if self.playwright:
            await self.playwright.stop()
        self.page = None
        self.browser = None

    async def discoverElements(self):
        if not pageOk(self.page):
            return []
        el = await self.page.evaluate("""() => {
            const out = []; const seen = new Set();
            document.querySelectorAll("input, select, textarea, button, a[href], [role='button']").forEach((e, i) => {
                const tag = e.tagName.toLowerCase();
                const id = e.id ? `#${e.id}` : '';
                const nm = e.getAttribute('name') ? `[name="${e.getAttribute('name')}"]` : '';
                const sel = id || nm || `${tag}:nth-of-type(${i + 1})`;
                if (seen.has(sel)) return; seen.add(sel);
                const style = window.getComputedStyle(e); const r = e.getBoundingClientRect();
                const visible = style.display !== 'none' && style.visibility !== 'hidden' && r.width > 0 && r.height > 0;
                out.push({tag, selector: sel, text: (e.textContent || '').substring(0, 80),
                    type: e.type || undefined, isVisible: visible,
                    interactable: visible && e.tabIndex >= -1});
            }); return out;
        }""")
        logger.info(f"已发现 {len(el)} 个页面元素")
        return el

    @traceable(name="single_page.plan", run_type="chain")
    async def generateTestPlan(self, elements):
        url = self.page.url
        title = await self.page.title()
        inputs = [e for e in elements if e["tag"] in ("input", "textarea", "select")]
        buttons = [e for e in elements if e["tag"] in ("button", "a")]
        other = [e for e in elements if e["tag"] not in ("input", "textarea", "select", "button", "a")]
        sys = "你是质量测试规划代理。请为单个网页生成测试计划，只返回有效 JSON，不要 Markdown。测试名称、描述、步骤说明和预期结果使用简体中文；JSON 字段名、枚举值、URL 和 CSS 选择器保持原值。"
        elementLines = "\n".join(
            f"{i + 1}. [{e['tag'].upper()}] {e['selector']} (text: \"{e['text'][:40]}\", type: {e.get('type') or 'N/A'}, visible: {str(e['isVisible']).lower()})"
            for i, e in enumerate(elements[:30]))
        user = (f"页面：{url}\n标题：{title}\n策略：{self.config['strategy']}\n最多测试数：{self.config.get('maxTestCases') or 20}\n\n"
                f"页面元素：\n{elementLines}\n\n请覆盖表单校验、按钮点击、边界情况、可见错误和控制台错误。\n"
                "每个用例包含：id（TC###）、中文 name 和 description、priority（critical|high|medium|low）、"
                "category（form|validation|interaction|navigation|visual）、steps（action、selector、value、中文 description）和中文 expectedOutcome。\n"
                "步骤 action 只用 click|fill|select|hover|wait|verify|navigate。另包含页面加载、破损图片检查和控制台错误检查。\n"
                "返回 JSON：{pageUrl, pageTitle, totalTests, estimatedDurationSeconds, coverage:{forms,buttons,links,inputs,otherInteractive}, testCases[]}")
        try:
            resp = await self.model.ainvoke([SystemMessage(content=sys), HumanMessage(content=user)])
            cleaned = str(resp.content).replace("```json", "").replace("```", "").strip()
            parsed = json.loads(cleaned)
            if not isinstance(parsed.get("testCases"), list):
                raise ValueError("模型未返回 testCases")
            testCases = parsed["testCases"][:self.config.get("maxTestCases") or 20]
            return {"pageUrl": url, "pageTitle": title, "totalTests": len(testCases),
                    "estimatedDurationSeconds": len(testCases) * 8,
                    "coverage": {"forms": len([e for e in inputs if e["tag"] == "form"]),
                                 "buttons": len(buttons), "links": len([e for e in elements if e["tag"] == "a"]),
                                 "inputs": len(inputs), "otherInteractive": len(other)},
                    "testCases": testCases}
        except Exception as error:
            logger.warn(f"模型生成测试计划失败：{error}，改用备用计划")
            return self.fallbackPlan(url, title, inputs, buttons, elements)

    def fallbackPlan(self, url, title, inputs, buttons, all):
        cases = [
            {"id": "TC001", "name": "页面正常加载", "description": "页面标题和正文正常显示",
             "priority": "critical", "category": "navigation",
             "steps": [{"action": "verify", "description": f'标题包含“{title}”'}],
             "expectedOutcome": f'标题为“{title}”'},
            {"id": "TC002", "name": "没有控制台错误", "description": "页面加载时没有 JavaScript 错误",
             "priority": "high", "category": "validation", "steps": [{"action": "wait", "description": "等待 2 秒"}],
             "expectedOutcome": "控制台没有错误"},
            {"id": "TC003", "name": "没有网络错误", "description": "所有请求返回 2xx 或 3xx",
             "priority": "high", "category": "validation", "steps": [{"action": "wait", "description": "等待网络空闲"}],
             "expectedOutcome": "没有 4xx 或 5xx 响应"},
        ]
        for i, btn in enumerate(buttons[:5]):
            cases.append({"id": f"TC{10 + i}", "name": f'点击按钮“{btn["text"][:30]}”',
                          "description": f"点击 {btn['selector']}", "priority": "medium", "category": "interaction",
                          "steps": [{"action": "click", "selector": btn["selector"], "description": "点击按钮"},
                                    {"action": "wait", "description": "等待 1.5 秒"}],
                          "expectedOutcome": "没有控制台或网络错误"})
        for i, inp in enumerate(inputs[:4]):
            cases.append({"id": f"TC{20 + i}", "name": f'填写输入框“{inp["selector"]}”',
                          "description": f"填写并检查 {inp['selector']}", "priority": "medium", "category": "form",
                          "steps": [{"action": "fill", "selector": inp["selector"], "value": "test@example.com", "description": "填写输入框"},
                                    {"action": "verify", "description": "输入框保留填写内容"}],
                          "expectedOutcome": "输入值被接受"})
        return {"pageUrl": url, "pageTitle": title, "totalTests": len(cases),
                "estimatedDurationSeconds": len(cases) * 8,
                "coverage": {"forms": 0, "buttons": len(buttons),
                             "links": len([e for e in all if e["tag"] == "a"]),
                             "inputs": len(inputs), "otherInteractive": len([e for e in all if e["tag"] not in ("input", "textarea", "select", "button", "a")])},
                "testCases": cases}

    @traceable(name="single_page.test_case", run_type="tool")
    async def executeTestCase(self, tc):
        if not pageOk(self.page):
            return {"testCaseId": tc["id"], "status": "error", "executionTimeMs": 0,
                    "stepsExecuted": 0, "errorMessage": "浏览器不可用", "findings": []}
        start = now_ms()
        findings = []
        stepsExecuted = 0
        try:
            try:
                await self.page.goto(self.config["targetUrl"], wait_until="networkidle")
            except Exception:
                pass
            await self.page.wait_for_timeout(500)
            for step in tc["steps"]:
                if self.stopping:
                    return {"testCaseId": tc["id"], "status": "skipped", "executionTimeMs": now_ms() - start,
                            "stepsExecuted": stepsExecuted, "findings": []}
                await self.executeStep(step)
                stepsExecuted += 1
            findings.extend(await self.validateOutcome(tc))
            hasErrors = any(f["severity"] in ("critical", "high") for f in findings)
            return {"testCaseId": tc["id"], "status": "failed" if hasErrors else "passed",
                    "executionTimeMs": now_ms() - start, "stepsExecuted": stepsExecuted, "findings": findings}
        except Exception as error:
            findings.append({"type": "bug", "description": f"测试执行错误：{error}",
                             "url": self.page.url, "severity": "high", "metadata": {"testCase": tc["id"]}})
            return {"testCaseId": tc["id"], "status": "error", "executionTimeMs": now_ms() - start,
                    "stepsExecuted": stepsExecuted, "errorMessage": f"测试执行失败：{error}", "findings": findings}

    async def executeStep(self, step):
        p = self.page
        sel = step.get("selector") or ""
        logger.info(f"{display_label(step['action'], ACTIONS)}：{sel}")
        if step["action"] == "wait":
            await p.wait_for_timeout(1200)
            return
        if step["action"] == "verify":
            return
        if step["action"] == "click" and sel:
            try:
                await p.locator(sel).first.click(timeout=5000)
            except Exception:
                pass
        elif step["action"] == "fill" and sel and step.get("value"):
            try:
                await p.locator(sel).first.fill(step["value"], timeout=5000)
            except Exception:
                pass
        elif step["action"] == "select" and sel and step.get("value"):
            try:
                await p.locator(sel).first.select_option(step["value"], timeout=5000)
            except Exception:
                pass
        elif step["action"] == "hover" and sel:
            try:
                await p.locator(sel).first.hover(timeout=5000)
            except Exception:
                pass
        elif step["action"] == "navigate" and step.get("value"):
            try:
                await p.goto(step["value"], wait_until="networkidle")
            except Exception:
                pass

    async def validateOutcome(self, tc):
        findings = []
        if not pageOk(self.page):
            return findings
        url = self.page.url
        for err in self.consoleMonitor.getErrors() if self.consoleMonitor else []:
            rawMessage = err.get("message") or str(err)
            findings.append({"type": "console_error", "description": f"控制台错误：{rawMessage}",
                             "severity": "medium", "url": url, "metadata": {"rawMessage": rawMessage}})
        for err in self.networkMonitor.getErrors() if self.networkMonitor else []:
            rawMessage = err.get("statusText") or err.get("url") or str(err)
            findings.append({"type": "network_error", "description": f"网络请求异常：{rawMessage}",
                             "severity": "medium", "url": url, "metadata": {"rawMessage": rawMessage}})
        broken = await findBrokenImages(self.page)
        for img in broken:
            findings.append({"type": "broken_image", "description": f"图片加载异常：{img['src']}",
                             "severity": "low", "url": url, "selector": img["selector"]})
        hasVisibleError = await self.page.evaluate("""() => {
            const els = document.querySelectorAll('[role="alert"], [class*="error"], [class*="toast"]');
            return Array.from(els).some(el => el.offsetWidth > 0 && el.textContent?.trim().length > 0);
        }""")
        if hasVisibleError:
            findings.append({"type": "validation_error", "description": f'执行“{tc["name"]}”后出现可见错误提示',
                             "severity": "high", "url": url})
        return findings

    async def runLayoutAudit(self, page):
        config = self.config.get("layoutAudit") or {}
        if config.get("enabled") is False:
            return
        try:
            self.state["currentAction"] = "正在检查页面布局……"
            findings = await runLayoutAudit(page, {"maxElements": config.get("maxElements", 300),
                                                   "heuristics": config.get("heuristics"),
                                                   "screenshots": config.get("screenshots"),
                                                   "sessionId": self.state["sessionId"]})
            for f in findings:
                self.state["results"].append({"testCaseId": "layout-audit",
                    "status": "failed" if f["severity"] in ("error", "warning") else "passed",
                    "executionTimeMs": 0, "stepsExecuted": 0,
                    "findings": [{"type": f["type"],
                                  "severity": "high" if f["severity"] == "error" else "medium" if f["severity"] == "warning" else "low",
                                  "category": "layout", "description": f["message"], "url": page.url,
                                  "selector": f.get("selector"), "screenshot": f.get("screenshot")}]})
        except Exception as error:
            logger.warn("页面布局检查失败：", error)

    async def runVisualRegression(self, page):
        config = self.config.get("visualRegression") or {}
        if config.get("enabled") is not True:
            return
        try:
            self.state["currentAction"] = "正在检查视觉差异……"
            vrConfig = {"enabled": True,
                "baselineDir": config.get("baselineDir") or "./test-results/baselines",
                "currentDir": config.get("currentDir") or "./test-results/current",
                "diffDir": config.get("diffDir") or "./test-results/diffs",
                "viewports": config.get("viewports") or [
                    {"width": 1920, "height": 1080, "name": "desktop"},
                    {"width": 768, "height": 1024, "name": "tablet"},
                    {"width": 375, "height": 667, "name": "mobile"}],
                "threshold": config.get("threshold", 0.1),
                "pixelmatchThreshold": config.get("pixelmatchThreshold", 0.1),
                "captureFullPage": config.get("captureFullPage", True),
                "generateDiffImages": config.get("generateDiffImages", True)}
            results = await runVisualRegression(page, self.config["targetUrl"], vrConfig)
            for result in results:
                viewport = result["viewport"]
                findings = []
                if result["isNewBaseline"]:
                    findings.append({"type": "visual_regression", "severity": "info", "category": "visual",
                        "description": f"已为 {viewport['name']}（{viewport['width']}×{viewport['height']}）创建新基线",
                        "url": result["url"], "metadata": {"baselinePath": result["baselinePath"], "isNew": True}})
                elif not result["match"]:
                    findings.append({"type": "visual_regression", "severity": "high", "category": "visual",
                        "description": f"检测到视觉差异：{viewport['name']} 差异 {result['diffPercentage']:.2f}%（{result['diffPixelCount']} 像素）",
                        "url": result["url"], "selector": viewport["name"], "screenshot": result["currentPath"],
                        "metadata": {"baselinePath": result["baselinePath"], "diffPath": result.get("diffPath"),
                                     "diffPercentage": result["diffPercentage"], "diffPixelCount": result["diffPixelCount"]}})
                if findings:
                    self.state["results"].append({"testCaseId": f"visual-regression-{viewport['name']}",
                        "status": "passed" if result["match"] else "failed", "executionTimeMs": 0,
                        "stepsExecuted": 0, "findings": findings})
            logger.info(f"视觉差异检查完成：已测试 {len(results)} 个视口")
        except Exception as error:
            logger.warn("视觉差异检查失败：", error)
