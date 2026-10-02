"""report [session-id]：按历史会话重出报告。"""
import asyncio
from pathlib import Path
import shutil
from urllib.parse import urlparse

import typer

from src.cli.core.exits import OK, RUN_FAILED, USAGE
from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository
from src.utils.report import generate_report
from src.runtime import new_run_id, validate_identifier


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
    run_id: str | None = typer.Option(None, "--run-id", help="查看指定历史运行"),
    output_dir: Path | None = typer.Option(None, "--output-dir", help="导出报告及附件"),
    base_url: str | None = typer.Option(None, "--base-url", help="站点地址（无法从发现推导时必填）"),
):
    try:
        repository = SessionRepository(AppDatabase.get_instance().get_database())
        sessions = repository.list_sessions() if list_sessions else None
        state = repository.load_state(session_id) if session_id and not list_sessions else None
    except Exception as error:
        typer.secho(f"读取会话失败：{error}", err=True)
        raise typer.Exit(RUN_FAILED)
    if list_sessions:
        if not sessions:
            typer.echo("暂无历史会话。")
            raise typer.Exit(OK)
        for identifier in sessions:
            typer.echo(identifier)
        raise typer.Exit(OK)
    if not session_id:
        typer.secho("用法错误：请提供会话 ID，或使用 --list 查看历史会话。", err=True)
        raise typer.Exit(USAGE)
    if state is None:
        typer.secho(f"未找到会话：{session_id}（用 --list 查看历史会话）", err=True)
        raise typer.Exit(USAGE)
    findings = list(state.get("findings") or [])
    resolved_base_url = base_url or state.get("baseUrl") or derive_base_url(findings)
    if not resolved_base_url:
        typer.secho("用法错误：该会话没有可推导的站点地址，请用 --base-url 提供（示例：report <id> --base-url https://example.com）",
                    err=True)
        raise typer.Exit(USAGE)
    visited = list(state.get("visitedUrls") or [])
    try:
        validate_identifier(session_id)
        runs = repository.list_runs()
        selected = next((r for r in runs if r["session_id"] == session_id and r["id"] == run_id), None) if run_id else repository.latest_run(session_id)
        if run_id and not selected:
            typer.secho(f"未找到运行：{run_id}", err=True)
            raise typer.Exit(USAGE)
        if selected and selected.get("report_path") and Path(selected["report_path"]).is_file():
            report_path = selected["report_path"]
        elif run_id:
            raise FileNotFoundError("该历史运行的报告文件已不存在，无法从当前会话还原历史报告")
        else:
            regenerated_run_id = state.get("runId") or new_run_id()
            report_path = asyncio.run(generate_report(findings, visited, session_id, resolved_base_url,
                                                       run_summary=state.get("lastRun"),
                                                       run_id=regenerated_run_id,
                                                       artifact_dir=state.get("artifactDir")))
            repository.save_run(session_id, regenerated_run_id, Path(report_path).parent,
                                report_path, state.get("lastRun") or {})
        if output_dir:
            source = Path(report_path).parent.resolve()
            destination = (output_dir.expanduser().absolute() / session_id / source.name).resolve()
            if destination == source or destination.is_relative_to(source) or source.is_relative_to(destination):
                raise ValueError("导出目录不能与原始产物目录重叠")
            shutil.copytree(source, destination, dirs_exist_ok=True)
        if not report_path:
            raise RuntimeError("报告生成未返回有效路径")
    except typer.Exit:
        raise
    except Exception as error:
        typer.secho(f"报告生成失败：{error}", err=True)
        raise typer.Exit(RUN_FAILED)
    typer.echo(f"报告已保存至：{report_path}")
