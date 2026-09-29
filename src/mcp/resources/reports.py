"""Port of src/mcp/resources/reports.ts."""

from pathlib import Path


async def handleTestReportResource(uri):
    sessionId = uri.replace("test-report://", "")
    if not sessionId:
        raise ValueError("资源地址中缺少 sessionId")
    reportPath = Path.cwd() / "reports" / f"report-{sessionId}.md"
    try:
        content = reportPath.read_text(encoding="utf-8")
        return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": content}]}
    except Exception:
        try:
            reportsDir = Path.cwd() / "reports"
            latestPath = ""
            latestTime = 0
            for path in reportsDir.glob("*.md"):
                info = path.stat()
                if info.st_mtime * 1000 > latestTime:
                    latestTime = info.st_mtime * 1000
                    latestPath = path
            if latestPath:
                content = latestPath.read_text(encoding="utf-8")
                return {"contents": [{"uri": uri, "mimeType": "text/markdown", "text": content}]}
        except Exception:
            pass
    raise FileNotFoundError(f"未找到会话 {sessionId} 的报告")
