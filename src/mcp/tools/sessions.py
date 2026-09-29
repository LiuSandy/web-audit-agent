"""Port of src/mcp/tools/sessions.ts."""

import importlib
import importlib.util
from datetime import datetime, timezone
from pathlib import Path

from src.database.database import AppDatabase
from src.mcp.types import toTextContent
from src.utils.logger import createLogger
from src.utils.locale import STATUSES, display_label

_repo_spec = importlib.util.spec_from_file_location(
    "src.repositories.session_repository", Path(__file__).parents[2] / "repositories" / "session.repository.py")
_repo_module = importlib.util.module_from_spec(_repo_spec)
_repo_spec.loader.exec_module(_repo_module)
SessionRepository = _repo_module.SessionRepository
logger = createLogger("mcp:sessions")


def _activeTests():
    return importlib.import_module("src.mcp.server").activeTests


def _iso(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    return None


async def handleListSessions(args):
    limit = args.get("limit") if isinstance(args.get("limit"), (int, float)) and args["limit"] > 0 else 10
    statusFilter = str(args.get("status") or "all")
    sessions = []
    for sid, execution in list(_activeTests().items()):
        if statusFilter == "completed" and execution.get("status") != "completed":
            continue
        if statusFilter == "active" and execution.get("status") in ("completed", "failed"):
            continue
        entry = {"sessionId": sid, "status": execution.get("status"),
                 "statusText": display_label(execution.get("status"), STATUSES),
                 "findingsCount": execution.get("findingsCount"),
                 "visitedUrlsCount": execution.get("visitedUrlsCount")}
        if _iso(execution.get("startTime")):
            entry["startTime"] = _iso(execution["startTime"])
        if _iso(execution.get("endTime")):
            entry["endTime"] = _iso(execution["endTime"])
        sessions.append(entry)
    if len(sessions) < limit:
        try:
            db = AppDatabase.getInstance()
            repo = SessionRepository(db.getDatabase())
            storedIds = repo.listSessions()[:int(limit)]
            for storedId in storedIds:
                if any(s["sessionId"] == storedId for s in sessions):
                    continue
                state = repo.loadState(storedId)
                if not state:
                    continue
                looksActive = state["steps"] < 50 and len(state["todoQueue"]) > 0
                storedStatus = "active" if looksActive else "completed"
                if statusFilter != "all" and statusFilter != storedStatus:
                    continue
                sessions.append({"sessionId": storedId, "status": storedStatus,
                    "statusText": display_label(storedStatus, STATUSES),
                    "findingsCount": len(state["findings"]),
                    "visitedUrlsCount": len(state["visitedUrls"])})
        except Exception as error:
            logger.error(f"读取已保存的会话失败：{error}")
    result = sessions[:int(limit)]
    return {"content": toTextContent({"total": len(result), "sessions": result})}
