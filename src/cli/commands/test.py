"""test [path]：执行生成的 Playwright 测试（替代 src/cli/run_tests.py）。"""
import subprocess
import sys
from pathlib import Path

import typer

from src.cli.core.exits import RUN_FAILED


def test_command(
    path: Path = typer.Argument(Path("./generated-tests"), help="生成的测试目录"),
):
    if not path.exists():
        typer.secho("未找到生成的测试", err=True)
        typer.secho("请先运行探索：uv run python -m src.index run <url>（或用向导）", err=True)
        raise typer.Exit(RUN_FAILED)
    typer.echo("🚀 正在运行全部生成的测试……")
    exit_code = subprocess.call([sys.executable, "-m", "pytest", "-o", "python_files=*_spec.py", str(path)])
    if exit_code != 0:
        typer.secho(f"❌ 测试失败（退出码：{exit_code}）", err=True)
        raise typer.Exit(exit_code)
    typer.echo("✅ 所有测试均已通过！")
