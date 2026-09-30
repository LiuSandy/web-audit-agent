"""WebAudit CLI 装配：typer 应用与版本号。"""
import asyncio
from importlib.metadata import PackageNotFoundError, version

import typer

from src.cli.commands.mcp import mcp_command
from src.cli.commands.report import report_command
from src.cli.commands.run import run_command
from src.cli.commands.test import test_command
from src.cli.core.console import console
from src.cli.core.exits import INTERRUPTED, OK

try:
    __version__ = version("web-audit-agent")
except PackageNotFoundError:
    __version__ = "0.1.0"

app = typer.Typer(help="WebAudit —— 网站探索测试代理")

app.command("run")(run_command)
app.command("report")(report_command)
app.command("test")(test_command)
app.command("mcp")(mcp_command)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version_flag: bool = typer.Option(False, "--version", help="显示版本号"),
):
    if version_flag:
        typer.echo(f"WebAudit {__version__}")
        raise typer.Exit(OK)
    if ctx.invoked_subcommand is not None:
        return
    from src.cli.wizard import WizardCancelled, run_wizard  # 延迟导入：子命令不拖起 questionary

    try:
        raise typer.Exit(asyncio.run(run_wizard()))
    except WizardCancelled:
        console.print("操作已取消。")
        raise typer.Exit(OK)
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise typer.Exit(INTERRUPTED)


def main():
    app()


if __name__ == "__main__":
    main()
