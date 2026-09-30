"""report [session-id]：按历史会话重出报告。"""
import asyncio
from urllib.parse import urlparse

import typer

from src.cli.core.exits import OK, RUN_FAILED, USAGE
from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository
from src.utils.report import generate_report


def derive_base_url(findings: list[dict]) -> str | None:
    """从 findings 的 url 推导站点 origin；旧 state 不存 base_url（spec §4）。"""
    for finding in findings:
        url = finding.get("url") or ""
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            return f"{parsed.scheme}://{parsed.netloc}"
    return None


def report_command(
    session_id: str | None = typer.Argument(None, help="会话 ID（--list 时可省略）"),
    list_sessions: bool = typer.Option(False, "--list", help="列出历史会话"),
    base_url: str | None = typer.Option(None, "--base-url", help="站点地址（无法从发现推导时必填）"),
):
    repository = SessionRepository(AppDatabase.get_instance().get_database())
    if list_sessions:
        sessions = repository.list_sessions()
        if not sessions:
            typer.echo("暂无历史会话。")
            raise typer.Exit(OK)
        for identifier in sessions:
            typer.echo(identifier)
        raise typer.Exit(OK)
    if not session_id:
        typer.secho("用法错误：请提供会话 ID，或使用 --list 查看历史会话。", err=True)
        raise typer.Exit(USAGE)
    state = repository.load_state(session_id)
    if state is None:
        typer.secho(f"未找到会话：{session_id}（用 --list 查看历史会话）", err=True)
        raise typer.Exit(USAGE)
    findings = list(state.get("findings") or [])
    resolved_base_url = base_url or derive_base_url(findings)
    if not resolved_base_url:
        typer.secho("用法错误：该会话没有可推导的站点地址，请用 --base-url 提供（示例：report <id> --base-url https://example.com）",
                    err=True)
        raise typer.Exit(USAGE)
    visited = list(state.get("visitedUrls") or [])
    try:
        report_path = asyncio.run(generate_report(findings, visited, session_id, resolved_base_url))
    except Exception as error:
        typer.secho(f"报告生成失败：{error}", err=True)
        raise typer.Exit(RUN_FAILED)
    typer.echo(f"报告已保存至：{report_path}")
