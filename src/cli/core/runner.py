"""Shared exploration lifecycle and run outcome for CLI and wizard."""
import asyncio
from collections.abc import AsyncIterator

from rich.markup import escape

from src.cli.core.console import diagnostics
from src.utils.report import generate_report


class StopExploration(Exception):
    """Guidance callback requests a normal early stop."""


class ExplorationFailed(RuntimeError):
    """Exploration exceeded its consecutive failure budget."""


async def explore(agent, get_guidance=None, pause: float = 1.0,
                  max_steps: int | None = None, max_failures: int = 3) -> AsyncIterator[dict]:
    """Start, run and clean up; max_steps is the budget for this invocation."""
    summary = {"terminationReason": "failed", "steps": 0, "failedSteps": 0,
               "cleanupErrors": []}
    agent.run_summary = summary
    consecutive_failures = 0
    primary_error = None
    try:
        if max_steps is not None and max_steps < 1 or max_failures < 1:
            raise ValueError("步数预算与连续失败阈值必须为正整数")
        await agent.start()
        next_guidance = None
        while True:
            summary["steps"] += 1
            try:
                result = await agent.step(next_guidance)
            except Exception:
                summary["failedSteps"] += 1
                raise
            next_guidance = None
            failed = result.get("success") is False or result.get("action") == "error"
            consecutive_failures = consecutive_failures + 1 if failed else 0
            summary["failedSteps"] += int(failed)
            yield result
            if consecutive_failures >= max_failures:
                raise ExplorationFailed(f"连续 {max_failures} 步失败：{result.get('result') or result.get('reason', '')}")
            if result["completed"] and not failed:
                summary["terminationReason"] = "completed"
                return
            if max_steps is not None and summary["steps"] >= max_steps:
                if failed:
                    raise ExplorationFailed("步数预算耗尽时最后一步仍失败：" + str(result.get("result") or result.get("reason", "")))
                summary["terminationReason"] = "step_limit"
                return
            if get_guidance is None:
                await asyncio.sleep(pause)
                continue
            try:
                next_guidance = await get_guidance(result)
            except StopExploration:
                summary["terminationReason"] = "completed"
                return
    except (asyncio.CancelledError, KeyboardInterrupt):
        summary["terminationReason"] = "cancelled"
        primary_error = True
        raise
    except BaseException:
        primary_error = True
        raise
    finally:
        cleanup_errors = []
        try:
            await agent.stop()
        except Exception as error:
            cleanup_errors.append(str(error))
        summary["cleanupErrors"] = cleanup_errors.copy()
        if cleanup_errors and not primary_error:
            summary["terminationReason"] = "failed"
        if hasattr(agent, "save_state") and getattr(agent, "session_ready", False):
            agent.state["lastRun"] = dict(summary)
            try:
                agent.save_state()
            except Exception as error:
                cleanup_errors.append(str(error))
        summary["cleanupErrors"] = cleanup_errors
        if cleanup_errors:
            for message in cleanup_errors:
                diagnostics.print(f"[yellow]收尾失败：{escape(message)}[/yellow]")
            if not primary_error:
                summary["terminationReason"] = "failed"
                raise RuntimeError("；".join(cleanup_errors))


async def finish_session(agent, config: dict, generate_tests: bool) -> tuple[str, list | None]:
    """Required report errors propagate; optional test generation only warns."""
    report_path = await generate_report(agent.get_findings(), agent.get_visited_urls(),
                                       config["sessionId"], config["baseUrl"],
                                       run_summary=getattr(agent, "run_summary", None))
    if not report_path:
        raise RuntimeError("报告生成未返回有效路径")
    generated = None
    if generate_tests:
        try:
            generated = await agent.generate_tests()
        except Exception as error:
            diagnostics.print(f"[yellow]测试生成失败：{escape(str(error))}[/yellow]")
    return report_path, generated
