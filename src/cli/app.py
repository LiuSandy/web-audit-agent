"""WebAudit CLI 装配：typer 应用与版本号。"""
import asyncio
import os
from pathlib import Path
from importlib.metadata import PackageNotFoundError, version

import typer

from src.cli.commands.clean import clean_command
from src.cli.commands.config import config_app, paths_command
from src.cli.commands.uninstall import uninstall_command
from src.runtime import resolve_runtime, set_runtime, reset_runtime

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

app = typer.Typer(help="WebAudit —— 网站探索测试代理（无子命令时进入交互向导）")

app.add_typer(config_app, name="config")
app.command("paths")(paths_command)
app.command("uninstall")(uninstall_command)
app.command("clean")(clean_command)

app.command("run")(run_command)
app.command("report")(report_command)
app.command("test")(test_command)
app.command("mcp")(mcp_command)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    home: Path | None = typer.Option(None, "--home", help="配置和数据根目录（默认 ~/.config/webaudit）"),
    data_dir: Path | None = typer.Option(None, "--data-dir", help="只改变数据库与运行产物目录"),
    config_file: Path | None = typer.Option(None, "--config", help="显式配置文件"),
    env_file: Path | None = typer.Option(None, "--env-file", help="显式加载 .env，已有环境变量优先"),
    provider: str | None = typer.Option(None, "--provider", help="覆盖模型服务商"),
    model: str | None = typer.Option(None, "--model", help="覆盖模型名称"),
    api_url: str | None = typer.Option(None, "--api-url", help="覆盖模型接口地址"),
    version_flag: bool = typer.Option(False, "--version", help="显示版本号"),
):
    if version_flag:
        typer.echo(f"WebAudit {__version__}")
        raise typer.Exit(OK)
    if env_file:
        from dotenv import dotenv_values
        if not env_file.is_file():
            raise typer.BadParameter(f"环境变量文件不存在：{env_file}")
        added = []
        for key, value in dotenv_values(env_file).items():
            if value is not None and key not in os.environ:
                os.environ[key] = value
                added.append(key)
        ctx.call_on_close(lambda: [os.environ.pop(key, None) for key in added])
    try:
        runtime = resolve_runtime(home, data_dir, config_file,
                                  {"provider": provider, "model": model, "base_url": api_url})
    except (ValueError, OSError) as error:
        if ctx.invoked_subcommand == "uninstall":
            runtime = resolve_runtime(home, data_dir, config_file, ignore_config=True)
        else:
            raise typer.BadParameter(str(error))
    token = set_runtime(runtime)
    ctx.call_on_close(lambda: reset_runtime(token))
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
