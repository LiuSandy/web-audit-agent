"""run 与向导共用的会话执行循环（spec §5：一个循环驱动两种模式）。"""
import asyncio
from collections.abc import AsyncIterator

from src.cli.core.console import diagnostics
from src.utils.report import generate_report


class StopExploration(Exception):
    """由指导回调抛出，表示用户要求提前结束探索。"""


async def explore(agent, get_guidance=None, pause: float = 1.0) -> AsyncIterator[dict]:
    """驱动 agent 步循环，逐步 yield 结果。

    get_guidance：每步（未完成）后调用的异步回调；返回下一步指导文本或 None 继续循环，
    抛 StopExploration 提前结束。为 None 时按自主模式在步间 sleep(pause)。
    生命周期：进入时 start()，退出（含异常/取消）时在 finally 中 stop()。
    """
    await agent.start()
    try:
        next_guidance = None
        while True:
            result = await agent.step(next_guidance)
            next_guidance = None
            yield result
            if result["completed"]:
                return
            if get_guidance is None:
                await asyncio.sleep(pause)
                continue
            try:
                next_guidance = await get_guidance(result)
            except StopExploration:
                return
    finally:
        try:
            await agent.stop()
        except Exception:
            pass


async def finish_session(agent, config: dict, generate_tests: bool) -> tuple[str, list | None]:
    """收尾：保存报告（失败向上抛，由调用方映射退出码）；可选生成测试（失败仅告警）。"""
    report_path = await generate_report(agent.get_findings(), agent.get_visited_urls(),
                                        config["sessionId"], config["baseUrl"])
    generated = None
    if generate_tests:
        try:
            generated = await agent.generate_tests()
        except Exception as error:
            diagnostics.print(f"[yellow]测试生成失败：{error}[/yellow]")
            generated = None
    return report_path, generated
