"""rich 输出分层（spec §7）：进度层/结果层走 Console 参数，诊断层固定 stderr。"""
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from src.utils.locale import ACTIONS, SEVERITIES, display_label

console = Console()
diagnostics = Console(stderr=True)

SEVERITY_STYLES = {"high": "red", "medium": "yellow", "low": "green"}


def render_step(step_index: int, result: dict, max_steps: int, out: Console) -> None:
    """进度层：每步一行。max_steps<=0 时不显示总数。"""
    stats = result.get("stats") or {}
    total = f"/{max_steps}" if max_steps else ""
    out.print(
        f"[bold cyan]步骤 {step_index}{total}[/bold cyan] "
        f"{display_label(result.get('action', ''), ACTIONS)} · "
        f"当前 {escape(stats.get('currentUrl', '未知'))} · 队列 {stats.get('queueLength', 0)} · "
        f"已访问 {stats.get('visitedCount', 0)} · 发现 {stats.get('findingsCount', 0)}"
    )


def findings_table(findings: list[dict], out: Console) -> None:
    """结果层：终局发现表格，按严重度着色（文案取 locale.SEVERITIES）。"""
    table = Table(title="发现问题")
    table.add_column("类型")
    table.add_column("严重度")
    table.add_column("描述")
    table.add_column("页面")
    for finding in findings:
        severity = finding.get("severity", "")
        table.add_row(escape(finding.get("type", "")), display_label(severity, SEVERITIES),
                      escape(finding.get("description", "")), escape(finding.get("url", "")),
                      style=SEVERITY_STYLES.get(severity, ""))
    out.print(table)


def friendly_hint(error: Exception) -> str:
    """把底层异常翻译成带修复建议的中文提示；无法识别时原样返回。"""
    text = str(error)
    lowered = text.lower()
    if "api key" in lowered or "api_key" in lowered or "unauthenticated" in lowered:
        return f"{text}\n未配置 API key：请在 .env 设置 GOOGLE_AI_STUDIO_API_KEY 或 OPEN_AI_API_KEY（参考 .env.example）"
    if "executable doesn't exist" in lowered or "playwright install" in lowered:
        return f"{text}\n浏览器未安装：运行 uv run python -m playwright install chromium"
    return text
