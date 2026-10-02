"""Generates Markdown exploration and test reports."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import hashlib
import shutil

from src.runtime import get_runtime, new_run_id, private_directory, validate_identifier
from urllib.parse import urlparse

from src.types.index import AgentFinding
from src.utils.locale import FINDING_TYPES, SEVERITIES, display_label


async def generate_report(
    findings: list[AgentFinding],
    visited_urls: list[str] | None = None,
    session_id: str | None = None,
    base_url: str | None = None,
    run_summary: dict | None = None,
    artifact_dir: str | None = None,
    run_id: str | None = None,
) -> str:
    session_id = session_id or "anonymous"
    validate_identifier(session_id)
    run_id = run_id or new_run_id()
    validate_identifier(run_id)
    directory = Path(artifact_dir) if artifact_dir else get_runtime().run_dir(session_id, run_id)
    directory = directory.absolute()
    private_directory(directory)
    path = str(directory / "report.md")
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
    if run_summary:
        labels = {"completed": "正常结束", "step_limit": "达到本次步数上限", "failed": "运行失败（部分结果）",
                  "cancelled": "用户中断（部分结果）"}
        reason = run_summary.get("terminationReason", "failed")
        content += (f"运行结果：{labels.get(reason, reason)}\n"
                    f"本次步数：{run_summary.get('steps', 0)}\n"
                    f"失败步数：{run_summary.get('failedSteps', 0)}\n")
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
                source = Path(finding["screenshot"])
                if not source.is_absolute():
                    source = directory / source
                if source.is_file():
                    screenshots = directory / "screenshots"
                    private_directory(screenshots)
                    if source.parent == screenshots:
                        destination = source
                    else:
                        prefix = hashlib.sha256(str(source).encode()).hexdigest()[:12]
                        destination = screenshots / f"{prefix}-{source.name}"
                        shutil.copy2(source, destination)
                    content += f"**截图**：\n![](screenshots/{destination.name})\n"
                else:
                    content += "**截图**：文件不可用\n"
            content += "\n---\n"
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(content, encoding="utf-8")
    return path
