"""scripts/benchmark.py — ROADMAP #5 量化实验跑批脚本。

固定配置循环跑 N 次探索（同 URL、同 maxSteps、独立会话），逐次调用 CLI 的
``python -m src.index run <url> --autonomous --json`` 并解析其 JSON 输出，
汇总发现数、类型分布、步数、成败与 token 用量（token 取自 LangSmith，
未接入时该项留空，不影响检出与稳定性维度）。

产物写入 reports/benchmark/<批次目录>/：runs.json（逐次原始数据）、
summary.json（汇总指标）、annotations.csv（人工标注骨架，按 ground truth
口径把干净对照页上的 finding 预标为误报）。

用法：``uv run python -m scripts.benchmark --runs 10``
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_URL = "http://localhost:3000/bench/index.html"
DEFAULT_MAX_STEPS = 15
DEFAULT_TIMEOUT_S = 1200
CLEAN_PAGE_MARKER = "/bench/about.html"


@dataclass
class RunRecord:
    """一次探索运行的原始记录。payload 为 CLI --json 输出（启动失败时为降级字典）。"""

    index: int
    payload: dict
    returncode: int
    started_at: str
    ended_at: str
    token_usage: dict | None = None


def build_command(url: str, max_steps: int,
                  env_file: Path | None = REPO_ROOT / ".env") -> list[str]:
    """构造 CLI 命令。#3 配置改造后 CLI 不再自动读取仓库 .env，需显式传 --env-file
    （子进程由此获得 LLM key 与 LANGSMITH_* 追踪变量；已有环境变量优先）。"""
    command = [sys.executable, "-m", "src.index"]
    if env_file and env_file.is_file():
        command += ["--env-file", str(env_file)]
    return command + ["run", url, "--autonomous", "--max-steps", str(max_steps), "--json"]


def parse_cli_output(stdout: str) -> dict:
    """从 CLI stdout 提取最终 JSON（契约：stdout 仅输出一个 JSON 对象；容忍进度噪声）。"""
    for line in reversed(stdout.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    raise ValueError("CLI stdout 中未找到 JSON 输出")


def _degraded_payload(reason: str, errors: list[str]) -> dict:
    return {"status": "failed", "terminationReason": reason, "steps": 0, "sessionSteps": 0,
            "failedSteps": 0, "durationMs": 0, "findingsCount": 0, "findings": [],
            "errors": errors}


def run_once(command: list[str], timeout_s: int, index: int) -> RunRecord:
    started = datetime.now(timezone.utc)
    try:
        proc = subprocess.run(command, cwd=REPO_ROOT, capture_output=True, text=True,
                              timeout=timeout_s)
    except subprocess.TimeoutExpired:
        ended = datetime.now(timezone.utc)
        return RunRecord(index=index, returncode=-1, started_at=started.isoformat(),
                         ended_at=ended.isoformat(),
                         payload=_degraded_payload(
                             "benchmark_timeout", [f"单次运行超过 {timeout_s}s 上限，已终止"]))
    ended = datetime.now(timezone.utc)
    try:
        payload = parse_cli_output(proc.stdout)
    except ValueError:
        payload = _degraded_payload("no_json_output", [proc.stderr[-2000:] or "无 stderr"])
    return RunRecord(index=index, payload=payload, returncode=proc.returncode,
                     started_at=started.isoformat(), ended_at=ended.isoformat())


def is_false_positive(finding: dict) -> bool:
    """干净对照页 about.html 上的全部 finding 一律计误报（ground truth 口径，无例外）。"""
    return CLEAN_PAGE_MARKER in str(finding.get("url", ""))


def aggregate(records: list[RunRecord]) -> dict:
    payloads = [r.payload for r in records]
    statuses = Counter(p.get("status", "unknown") for p in payloads)
    terminations = Counter(p.get("terminationReason", "unknown") for p in payloads)
    steps = [p.get("steps", 0) for p in payloads]
    durations = [p.get("durationMs", 0) for p in payloads]
    findings_per_run = [p.get("findingsCount", len(p.get("findings", []))) for p in payloads]
    type_counter = Counter(f.get("type", "unknown")
                           for p in payloads for f in p.get("findings", []))
    token_totals = [r.token_usage["total"] for r in records if r.token_usage]
    token_prompts = [r.token_usage["prompt"] for r in records if r.token_usage]
    token_completions = [r.token_usage["completion"] for r in records if r.token_usage]
    total = len(records)
    return {
        "runs": total,
        "statusDist": dict(statuses),
        "terminationDist": dict(terminations),
        "successRate": round(statuses.get("success", 0) / total, 3) if total else 0.0,
        "stepsMean": round(statistics.fmean(steps), 1) if steps else 0.0,
        "stepsStdev": round(statistics.stdev(steps), 1) if len(steps) > 1 else 0.0,
        "durationMsMean": round(statistics.fmean(durations)) if durations else 0,
        "findingsPerRunMean": round(statistics.fmean(findings_per_run), 1) if findings_per_run else 0.0,
        "findingsTypeDist": dict(type_counter),
        "autoFalsePositives": sum(1 for p in payloads for f in p.get("findings", [])
                                  if is_false_positive(f)),
        "tokenTotalMean": round(statistics.fmean(token_totals)) if token_totals else None,
        "tokenPromptMean": round(statistics.fmean(token_prompts)) if token_prompts else None,
        "tokenCompletionMean": round(statistics.fmean(token_completions)) if token_completions else None,
    }


def write_annotations(records: list[RunRecord], path: Path) -> None:
    """人工标注骨架：每行一条 finding，gtId/category 留空待填（干净页行预标误报）。"""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["run", "findingIndex", "url", "type", "severity",
                         "description", "gtId", "category"])
        for record in records:
            for i, finding in enumerate(record.payload.get("findings", [])):
                description = " ".join(str(finding.get("description", "")).split())[:200]
                pre = "false_positive" if is_false_positive(finding) else ""
                writer.writerow([record.index, i, finding.get("url", ""),
                                 finding.get("type", ""), finding.get("severity", ""),
                                 description, "", pre])


def sum_token_usage(runs, session_id: str) -> dict | None:
    """对一次会话的 LangSmith runs 求根到叶闭包内的 LLM token 总量（纯函数，可测）。

    agent.step 带 metadata.sessionId；其下两层（execute_action /
    automatic_bug_scanning / LLM 调用）按 parent_run_id 逐层收编。
    """
    ids = {r.id for r in runs if (r.metadata or {}).get("sessionId") == session_id}
    for _ in range(2):
        ids |= {r.id for r in runs if r.parent_run_id in ids and r.id not in ids}
    touched = [r for r in runs if r.id in ids and r.run_type == "llm"]
    if not touched:
        return None
    prompt = sum(r.prompt_tokens or 0 for r in touched)
    completion = sum(r.completion_tokens or 0 for r in touched)
    return {"prompt": prompt, "completion": completion,
            "total": prompt + completion, "llmCalls": len(touched)}


def _langsmith_client():
    """LangSmith 就绪时返回 Client，否则 None（未接入时 token 维度留空）。"""
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        from dotenv import load_dotenv
        load_dotenv(env_file)
    if os.getenv("LANGSMITH_TRACING", "").strip().lower() != "true":
        return None
    if not os.getenv("LANGSMITH_API_KEY"):
        return None
    try:
        from langsmith import Client
    except ImportError:
        return None
    return Client()


def _fill_token_usage(records: list[RunRecord], client, project: str) -> None:
    for record in records:
        if record.payload.get("status") == "failed" and record.returncode != 0:
            continue
        session_id = record.payload.get("sessionId", "")
        if not session_id:
            continue
        window_start = datetime.fromisoformat(record.started_at)
        window_end = datetime.fromisoformat(record.ended_at)
        try:
            runs = list(client.list_runs(project_name=project,
                                         start_time=window_start, end_time=window_end))
            record.token_usage = sum_token_usage(runs, session_id)
        except Exception:
            record.token_usage = None


def render_summary(agg: dict, records: list[RunRecord]) -> str:
    from rich.console import Console
    from rich.table import Table

    buffer = Console(width=100, record=True)
    table = Table(title="基准跑批汇总", show_lines=False)
    for column in ("#", "状态", "终止原因", "步数", "发现数", "干净页预标误报"):
        table.add_column(column)
    for record in records:
        payload = record.payload
        flagged = sum(1 for f in payload.get("findings", []) if is_false_positive(f))
        table.add_row(str(record.index), str(payload.get("status")),
                      str(payload.get("terminationReason")), str(payload.get("steps", 0)),
                      str(payload.get("findingsCount", 0)), str(flagged))
    buffer.print(table)
    token_line = (f"单次 token 均值：总量 {agg['tokenTotalMean']}（prompt "
                  f"{agg['tokenPromptMean']} / completion {agg['tokenCompletionMean']}）"
                  if agg["tokenTotalMean"] is not None
                  else "单次 token 均值：未接入（LANGSMITH_TRACING/API_KEY 未配置或查询失败），"
                       "token 数字留空，出处见 LangSmith 面板")
    buffer.print(f"成功率：{agg['successRate']}（终止原因 {agg['terminationDist']}）")
    buffer.print(f"平均步数：{agg['stepsMean']}（标准差 {agg['stepsStdev']}）· "
                 f"平均时长：{agg['durationMsMean']}ms · 平均发现数：{agg['findingsPerRunMean']}")
    buffer.print(f"发现类型分布：{agg['findingsTypeDist']}")
    buffer.print(f"干净页 about.html 预标误报：{agg['autoFalsePositives']} 条")
    buffer.print(token_line)
    buffer.print("检出率/误报率：请在 annotations.csv 逐条标注后按 ground truth 口径计算，"
                 "结果记入 docs/benchmark-results.md（注明样本量 N）")
    return buffer.export_text()


def main(argv: list[str] | None = None, runner=run_once) -> dict:
    parser = argparse.ArgumentParser(description="ROADMAP #5 基准跑批：固定配置循环探索并汇总")
    parser.add_argument("--runs", type=int, default=10, help="运行次数（默认 10）")
    parser.add_argument("--url", default=DEFAULT_URL, help="基准站入口 URL")
    parser.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS,
                        help="每次会话步数预算（默认 15）")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT_S,
                        help="单次运行超时秒数（默认 1200）")
    parser.add_argument("--out-dir", default=None,
                        help="产物目录（默认 reports/benchmark/<UTC 时间戳>）")
    args = parser.parse_args(argv)
    if args.runs < 1:
        parser.error("--runs 至少为 1")

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir) if args.out_dir else REPO_ROOT / "reports" / "benchmark" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)

    command = build_command(args.url, args.max_steps)
    records: list[RunRecord] = []
    for index in range(args.runs):
        print(f"[benchmark] 运行 {index + 1}/{args.runs} …", flush=True)
        records.append(runner(command, args.timeout, index))
        payload = records[-1].payload
        print(f"[benchmark] 状态 {payload.get('status')} · 步数 {payload.get('steps', 0)} · "
              f"发现 {payload.get('findingsCount', 0)} 条", flush=True)

    client = _langsmith_client()
    if client is not None:
        project = os.getenv("LANGSMITH_PROJECT", "web-audit-agent")
        print("[benchmark] 从 LangSmith 取 token 用量 …", flush=True)
        _fill_token_usage(records, client, project)

    agg = aggregate(records)
    (out_dir / "runs.json").write_text(
        json.dumps([asdict(r) for r in records], ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out_dir / "summary.json").write_text(
        json.dumps({"aggregate": agg, "url": args.url, "maxSteps": args.max_steps,
                    "runs": args.runs, "generatedAt": stamp}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    write_annotations(records, out_dir / "annotations.csv")

    print(render_summary(agg, records))
    print(f"产物目录：{out_dir}")
    return agg


if __name__ == "__main__":
    main()
