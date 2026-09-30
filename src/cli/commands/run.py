"""run <url>：非交互探索入口。"""
import asyncio
import json
import time

import typer
from rich.markup import escape

from src.agents.exploratory import ExploratoryAgent
from src.cli.core.config import RunOptions, build_config, validate_auth
from src.cli.core.console import console, diagnostics, findings_table, friendly_hint, render_step
from src.cli.core.exits import INTERRUPTED, OK, RUN_FAILED, USAGE
from src.cli.core.runner import explore, finish_session
from src.utils.logger import set_verbose


async def _execute(options: RunOptions) -> int:
    started = time.monotonic()
    config = build_config(options)
    agent = ExploratoryAgent(config)
    out = diagnostics if options.json_output else console
    try:
        step_index = 0
        async for result in explore(agent, max_steps=options.max_steps):
            step_index += 1
            render_step(step_index, result, options.max_steps, out)
        report_path, generated = await finish_session(agent, config, options.generate_tests)
    except asyncio.CancelledError:
        try:
            await finish_session(agent, config, False)
        except Exception as error:
            diagnostics.print(f"[yellow]取消时保存报告失败：{error}[/yellow]")
        return INTERRUPTED
    except Exception as error:
        out.print(f"[red]运行失败：{escape(friendly_hint(error))}[/red]")
        return RUN_FAILED
    duration_ms = int((time.monotonic() - started) * 1000)
    findings = agent.get_findings()
    if options.json_output:
        payload = {"sessionId": config["sessionId"], "reportPath": report_path, "steps": step_index,
                   "durationMs": duration_ms, "findingsCount": len(findings), "findings": findings}
        print(json.dumps(payload, ensure_ascii=False))
    else:
        console.print(f"[green]✅ 探索完成[/green] · 报告：{report_path}")
        if findings:
            findings_table(findings, console)
        if generated:
            console.print(f"已生成 {len(generated)} 个自动化测试（目录：./generated-tests/）")
    return OK


def run_command(
    base_url: str = typer.Argument(..., help="目标网站起始地址"),
    max_steps: int = typer.Option(50, "--max-steps", help="最大探索步数"),
    autonomous: bool = typer.Option(True, "--autonomous/--guided", help="自主/引导模式（非交互下 guided 降级为自主）"),
    session_id: str | None = typer.Option(None, "--session-id", help="恢复指定会话"),
    verbose: bool = typer.Option(False, "--verbose", help="显示诊断层输出"),
    json_output: bool = typer.Option(False, "--json", help="stdout 仅输出最终 JSON，进度走 stderr"),
    auth_email: str | None = typer.Option(None, "--auth-email", help="登录邮箱或用户名"),
    auth_password: str | None = typer.Option(None, "--auth-password", help="登录密码（仅本次运行使用）"),
    auth_app_identifier: str | None = typer.Option(None, "--auth-app-identifier", help="凭据标识"),
    use_saved_credentials: str | None = typer.Option(None, "--use-saved-credentials", help="复用已保存凭据的应用标识"),
    generate_tests: bool = typer.Option(False, "--generate-tests/--no-generate-tests", help="结束时生成自动化测试"),
    test_mode: str = typer.Option("dry-run", "--test-mode", help="dry-run | sequential | parallel"),
    max_concurrency: int = typer.Option(4, "--max-concurrency", help="最大并行测试数"),
    timeout_ms: int = typer.Option(30000, "--timeout", help="单条测试超时（毫秒）"),
    retry_count: int = typer.Option(2, "--retry-count", help="测试失败重试次数"),
):
    options = RunOptions(base_url=base_url, max_steps=max_steps, autonomous=autonomous,
                         session_id=session_id, verbose=verbose, json_output=json_output,
                         auth_email=auth_email, auth_password=auth_password,
                         auth_app_identifier=auth_app_identifier,
                         use_saved_credentials=use_saved_credentials, generate_tests=generate_tests,
                         test_mode=test_mode, max_concurrency=max_concurrency,
                         timeout_ms=timeout_ms, retry_count=retry_count)
    usage_error = validate_auth(options)
    if usage_error is None and options.test_mode not in ("dry-run", "sequential", "parallel"):
        usage_error = f"--test-mode 仅支持 dry-run | sequential | parallel，收到：{options.test_mode}"
    if usage_error:
        typer.secho(f"用法错误：{usage_error}", fg=typer.colors.RED, err=True)
        raise typer.Exit(USAGE)
    set_verbose(options.verbose)
    if not options.autonomous:
        diagnostics.print("提示：非交互模式下 --guided 无法逐条问询，将按自主模式执行。")
    exit_code = OK
    try:
        exit_code = asyncio.run(_execute(options))
    except (KeyboardInterrupt, asyncio.CancelledError):
        exit_code = INTERRUPTED
    raise typer.Exit(exit_code)
