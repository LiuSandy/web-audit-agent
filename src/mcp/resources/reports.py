"""MCP resource for reading generated reports."""

from pathlib import Path


async def handle_test_report_resource(uri):
    session_id = uri.replace("test-report://", "")
    if not session_id:
        raise ValueError("资源地址中缺少 sessionId")
    report_path = Path.cwd() / "reports" / f"report-{session_id}.md"
    try:
        content = report_path.read_text(encoding="utf-8")
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": content}]}
    except Exception:
        try:
            reports_dir = Path.cwd() / "reports"
            latest_path = ""
            latest_time = 0
            for path in reports_dir.glob("*.md"):
                info = path.stat()
                if info.st_mtime * 1000 > latest_time:
                    latest_time = info.st_mtime * 1000
                    latest_path = path
            if latest_path:
                content = latest_path.read_text(encoding="utf-8")
                return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": content}]}
        except Exception:
            pass
    raise FileNotFoundError(f"未找到会话 {session_id} 的报告")
