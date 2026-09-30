"""WebAudit interactive CLI entry."""

import asyncio
import importlib
import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

import questionary

from src.agents.exploratory import ExploratoryAgent
from src.database.database import AppDatabase
from src.utils.logger import createLogger, setVerbose
from src.utils.locale import ACTIONS, display_label
from src.utils.report import generateReport

CredentialProvider = importlib.import_module("src.auth.credential-provider").CredentialProvider
_repo_spec = importlib.util.spec_from_file_location(
    "src.repositories.session_repository", Path(__file__).parent / "repositories" / "session.repository.py")
_repo_module = importlib.util.module_from_spec(_repo_spec)
_repo_spec.loader.exec_module(_repo_module)
SessionRepository = _repo_module.SessionRepository
logger = createLogger("cli")


def _sessionId():
    timestamp = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return "session-" + timestamp.replace(":", "-").replace(".", "-")


async def _text(message, default=None):
    result = await questionary.text(message, default=default or "").ask_async()
    if result is None:
        print("操作已取消。")
        sys.exit(0)
    return result or default or ""


async def _confirm(message, default=False):
    result = await questionary.confirm(message, default=default).ask_async()
    if result is None:
        print("操作已取消。")
        sys.exit(0)
    return result


async def _select(message, choices):
    result = await questionary.select(message, choices=choices).ask_async()
    if result is None:
        print("操作已取消。")
        sys.exit(0)
    return result


def wrapText(str, maxWidth=80):
    if not str:
        return ""
    words = str.split(" ")
    if not words:
        return ""
    lines = []
    currentLine = words[0] or ""
    for word in words[1:]:
        word = word or ""
        if len(currentLine) + 1 + len(word) <= maxWidth:
            currentLine += " " + word
        else:
            lines.append(currentLine)
            currentLine = word
    lines.append(currentLine)
    return "\n".join(lines)


async def main():
    print("✨ 欢迎使用网站探索测试工具 ✨")
    defaultUrl = "https://www.lius-node.com"
    baseUrl = await _text("请输入目标网站地址：", defaultUrl)
    isAutonomous = await _confirm("启用自主模式？（每一步无需人工确认）")
    isVerbose = await _confirm("显示详细日志？（包含工具输出）")
    setVerbose(isVerbose)
    enableTestGeneration = await _confirm(
        "根据发现的问题生成自动化测试？", True)
    testConfig = {}
    if enableTestGeneration:
        testExecutionMode = await _select("端到端测试执行方式：", [
            questionary.Choice("仅生成，不执行", value="dry-run"),
            questionary.Choice("依次执行", value="sequential"),
            questionary.Choice("并行执行", value="parallel")])
        showAdvanced = await _confirm("配置高级测试选项？")
        maxConcurrencyValue = 4
        timeoutValue = 30000
        retryCountValue = 2
        if showAdvanced:
            maxConcurrencyInput = await _text("最大并行测试数：", "4")
            timeoutInput = await _text("测试超时时间（毫秒）：", "30000")
            retryCountInput = await _text("失败后的重试次数：", "2")
            maxConcurrencyValue = int(maxConcurrencyInput) if maxConcurrencyInput.isdigit() and int(maxConcurrencyInput) else 4
            timeoutValue = int(timeoutInput) if timeoutInput.isdigit() and int(timeoutInput) else 30000
            retryCountValue = int(retryCountInput) if retryCountInput.isdigit() and int(retryCountInput) else 2
        testConfig = {"testOutputDir": "./generated-tests", "includeE2ETests": True,
            "testDryRun": testExecutionMode == "dry-run",
            "testParallelExecution": testExecutionMode == "parallel",
            "testMaxConcurrency": maxConcurrencyValue, "testTimeout": timeoutValue,
            "testRetryCount": retryCountValue}
    db = AppDatabase.getInstance()
    sessionRepo = SessionRepository(db.getDatabase())
    existingSessions = sessionRepo.listSessions()[:5]
    if existingSessions:
        choices = [questionary.Choice("开始新会话", value="new")]
        choices.extend(questionary.Choice(f"继续会话：{id}", value=id) for id in existingSessions)
        sessionAction = await _select("会话管理", choices)
        sessionId = _sessionId() if sessionAction == "new" else sessionAction
    else:
        sessionId = _sessionId()
    print(f"当前会话 ID：{sessionId}")
    isAuthRequired = await _confirm("目标网站需要登录吗？")
    authConfig = None
    if isAuthRequired:
        credProvider = CredentialProvider(db.getDatabase())
        existingCreds = await credProvider.listCredentials()
        useExisting = False
        selectedAppId = ""
        if existingCreds:
            choices = [questionary.Choice("输入新凭据", value="new")]
            choices.extend(questionary.Choice(f"使用已保存凭据：{id}", value=id) for id in existingCreds)
            credAction = await _select("选择登录凭据", choices)
            if credAction != "new":
                useExisting = True
                selectedAppId = credAction
        if useExisting:
            authConfig = {"required": True, "appIdentifier": selectedAppId}
            print(f"使用已保存的凭据：{selectedAppId}")
        else:
            appIdentifier = await _text("请输入凭据标识（例如 local-app）：", "default-app")
            email = await _text("邮箱或用户名：")
            password = await questionary.password("密码：").ask_async()
            if password is None:
                print("操作已取消。")
                sys.exit(0)
            authConfig = {"required": True, "appIdentifier": appIdentifier,
                          "credentials": {"email": email, "password": password}}
    config = {"baseUrl": baseUrl, "maxSteps": 10, "sessionId": sessionId,
              "auth": authConfig, "enableTestGeneration": enableTestGeneration, **testConfig}
    agent = ExploratoryAgent(config)

    async def generateAndDisplayReport():
        try:
            print("正在生成报告……")
            reportPath = await generateReport(agent.getFindings(), agent.getVisitedUrls(),
                                              config["sessionId"], config["baseUrl"])
            print(f"报告已保存至：{reportPath}")
            try:
                reportContent = Path(reportPath).read_text(encoding="utf-8")
                print("\n报告预览\n" + reportContent)
            except Exception:
                print("无法读取报告文件以供预览。", file=sys.stderr)
        except Exception as error:
            logger.error("生成报告失败：", error)
            print("生成报告失败", file=sys.stderr)

    try:
        print("正在启动测试代理和浏览器……")
        await agent.start()
        print("测试代理已启动")
        nextGuidance = None
        running = True
        while running:
            print("测试代理正在分析并执行操作……")
            result = await agent.step(nextGuidance)
            nextGuidance = None
            print(f"本步操作完成：{display_label(result['action'], ACTIONS)}")
            if result.get("stats"):
                stats = result["stats"]
                print(f"当前页面：{stats['currentUrl']}\n待访问页面：{stats['queueLength']}\n"
                      f"已访问页面：{stats['visitedCount']}\n发现问题：{stats['findingsCount']}\n\n"
                      f"操作：\n{display_label(result['action'], ACTIONS)}\n\n原因：\n{wrapText(result['reason'], 80)}")
            else:
                print(f"原因：\n{wrapText(result['reason'], 80)}\n\n操作：\n{display_label(result['action'], ACTIONS)}")
            if result["completed"]:
                print("测试代理已结束探索。")
                running = False
                break
            if isAutonomous:
                if not running:
                    break
                await asyncio.sleep(1)
                continue
            explorationOptions = [questionary.Choice("继续探索", value="continue"),
                questionary.Choice("提供指导或反馈", value="guidance"),
                questionary.Choice("停止并生成报告", value="stop")]
            if enableTestGeneration:
                explorationOptions.append(questionary.Choice("立即生成测试（随后继续）", value="generate-tests"))
            answer = await questionary.select("下一步要做什么？", choices=explorationOptions).ask_async()
            if answer is None:
                running = False
                break
            if answer == "stop":
                running = False
            elif answer == "guidance":
                userGuidance = await questionary.text("请输入下一步的指导：").ask_async()
                if userGuidance is None:
                    continue
                nextGuidance = userGuidance
                print(f'已记录指导："{nextGuidance}"')
            elif answer == "generate-tests":
                try:
                    print("正在根据当前发现生成测试……")
                    generatedTests = await agent.generateTests()
                    if generatedTests:
                        summary = {priority: len([t for t in generatedTests if t["priority"] == priority])
                                   for priority in ("high", "medium", "low")}
                        print(f"✅ 已根据当前发现生成 {len(generatedTests)} 个自动化测试")
                        print(f"📊 已生成 {len(generatedTests)} 个端到端测试（高优先级 {summary['high']}，中优先级 {summary['medium']}，低优先级 {summary['low']}）")
                    else:
                        print("当前发现未能生成测试")
                except Exception as error:
                    logger.error("生成测试失败：", error)
                    print("生成测试失败，继续探索……")
                continue
        await generateAndDisplayReport()
        if enableTestGeneration:
            try:
                print("正在根据发现的问题生成自动化测试……")
                generatedTests = await agent.generateTests()
                if generatedTests:
                    testSummary = {"total": 0}
                    for test in generatedTests:
                        testSummary[test["testType"]] = testSummary.get(test["testType"], 0) + 1
                        testSummary[test["priority"]] = testSummary.get(test["priority"], 0) + 1
                        testSummary["total"] += 1
                    print(f"📊 端到端测试生成摘要：\n• 测试总数：{testSummary['total']}\n"
                          f"• 高优先级：{testSummary.get('high', 0)}\n"
                          f"• 中优先级：{testSummary.get('medium', 0)}\n"
                          f"• 低优先级：{testSummary.get('low', 0)}\n\n"
                          "📁 测试文件：./generated-tests/\n📄 执行报告：./reports/")
                else:
                    print("未生成测试（没有发现问题或未启用测试生成）")
            except Exception as error:
                logger.error("生成测试失败：", error)
                print("生成测试时出错，但探索已完成。")
    except Exception as error:
        if type(error).__name__ == "AbortError" or "cancel" in str(error):
            print("\n\n⚠️  用户已取消，正在保存报告……\n")
        else:
            print("测试代理执行失败")
            logger.error("测试代理执行失败：", error)
            print(f"严重错误：{error}", file=sys.stderr)
        await generateAndDisplayReport()
    finally:
        await agent.stop()
        print("再见！👋")


if __name__ == "__main__":
    asyncio.run(main())
