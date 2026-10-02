"""Read the requested session's report from the shared run index."""
from pathlib import Path

from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository
from src.runtime import get_runtime, validate_identifier


async def handle_test_report_resource(uri):
    session_id = uri.removeprefix("test-report://")
    validate_identifier(session_id)
    if not get_runtime().database.exists():
        raise FileNotFoundError(f"未找到会话 {session_id} 的报告")
    repository = SessionRepository(AppDatabase.get_instance().get_database())
    if session_id == "latest":
        runs = repository.list_runs()
        run = runs[0] if runs else None
    else:
        run = repository.latest_run(session_id)
    if not run or not run.get("report_path"):
        raise FileNotFoundError(f"未找到会话 {session_id} 的报告")
    content = Path(run["report_path"]).read_text(encoding="utf-8")
    return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": content}]}
