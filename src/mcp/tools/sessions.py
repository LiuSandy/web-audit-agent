"""MCP tool for listing saved sessions."""

import importlib
from datetime import datetime, timezone

from src.database.database import AppDatabase
from src.mcp.types import to_text_content
from src.repositories.session_repository import SessionRepository
from src.utils.logger import create_logger
from src.utils.locale import STATUSES, display_label

logger = create_logger("mcp:sessions")


def _active_tests():
    return importlib.import_module("src.mcp.server").active_tests


def _iso(value):
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat().replace("+00:00", "Z")
    return None


async def handle_list_sessions(args):
    limit = args.get("limit") if isinstance(args.get("limit"), (int, float)) and args["limit"] > 0 else 10
    status_filter = str(args.get("status") or "all")
    sessions = []
    for sid, execution in list(_active_tests().items()):
        if status_filter == "completed" and execution.get("status") != "completed":
            continue
        if status_filter == "active" and execution.get("status") in ("completed", "failed"):
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
            db = AppDatabase.get_instance()
            repo = SessionRepository(db.get_database())
            stored_ids = repo.list_sessions()[:int(limit)]
            for stored_id in stored_ids:
                if any(s["sessionId"] == stored_id for s in sessions):
                    continue
                state = repo.load_state(stored_id)
                if not state:
                    continue
                looks_active = state["steps"] < 50 and len(state["todoQueue"]) > 0
                stored_status = "active" if looks_active else "completed"
                if status_filter != "all" and status_filter != stored_status:
                    continue
                sessions.append({"sessionId": stored_id, "status": stored_status,
                    "statusText": display_label(stored_status, STATUSES),
                    "findingsCount": len(state["findings"]),
                    "visitedUrlsCount": len(state["visitedUrls"])})
        except Exception as error:
            logger.error(f"读取已保存的会话失败：{error}")
    result = sessions[:int(limit)]
    return {"content": to_text_content({"total": len(result), "sessions": result})}
