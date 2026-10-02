"""run <url>：非交互探索入口。"""
import asyncio
from contextlib import aclosing
from pathlib import Path
import json
import time

import typer
from rich.markup import escape

from src.agents.exploratory import ExploratoryAgent, SessionTargetError
from src.cli.core.config import RunOptions, build_config, validate_options
from src.cli.core.console import console, diagnostics, findings_table, friendly_hint, render_step
from src.cli.core.exits import INTERRUPTED, OK, RUN_FAILED, USAGE
from src.cli.core.runner import explore, finish_session
from src.utils.logger import set_verbose
from src.runtime import get_runtime


async def _execute(options: RunOptions) -> int:
    started = time.monotonic()
    config = build_config(options)
    agent = None
    out = diagnostics if options.json_output else console
    exit_code = OK
    reason = "failed"
    errors = []
    report_path = None
    generated = None
    try:
        agent = ExploratoryAgent(config)
        async with aclosing(explore(agent, max_steps=options.max_steps, max_failures=options.max_failures)) as steps:
            async for result in steps:
                render_step(agent.run_summary["steps"], result, options.max_steps, out)
        reason = agent.run_summary["terminationReason"]
    except (asyncio.CancelledError, KeyboardInterrupt):
        reason, exit_code = "cancelled", INTERRUPTED
    except SessionTargetError as error:
        reason, exit_code = "failed", USAGE
        errors.append(str(error))
    except Exception as error:
        reason, exit_code = "failed", RUN_FAILED
        errors.append(friendly_hint(error))
    # Never overwrite a saved session's report after rejecting its target.
    if agent is not None and exit_code != USAGE:
        try:
            report_path, generated = await finish_session(agent, config, options.generate_tests and exit_code == OK)
        except (asyncio.CancelledError, KeyboardInterrupt):
            reason, exit_code = "cancelled", INTERRUPTED
            agent.run_summary["terminationReason"] = reason
            try:
                report_path, generated = await finish_session(agent, config, False)
            except Exception as error:
                errors.append(f"中断时保存报告失败：{error}")
        except Exception as error:
            errors.append(f"报告生成失败：{error}")
            if exit_code != INTERRUPTED:
                reason, exit_code = "failed", RUN_FAILED
        if getattr(agent, "session_ready", False):
            agent.state["lastRun"] = {**agent.run_summary, "terminationReason": reason,
                                      "errors": errors.copy(), "reportPath": report_path}
            try:
                agent.save_state()
                if hasattr(agent, "save_run"):
                    agent.save_run(report_path)
            except Exception as error:
                errors.append(str(error))
                if exit_code != INTERRUPTED:
                    reason, exit_code = "failed", RUN_FAILED
    summary = getattr(agent, "run_summary", {})
    findings = agent.get_findings() if agent is not None else []
    payload = {"sessionId": config["sessionId"], "runId": config["runId"], "artifactDir": config["artifactDir"], "status": "cancelled" if reason == "cancelled" else
               "failed" if exit_code != OK else "success", "terminationReason": reason,
               "reportPath": report_path, "steps": summary.get("steps", 0),
               "sessionSteps": getattr(agent, "state", {}).get("steps", summary.get("steps", 0)),
               "failedSteps": summary.get("failedSteps", 0), "cleanupErrors": summary.get("cleanupErrors", []),
               "durationMs": int((time.monotonic() - started) * 1000),
               "findingsCount": len(findings), "findings": findings, "errors": errors}
    for error in errors:
        diagnostics.print(f"[red]{escape(error)}[/red]")
    if options.json_output:
        print(json.dumps(payload, ensure_ascii=False))
    elif exit_code == OK:
        label = "已达到本次步数上限" if reason == "step_limit" else "探索完成"
        console.print(f"[green]{label}[/green] · 报告：{escape(report_path or '')}")
        if findings:
            findings_table(findings, console)
        if generated:
            console.print(f"已生成 {len(generated)} 个自动化测试（目录：{config['testOutputDir']}）")
    elif report_path:
        out.print(f"已保存部分结果：{escape(report_path)}")
    return exit_code


def run_command(
    base_url: str = typer.Argument(..., help="目标网站起始地址"),
    max_steps: int | None = typer.Option(None, "--max-steps", min=1, help="本次运行的最大探索步数"),
    max_failures: int | None = typer.Option(None, "--max-failures", min=1, help="连续失败步数上限"),
    autonomous: bool = typer.Option(True, "--autonomous/--guided", help="自主/引导模式（非交互下 guided 降级为自主）"),
    session_id: str | None = typer.Option(None, "--session-id", help="恢复指定会话"),
    verbose: bool = typer.Option(False, "--verbose", help="显示诊断层输出"),
    json_output: bool = typer.Option(False, "--json", help="stdout 仅输出最终 JSON，进度走 stderr"),
    auth_email: str | None = typer.Option(None, "--auth-email", help="登录邮箱或用户名"),
    auth_password: str | None = typer.Option(None, "--auth-password", help="登录密码（保存到本地加密凭据库）"),
    auth_app_identifier: str | None = typer.Option(None, "--auth-app-identifier", help="凭据标识"),
    use_saved_credentials: str | None = typer.Option(None, "--use-saved-credentials", help="复用已保存凭据的应用标识"),
    generate_tests: bool = typer.Option(False, "--generate-tests/--no-generate-tests", help="结束时生成自动化测试"),
    test_mode: str = typer.Option("dry-run", "--test-mode", help="dry-run | sequential | parallel"),
    max_concurrency: int = typer.Option(4, "--max-concurrency", help="最大并行测试数"),
    timeout_ms: int = typer.Option(30000, "--timeout", help="单条测试超时（毫秒）"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="导出报告、截图和测试副本"),
    retry_count: int = typer.Option(2, "--retry-count", help="测试失败重试次数"),
):
    settings = get_runtime().settings["run"]
    max_steps = max_steps if max_steps is not None else settings.get("max_steps", 50)
    max_failures = max_failures if max_failures is not None else settings.get("max_failures", 3)
    options = RunOptions(output_dir=str(output_dir) if output_dir else None, base_url=base_url, max_steps=max_steps, max_failures=max_failures, autonomous=autonomous,
                         session_id=session_id, verbose=verbose, json_output=json_output,
                         auth_email=auth_email, auth_password=auth_password,
                         auth_app_identifier=auth_app_identifier,
                         use_saved_credentials=use_saved_credentials, generate_tests=generate_tests,
                         test_mode=test_mode, max_concurrency=max_concurrency,
                         timeout_ms=timeout_ms, retry_count=retry_count)
    usage_error = validate_options(options)
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
