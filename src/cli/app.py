"""WebAudit CLI 装配：typer 应用与版本号。"""
from importlib.metadata import PackageNotFoundError, version

import typer

from src.cli.commands.report import report_command
from src.cli.commands.run import run_command
from src.cli.core.exits import OK

try:
    __version__ = version("web-audit-agent")
except PackageNotFoundError:
    __version__ = "0.1.0"

app = typer.Typer(help="WebAudit —— 网站探索测试代理")

app.command("run")(run_command)
app.command("report")(report_command)


@app.callback(invoke_without_command=True)
def main_callback(
    ctx: typer.Context,
    version_flag: bool = typer.Option(False, "--version", help="显示版本号"),
):
    if version_flag:
        typer.echo(f"WebAudit {__version__}")
        raise typer.Exit(OK)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


def main():
    app()


if __name__ == "__main__":
    main()
