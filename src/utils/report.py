"""Generates Markdown exploration and test reports."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from src.types.index import AgentFinding
from src.utils.locale import FINDING_TYPES, SEVERITIES, display_label


async def generate_report(
    findings: list[AgentFinding],
    visited_urls: list[str] | None = None,
    session_id: str | None = None,
    base_url: str | None = None,
) -> str:
    timestamp = datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    timestamp = timestamp.replace(":", "-").replace(".", "-")
    filename = f"report-{session_id}.md" if session_id else f"report-{timestamp}.md"
    path = f"reports/{filename}"
    target = base_url or "未知"
    if not base_url and visited_urls:
        first_url = visited_urls[0]
        try:
            target = urlparse(first_url).netloc or first_url
        except Exception:  # noqa: BLE001 - source falls back to original URL
            target = first_url

    content = (
        f"# 探索性测试报告\n"
        f"日期：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"  # noqa: DTZ005 - local time
        f"测试目标：{target}\n\n"
        f"## 摘要\n发现问题：{len(findings)}\n"
        f"已探索页面：{len(visited_urls) if visited_urls else 0}\n"
    )
    if visited_urls:
        content += "\n## 已访问页面\n"
        for url in visited_urls:
            content += f"- {url}\n"
    content += "\n## 问题详情\n\n"
    if not findings:
        content += "未记录到问题。\n"
    else:
        for index, finding in enumerate(findings, 1):
            content += (
                f"### {index}. [{display_label(finding['type'], FINDING_TYPES)}] [{display_label(finding['severity'], SEVERITIES)}]\n"
                f"**页面地址**：{finding['url']}\n"
                f"**问题描述**：{finding['description']}\n"
            )
            occurrences = finding.get("occurrences", [])
            if occurrences:
                content += f"**其他出现页面**：另有 {len(occurrences)} 个页面\n"
                for occurrence in occurrences[:5]:
                    content += f"- {occurrence}\n"
                if len(occurrences) > 5:
                    content += f"- ……以及其他 {len(occurrences) - 5} 个页面\n"
            if finding.get("selector"):
                content += f"**元素选择器**：`{finding['selector']}`\n"
            if finding.get("screenshot"):
                content += f"**截图**：\n![]({finding['screenshot']})\n"
            content += "\n---\n"
    try:
        Path(path).write_text(content, encoding="utf-8")
        return path
    except Exception as error:  # noqa: BLE001 - source logs and returns empty path
        print("写入报告失败：", error)
        return ""
