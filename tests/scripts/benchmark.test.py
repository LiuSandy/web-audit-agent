"""跑批脚本 scripts/benchmark.py 的单元测试（ROADMAP #5）。纯逻辑测试，不发起任何 LLM 调用。"""
import csv
import json
import sys
from dataclasses import dataclass

import pytest

from scripts.benchmark import (
    aggregate,
    build_command,
    is_false_positive,
    main,
    parse_cli_output,
    render_summary,
    run_once,
    sum_token_usage,
    write_annotations,
)


def payload(status="success", steps=10, findings=None, termination="step_limit", **extra):
    base = {"sessionId": f"s-{status}-{steps}", "runId": f"r-{steps}", "status": status,
            "terminationReason": termination, "steps": steps, "sessionSteps": steps,
            "failedSteps": 1, "durationMs": 60_000, "reportPath": "reports/demo.md",
            "findingsCount": len(findings or []), "findings": findings or [], "errors": []}
    base.update(extra)
    return base


def finding(url="http://localhost:3000/bench/index.html", type_="network_error",
            severity="medium", description="网络请求异常：404 GET /x"):
    return {"type": type_, "description": description, "url": url, "severity": severity}


@dataclass
class FakeRun:
    id: str
    parent_run_id: str | None
    run_type: str
    metadata: dict | None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None


class TestParseCliOutput:
    def test_extracts_json_from_noisy_stdout(self):
        stdout = "进度行一\n进度行二\n" + json.dumps(payload(), ensure_ascii=False) + "\n尾部噪声"
        assert parse_cli_output(stdout)["status"] == "success"

    def test_empty_stdout_raises(self):
        with pytest.raises(ValueError):
            parse_cli_output("")


class TestHelpers:
    def test_build_command_pins_autonomous_json(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("OPEN_AI_API_KEY=x\n", encoding="utf-8")
        cmd = build_command("http://x/bench/index.html", 15, env_file=env_file)
        assert cmd[1:3] == ["-m", "src.index"]
        assert cmd[3:5] == ["--env-file", str(env_file)]
        assert cmd[5:7] == ["run", "http://x/bench/index.html"]
        assert "--autonomous" in cmd and "--json" in cmd
        assert cmd[cmd.index("--max-steps") + 1] == "15"

    def test_build_command_skips_missing_env_file(self, tmp_path):
        cmd = build_command("http://x/bench/index.html", 15,
                            env_file=tmp_path / "nope.env")
        assert "--env-file" not in cmd

    def test_build_command_skips_env_file_when_none(self):
        cmd = build_command("http://x/bench/index.html", 15, env_file=None)
        assert "--env-file" not in cmd

    def test_false_positive_only_on_clean_page(self):
        assert is_false_positive(finding(url="http://x/bench/about.html"))
        assert not is_false_positive(finding(url="http://x/bench/index.html"))

    def test_run_once_captures_cli_payload(self):
        inner = json.dumps(payload(steps=7), ensure_ascii=False)
        record = run_once([sys.executable, "-c", f"print({inner!r})"], timeout_s=30, index=3)
        assert record.index == 3
        assert record.returncode == 0
        assert record.payload["steps"] == 7


class TestAggregate:
    def test_counts_statuses_steps_types(self):
        records = [
            _record(0, payload(findings=[finding(type_="network_error"), finding(type_="network_error")])),
            _record(1, payload(status="failed", termination="failed", steps=4, findings=[finding(type_="console_error")])),
            _record(2, payload(status="cancelled", termination="cancelled", steps=2)),
        ]
        agg = aggregate(records)
        assert agg["runs"] == 3
        assert agg["statusDist"] == {"success": 1, "failed": 1, "cancelled": 1}
        assert agg["terminationDist"]["step_limit"] == 1
        assert agg["successRate"] == pytest.approx(1 / 3, abs=1e-3)
        assert agg["stepsMean"] == pytest.approx(5.3, abs=0.01)
        assert agg["findingsPerRunMean"] == pytest.approx(1.0, abs=1e-3)
        assert agg["findingsTypeDist"] == {"network_error": 2, "console_error": 1}
        assert agg["autoFalsePositives"] == 0

    def test_flags_about_html_auto_false_positive(self):
        records = [_record(0, payload(findings=[
            finding(url="http://x/bench/about.html", type_="validation_error"),
            finding(url="http://x/bench/cart.html"),
        ]))]
        agg = aggregate(records)
        assert agg["autoFalsePositives"] == 1


class TestAnnotations:
    def test_rows_and_precategorization(self, tmp_path):
        records = [_record(0, payload(findings=[
            finding(url="http://x/bench/about.html", description="干净页噪声"),
            finding(url="http://x/bench/cart.html", description="真发现"),
        ]))]
        target = tmp_path / "annotations.csv"
        write_annotations(records, target)
        rows = list(csv.DictReader(target.open(encoding="utf-8")))
        assert len(rows) == 2
        assert rows[0]["category"] == "false_positive"
        assert rows[1]["category"] == ""
        assert rows[1]["gtId"] == ""
        assert rows[1]["description"] == "真发现"


class TestTokenUsage:
    def test_sums_only_session_llm_descendants(self):
        runs = [
            FakeRun("step1", None, "chain", {"sessionId": "s1"}),
            FakeRun("tool1", "step1", "tool", None),
            FakeRun("llm1", "tool1", "llm", None, prompt_tokens=100, completion_tokens=20),
            FakeRun("llm2", "tool1", "llm", None, prompt_tokens=50, completion_tokens=10),
            FakeRun("step2", None, "chain", {"sessionId": "s2"}),
            FakeRun("llm3", "step2", "llm", None, prompt_tokens=999, completion_tokens=999),
        ]
        usage = sum_token_usage(runs, "s1")
        assert usage == {"prompt": 150, "completion": 30, "total": 180, "llmCalls": 2}

    def test_returns_none_without_llm_runs(self):
        runs = [FakeRun("step1", None, "chain", {"sessionId": "s1"})]
        assert sum_token_usage(runs, "s1") is None


class TestRenderSummary:
    def test_contains_core_numbers(self):
        records = [_record(0, payload(findings=[finding()]), token_usage={"prompt": 900, "completion": 100, "total": 1000, "llmCalls": 5})]
        text = render_summary(aggregate(records), records)
        assert "平均步数" in text
        assert "成功率" in text
        assert "误报" in text
        assert "1000" in text


class TestMain:
    def test_end_to_end_with_fake_runner(self, tmp_path, monkeypatch):
        monkeypatch.setenv("LANGSMITH_TRACING", "false")
        fake_payloads = [payload(steps=8, findings=[finding()]), payload(status="failed", termination="failed", steps=3)]
        calls = []

        def fake_runner(command, timeout_s, index):
            calls.append(command)
            return _record(index, fake_payloads[index])

        out_dir = tmp_path / "bench-out"
        agg = main(["--runs", "2", "--url", "http://x/bench/index.html",
                    "--out-dir", str(out_dir)], runner=fake_runner)
        assert len(calls) == 2
        assert agg["runs"] == 2
        assert agg["statusDist"] == {"success": 1, "failed": 1}
        assert (out_dir / "runs.json").exists()
        assert (out_dir / "summary.json").exists()
        assert (out_dir / "annotations.csv").exists()
        saved = json.loads((out_dir / "summary.json").read_text(encoding="utf-8"))
        assert saved["aggregate"]["stepsMean"] == pytest.approx(5.5, abs=1e-3)


def _record(index, payload_dict, token_usage=None):
    from scripts.benchmark import RunRecord
    return RunRecord(index=index, payload=payload_dict, returncode=0,
                     started_at="2026-10-14T00:00:00+00:00", ended_at="2026-10-14T00:01:00+00:00",
                     token_usage=token_usage)


def test_subprocess_timeout_captured_as_failed_record():
    record = run_once([sys.executable, "-c", "import time; time.sleep(10)"], timeout_s=1, index=0)
    assert record.returncode == -1
    assert record.payload["terminationReason"] == "benchmark_timeout"
    assert record.payload["status"] == "failed"
