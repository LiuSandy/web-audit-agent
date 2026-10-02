"""Explicit cleanup of owned files, with preview and matching database updates."""
from datetime import datetime, timezone
from pathlib import Path
import shutil

import typer

from src.cli.core.errors import command_errors
from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository
from src.runtime import get_runtime, validate_identifier
from src.runtime.secrets import delete_keyring_keys


def remove_owned(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


@command_errors
def clean_command(
    cache: bool = typer.Option(False, "--cache"),
    logs: bool = typer.Option(False, "--logs"),
    runs: bool = typer.Option(False, "--runs", help="删除运行产物及相应索引"),
    credentials: bool = typer.Option(False, "--credentials", help="删除 API key、网站凭据与浏览器认证会话"),
    session_id: str | None = typer.Option(None, "--session-id"),
    before: str | None = typer.Option(None, "--before", help="只清理该 UTC 日期之前的运行，YYYY-MM-DD"),
    dry_run: bool = typer.Option(False, "--dry-run", help="仅显示范围"),
    yes: bool = typer.Option(False, "--yes", help="确认执行删除"),
):
    runtime = get_runtime()
    if not any((cache, logs, runs, credentials)):
        raise typer.BadParameter("请选择 --cache / --logs / --runs / --credentials")
    if (session_id or before) and not runs:
        raise typer.BadParameter("--session-id / --before 需要搭配 --runs")
    if session_id:
        validate_identifier(session_id)
    cutoff = datetime.strptime(before, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() if before else None
    targets = []
    if cache:
        targets.append(runtime.home / "cache")
    if logs:
        targets.append(runtime.home / "logs")
    if credentials:
        targets.append(runtime.credentials)
    if runs and runtime.runs.exists():
        if runtime.runs.is_symlink():
            raise typer.BadParameter("运行产物根目录不能是符号链接，请先检查路径")
        for session in runtime.runs.iterdir():
            if session_id and session.name != session_id:
                continue
            if session.is_symlink():
                if cutoff is None or session.lstat().st_mtime < cutoff:
                    targets.append(session)
                continue
            if not session.is_dir():
                continue
            for run in session.iterdir():
                if cutoff is None or run.lstat().st_mtime < cutoff:
                    targets.append(run)
    for target in targets:
        typer.echo(str(target))
    if not targets and not credentials:
        typer.echo("没有需要清理的内容。")
        return
    if dry_run:
        return
    if not yes:
        typer.confirm("删除上述内容？", abort=True, default=False)
    if credentials and ((runtime.credentials / "keyring.json").exists() or runtime.settings["llm"].get("secret_storage") == "keyring"):
        delete_keyring_keys(runtime)
    for target in targets:
        remove_owned(target)
    if runtime.database.exists() and (runs or credentials):
        db = AppDatabase.get_instance().get_database()
        if credentials:
            db.execute("DELETE FROM credentials")
            db.execute("DELETE FROM browser_sessions")
        if runs:
            repository = SessionRepository(db)
            for run in repository.list_runs():
                if not Path(run["artifact_dir"]).exists():
                    db.execute("DELETE FROM agent_runs WHERE id=?", (run["id"],))
            for identifier in repository.list_sessions():
                state = repository.load_state(identifier)
                artifact = state.get("artifactDir")
                if artifact and not Path(artifact).exists():
                    # Keep exploration state resumable, but discard references to deleted media.
                    for finding in state.get("findings", []):
                        if finding.get("screenshot") and not Path(finding["screenshot"]).exists():
                            finding.pop("screenshot")
                    state.pop("artifactDir", None)
                    state.pop("runId", None)
                    state["lastRun"] = {**state.get("lastRun", {}), "reportPath": None}
                    repository.save_state(identifier, state)
    typer.echo("清理完成。")
