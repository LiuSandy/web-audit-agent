"""交互向导：流程与提示文案对齐旧 main()（spec §10 基线），渲染层换 rich。"""
import asyncio
from pathlib import Path

import questionary
from rich.markup import escape
from rich.panel import Panel

from src.agents.exploratory import ExploratoryAgent
from src.auth.credential_provider import CredentialProvider
from src.cli.core.config import RunOptions, build_config, new_session_id
from src.cli.core.console import console, diagnostics, findings_table, friendly_hint, render_step
from src.cli.core.exits import INTERRUPTED, OK, RUN_FAILED
from src.cli.core.runner import StopExploration, explore, finish_session
from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository
from src.utils.logger import set_verbose


class WizardCancelled(Exception):
    """用户在向导提示中取消（questionary 返回 None）。"""


async def _text(message: str, default: str | None = None) -> str:
    result = await questionary.text(message, default=default or "").ask_async()
    if result is None:
        raise WizardCancelled()
    return result or default or ""


async def _confirm(message: str, default: bool = False) -> bool:
    result = await questionary.confirm(message, default=default).ask_async()
    if result is None:
        raise WizardCancelled()
    return result


async def _select(message: str, choices: list) -> object:
    result = await questionary.select(message, choices=choices).ask_async()
    if result is None:
        raise WizardCancelled()
    return result


def _int_or_default(raw: str, fallback: int) -> int:
    return int(raw) if raw.isdigit() and int(raw) else fallback


async def _collect_options() -> RunOptions:
    """问答收集选项；任何一步取消 → WizardCancelled（此时无报告可存，与旧行为一致）。"""
    base_url = await _text("请输入目标网站地址：", "https://www.lius-node.com")
    autonomous = await _confirm("启用自主模式？（每一步无需人工确认）")
    verbose = await _confirm("显示详细日志？（包含工具输出）")
    set_verbose(verbose)
    generate_tests = await _confirm("根据发现的问题生成自动化测试？", True)
    test_mode, max_concurrency, timeout_ms, retry_count = "dry-run", 4, 30000, 2
    if generate_tests:
        test_mode = await _select("端到端测试执行方式：", [
            questionary.Choice("仅生成，不执行", value="dry-run"),
            questionary.Choice("依次执行", value="sequential"),
            questionary.Choice("并行执行", value="parallel")])
        if await _confirm("配置高级测试选项？"):
            max_concurrency = _int_or_default(await _text("最大并行测试数：", "4"), 4)
            timeout_ms = _int_or_default(await _text("测试超时时间（毫秒）：", "30000"), 30000)
            retry_count = _int_or_default(await _text("失败后的重试次数：", "2"), 2)
    db = AppDatabase.get_instance()
    repository = SessionRepository(db.get_database())
    existing = repository.list_sessions()[:5]
    session_id = new_session_id()
    if existing:
        # 注：questionary 会把 value=None 回退成 title，故用 "" 表达「新会话」的假值语义
        choices = [questionary.Choice("开始新会话", value="")]
        choices.extend(questionary.Choice(f"继续会话：{identifier}", value=identifier)
                       for identifier in existing)
        session_id = await _select("会话管理", choices) or new_session_id()
    console.print(f"当前会话 ID：{session_id}")
    auth_email = auth_password = auth_app_identifier = use_saved = None
    if await _confirm("目标网站需要登录吗？"):
        credential_provider = CredentialProvider(db.get_database())
        saved = await credential_provider.list_credentials()
        if saved:
            # 注：questionary 会把 value=None 回退成 title，故用 "" 表达「输入新凭据」的假值语义
            choices = [questionary.Choice("输入新凭据", value="")]
            choices.extend(questionary.Choice(f"使用已保存凭据：{identifier}", value=identifier)
                           for identifier in saved)
            use_saved = await _select("选择登录凭据", choices)
        if use_saved:
            console.print(f"使用已保存的凭据：{use_saved}")
        else:
            auth_app_identifier = await _text("请输入凭据标识（例如 local-app）：", "default-app")
            auth_email = await _text("邮箱或用户名：")
            auth_password = await questionary.password("密码：").ask_async()
            if auth_password is None:
                raise WizardCancelled()
    return RunOptions(base_url=base_url, autonomous=autonomous, verbose=verbose,
                      session_id=session_id, generate_tests=generate_tests, test_mode=test_mode,
                      max_concurrency=max_concurrency, timeout_ms=timeout_ms, retry_count=retry_count,
                      auth_email=auth_email, auth_password=auth_password,
                      auth_app_identifier=auth_app_identifier, use_saved_credentials=use_saved)


async def _generate_and_summarize(agent) -> None:
    """向导中途生成测试并展示摘要（对齐旧 main 的 generate-tests 分支）。"""
    console.print("正在根据当前发现生成测试……")
    try:
        generated = await agent.generate_tests()
    except Exception as error:
        console.print(f"生成测试失败，继续探索……（{error}）")
        return
    if generated:
        summary = {priority: len([test for test in generated if test["priority"] == priority])
                   for priority in ("high", "medium", "low")}
        console.print(f"✅ 已根据当前发现生成 {len(generated)} 个端到端测试"
                      f"（高优先级 {summary['high']}，中优先级 {summary['medium']}，低优先级 {summary['low']}）")
    else:
        console.print("当前发现未能生成测试")


def _make_guidance_menu(agent, options: RunOptions):
    """guided 模式的步间菜单；自主模式返回 None（explore 自动步进，sleep 1s）。"""
    async def get_guidance(result: dict):
        choices = [questionary.Choice("继续探索", value="continue"),
                   questionary.Choice("提供指导或反馈", value="guidance"),
                   questionary.Choice("停止并生成报告", value="stop")]
        if options.generate_tests:
            choices.append(questionary.Choice("立即生成测试（随后继续）", value="generate-tests"))
        answer = await _select("下一步要做什么？", choices)
        if answer == "stop":
            raise StopExploration()
        if answer == "guidance":
            try:
                return await _text("请输入下一步的指导：")
            except WizardCancelled:
                return None
        if answer == "generate-tests":
            await _generate_and_summarize(agent)
            return None
        return None

    return None if options.autonomous else get_guidance


def _show_epilogue(agent, report_path: str, generated: list | None) -> None:
    """终局：报告路径 + 预览 + 发现表格 + 测试摘要（对齐旧 main 收尾）。"""
    console.print(f"[green]报告已保存至：{report_path}[/green]")
    try:
        content = Path(report_path).read_text(encoding="utf-8")
        console.print(Panel(content, title="报告预览"))
    except OSError:
        diagnostics.print("无法读取报告文件以供预览。")
    findings = agent.get_findings()
    if findings:
        findings_table(findings, console)
    if generated:
        console.print("📁 测试文件：./generated-tests/ · 📄 执行报告：./reports/")


async def run_wizard() -> int:
    console.print(Panel("✨ 欢迎使用网站探索测试工具 ✨"))
    options = await _collect_options()
    config = build_config(options)
    agent = ExploratoryAgent(config)
    step_index = 0
    try:
        console.print("正在启动测试代理和浏览器……")
        async for result in explore(agent, _make_guidance_menu(agent, options)):
            step_index += 1
            render_step(step_index, result, 0, console)
            console.print(f"原因：{escape(result.get('reason', ''))}")
        console.print("测试代理已结束探索。正在生成报告……")
        report_path, generated = await finish_session(agent, config, options.generate_tests)
        _show_epilogue(agent, report_path, generated)
    except WizardCancelled:
        # 步间菜单取消：先存已收集的发现（对齐旧 main 的 answer is None 分支）
        try:
            report_path, generated = await finish_session(agent, config, options.generate_tests)
        except Exception as error:
            diagnostics.print(f"[yellow]取消时保存报告失败：{error}[/yellow]")
            diagnostics.print(f"[red]严重错误：{friendly_hint(error)}[/red]")
            return RUN_FAILED
        _show_epilogue(agent, report_path, generated)
    except asyncio.CancelledError:
        console.print("⚠️ 用户已取消，正在保存报告……")
        try:
            report_path, _generated = await finish_session(agent, config, False)
            _show_epilogue(agent, report_path, None)
        except Exception as error:
            diagnostics.print(f"[yellow]取消时保存报告失败：{error}[/yellow]")
        return INTERRUPTED
    except Exception as error:
        diagnostics.print(f"[red]严重错误：{friendly_hint(error)}[/red]")
        return RUN_FAILED
    return OK
