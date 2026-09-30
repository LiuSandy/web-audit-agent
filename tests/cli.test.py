"""WebAudit CLI 层的测试（ROADMAP #3）。"""
import asyncio
import io
import json as json_module

import pytest
from rich.console import Console
from typer.testing import CliRunner

from src.cli.app import app
from src.cli.core.config import RunOptions, build_config, new_session_id, validate_auth
from src.cli.core.console import findings_table, friendly_hint, render_step
from src.cli.core.runner import StopExploration, explore, finish_session
from tests.fakes import FakeAgent, STEP_A, STEP_B

runner = CliRunner()


def test_version_outputs_project_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_build_config_camel_case_contract():
    config = build_config(RunOptions(base_url="https://example.com"))
    assert config["baseUrl"] == "https://example.com"
    assert config["maxSteps"] == 50
    assert config["auth"] is None
    assert config["enableTestGeneration"] is False
    assert config["testOutputDir"] == "./generated-tests"
    assert config["includeE2ETests"] is True
    assert config["testDryRun"] is True and config["testParallelExecution"] is False
    assert config["testMaxConcurrency"] == 4
    assert config["testTimeout"] == 30000
    assert config["testRetryCount"] == 2


def test_build_config_passes_session_id_through():
    config = build_config(RunOptions(base_url="u", session_id="session-abc"))
    assert config["sessionId"] == "session-abc"


def test_build_config_generates_session_id_when_absent():
    config = build_config(RunOptions(base_url="u"))
    assert config["sessionId"].startswith("session-")
    assert new_session_id().startswith("session-")


def test_build_auth_password_only_gets_default_app_identifier():
    config = build_config(RunOptions(base_url="u", auth_password="pw"))
    assert config["auth"] == {"required": True, "appIdentifier": "default-app",
                              "credentials": {"email": "", "password": "pw"}}


def test_build_auth_saved_credentials():
    config = build_config(RunOptions(base_url="u", use_saved_credentials="local-app"))
    assert config["auth"] == {"required": True, "appIdentifier": "local-app"}


def test_validate_auth_rejects_email_without_password():
    assert validate_auth(RunOptions(base_url="u", auth_email="a@b.c")) is not None


def test_validate_auth_rejects_saved_with_password_flags():
    options = RunOptions(base_url="u", use_saved_credentials="app", auth_password="pw")
    assert validate_auth(options) is not None


def test_validate_auth_rejects_identifier_without_credentials():
    assert validate_auth(RunOptions(base_url="u", auth_app_identifier="app")) is not None


def test_validate_auth_accepts_password_only():
    assert validate_auth(RunOptions(base_url="u", auth_password="pw")) is None


def _capture_console() -> Console:
    return Console(file=io.StringIO(), width=120, force_terminal=False, highlight=False)


def test_render_step_contains_progress_fields():
    out = _capture_console()
    result = {"action": "navigate", "reason": "r",
              "stats": {"currentUrl": "https://x/1", "queueLength": 2, "visitedCount": 1, "findingsCount": 0}}
    render_step(1, result, 50, out)
    text = out.file.getvalue()
    assert "步骤 1/50" in text and "https://x/1" in text and "发现 0" in text


def test_findings_table_shows_severity_label():
    out = _capture_console()
    finding = {"type": "console_error", "severity": "medium", "url": "https://x", "description": "控制台错误：示例"}
    findings_table([finding], out)
    text = out.file.getvalue()
    assert "中" in text and "控制台错误：示例" in text


def test_friendly_hint_suggests_api_key_setup():
    message = friendly_hint(RuntimeError("No API key provided"))
    assert "GOOGLE_AI_STUDIO_API_KEY" in message and ".env" in message


def test_friendly_hint_suggests_playwright_install():
    message = friendly_hint(RuntimeError("Executable doesn't exist at .../chromium"))
    assert "playwright install" in message


def test_friendly_hint_passes_through_unknown_errors():
    assert friendly_hint(RuntimeError("boom")) == "boom"


@pytest.mark.asyncio
async def test_explore_yields_steps_until_completed_and_stops_agent():
    agent = FakeAgent(steps=[STEP_A, STEP_B])
    results = [result async for result in explore(agent, pause=0)]
    assert [result["reason"] for result in results] == ["第一步原因", "最后一步原因"]
    assert agent.started and agent.stopped


@pytest.mark.asyncio
async def test_explore_guidance_callback_receives_result_and_injects_text():
    agent = FakeAgent(steps=[STEP_A, STEP_B])
    seen = []

    async def guidance(result):
        seen.append(result["reason"])
        return "聚焦登录页" if len(seen) == 1 else None

    results = [result async for result in explore(agent, guidance, pause=0)]
    assert seen == ["第一步原因"]
    assert agent.step_calls[1] == "聚焦登录页"
    assert len(results) == 2


@pytest.mark.asyncio
async def test_explore_stop_exploration_ends_loop_and_stops_agent():
    agent = FakeAgent(steps=[STEP_A, STEP_A, STEP_B])

    async def guidance(result):
        raise StopExploration()

    results = [result async for result in explore(agent, guidance, pause=0)]
    assert len(results) == 1 and agent.stopped


@pytest.mark.asyncio
async def test_explore_stops_agent_when_cancelled():
    agent = FakeAgent(steps=[STEP_A], cancelled_during=1)
    with pytest.raises(asyncio.CancelledError):
        [result async for result in explore(agent, pause=0)]
    assert agent.stopped


@pytest.mark.asyncio
async def test_finish_session_returns_report_and_generated_tests(monkeypatch):
    async def fake_report(findings, visited, session_id, base_url):
        return "reports/fake.md"

    monkeypatch.setattr("src.cli.core.runner.generate_report", fake_report)
    agent = FakeAgent()
    report_path, generated = await finish_session(agent, {"sessionId": "s1", "baseUrl": "https://x"}, True)
    assert report_path == "reports/fake.md"
    assert generated == agent.generated


@pytest.mark.asyncio
async def test_finish_session_swallows_test_generation_failure(monkeypatch):
    async def fake_report(findings, visited, session_id, base_url):
        return "reports/fake.md"

    monkeypatch.setattr("src.cli.core.runner.generate_report", fake_report)
    agent = FakeAgent()

    async def failing_generate_tests():
        raise RuntimeError("boom")

    agent.generate_tests = failing_generate_tests
    report_path, generated = await finish_session(agent, {"sessionId": "s", "baseUrl": "b"}, True)
    assert report_path == "reports/fake.md" and generated is None


@pytest.fixture
def fake_run_env(monkeypatch):
    """替换 run 命令的 agent 与报告生成，返回 (agent, report_calls)。"""
    import src.cli.commands.run as run_module
    from src.cli.core import runner as runner_module

    agent = FakeAgent(steps=[STEP_A, STEP_B])
    report_calls = []

    async def fake_report(findings, visited, session_id, base_url):
        report_calls.append({"sessionId": session_id, "baseUrl": base_url})
        return "reports/fake.md"

    monkeypatch.setattr(run_module, "ExploratoryAgent", lambda config: agent)
    monkeypatch.setattr(runner_module, "generate_report", fake_report)
    return agent, report_calls


def test_run_success_exit_zero(fake_run_env):
    agent, _ = fake_run_env
    result = runner.invoke(app, ["run", "https://example.com"])
    assert result.exit_code == 0
    assert agent.started and agent.stopped


def test_run_json_stdout_pure(fake_run_env):
    agent, _ = fake_run_env
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    assert result.exit_code == 0
    payload = json_module.loads(result.stdout)
    assert payload["sessionId"].startswith("session-")
    assert payload["reportPath"] == "reports/fake.md"
    assert payload["steps"] == 2
    assert payload["findingsCount"] == len(agent.findings)
    assert "步骤" not in result.stdout


def test_run_agent_failure_exit_one(monkeypatch):
    import src.cli.commands.run as run_module

    agent = FakeAgent(error=RuntimeError("浏览器启动失败"))
    monkeypatch.setattr(run_module, "ExploratoryAgent", lambda config: agent)
    result = runner.invoke(app, ["run", "https://example.com"])
    assert result.exit_code == 1


def test_run_cancelled_saves_report_and_exits_130(fake_run_env):
    agent, report_calls = fake_run_env
    agent.cancelled_during = 1
    result = runner.invoke(app, ["run", "https://example.com"])
    assert result.exit_code == 130
    assert len(report_calls) == 1
    assert agent.stopped


def test_run_rejects_incomplete_auth(fake_run_env):
    result = runner.invoke(app, ["run", "https://example.com", "--auth-email", "a@b.c"])
    assert result.exit_code == 2


def test_run_rejects_unknown_test_mode(fake_run_env):
    result = runner.invoke(app, ["run", "https://example.com", "--test-mode", "bogus"])
    assert result.exit_code == 2


@pytest.fixture
def fake_repo(monkeypatch):
    import src.cli.commands.report as report_module

    class FakeRepo:
        def __init__(self, db):
            self.db = db

        def list_sessions(self):
            return ["session-1", "session-2"]

        def load_state(self, session_id):
            if session_id == "session-1":
                return {"findings": [{"type": "console_error", "severity": "medium",
                                      "url": "https://example.com/a", "description": "d"}],
                        "visitedUrls": {"https://example.com/"}, "steps": 3}
            return {"findings": [], "visitedUrls": [], "steps": 1}

    class FakeDB:
        @classmethod
        def get_instance(cls):
            return cls()

        def get_database(self):
            return object()

    monkeypatch.setattr(report_module, "AppDatabase", FakeDB)
    monkeypatch.setattr(report_module, "SessionRepository", FakeRepo)
    return report_module


def test_report_list_sessions(fake_repo):
    result = runner.invoke(app, ["report", "--list"])
    assert result.exit_code == 0 and "session-1" in result.output and "session-2" in result.output


def test_report_regenerates_from_state_and_derives_base_url(fake_repo, monkeypatch):
    calls = []

    async def fake_report(findings, visited, session_id, base_url):
        calls.append(base_url)
        return "reports/r.md"

    monkeypatch.setattr(fake_repo, "generate_report", fake_report)
    result = runner.invoke(app, ["report", "session-1"])
    assert result.exit_code == 0
    assert "reports/r.md" in result.output
    assert calls == ["https://example.com"]


def test_report_requires_base_url_when_not_derivable(fake_repo):
    result = runner.invoke(app, ["report", "session-2"])
    assert result.exit_code == 2


def test_report_accepts_explicit_base_url(fake_repo, monkeypatch):
    calls = []

    async def fake_report(findings, visited, session_id, base_url):
        calls.append(base_url)
        return "reports/r2.md"

    monkeypatch.setattr(fake_repo, "generate_report", fake_report)
    result = runner.invoke(app, ["report", "session-2", "--base-url", "https://other.com"])
    assert result.exit_code == 0 and calls == ["https://other.com"]


def test_report_unknown_session_is_usage_error(fake_repo):
    result = runner.invoke(app, ["report", "nope"])
    assert result.exit_code == 2


def test_report_missing_arg_is_usage_error(fake_repo):
    result = runner.invoke(app, ["report"])
    assert result.exit_code == 2


def test_derive_base_url_takes_first_valid_origin():
    from src.cli.commands.report import derive_base_url

    findings = [{"url": "not-a-url"}, {"url": "https://a.com/x?y=1"}, {"url": "https://b.com/"}]
    assert derive_base_url(findings) == "https://a.com"
    assert derive_base_url([]) is None


def test_test_command_missing_dir_exits_one(tmp_path):
    result = runner.invoke(app, ["test", str(tmp_path / "nope")])
    assert result.exit_code == 1
    assert "未找到生成的测试" in result.output


def test_test_command_propagates_pytest_exit_code(tmp_path):
    (tmp_path / "demo_spec.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    result = runner.invoke(app, ["test", str(tmp_path)])
    assert result.exit_code == 0
    assert "所有测试均已通过" in result.output


def test_test_command_propagates_failure_exit_code(tmp_path):
    (tmp_path / "bad_spec.py").write_text("def test_bad():\n    assert False\n", encoding="utf-8")
    result = runner.invoke(app, ["test", str(tmp_path)])
    assert result.exit_code != 0


def test_help_lists_all_subcommands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for name in ("run", "report", "test", "mcp"):
        assert name in result.output


def test_mcp_command_delegates_to_mcp_entry(monkeypatch):
    import sys
    import types

    called = []
    fake_module = types.ModuleType("src.mcp.index")

    async def fake_main():
        called.append(True)

    fake_module.main = fake_main
    monkeypatch.setitem(sys.modules, "src.mcp.index", fake_module)
    result = runner.invoke(app, ["mcp"])
    assert result.exit_code == 0
    assert called == [True]


@pytest.mark.asyncio
async def test_explore_respects_max_steps():
    agent = FakeAgent(steps=[STEP_A, STEP_A, STEP_A])
    results = [result async for result in explore(agent, pause=0, max_steps=2)]
    assert len(results) == 2
    assert agent.stopped


def test_run_respects_max_steps(fake_run_env):
    agent, _ = fake_run_env
    result = runner.invoke(app, ["run", "https://example.com", "--max-steps", "1", "--json"])
    assert result.exit_code == 0
    payload = json_module.loads(result.stdout)
    assert payload["steps"] == 1
    assert payload["reportPath"] == "reports/fake.md"


def test_render_step_escapes_rich_markup_in_current_url():
    out = _capture_console()
    result = {"action": "navigate", "reason": "r",
              "stats": {"currentUrl": "https://x/[/x]", "queueLength": 0, "visitedCount": 0,
                        "findingsCount": 0}}
    render_step(1, result, 0, out)
    text = out.file.getvalue()
    assert "https://x/[/x]" in text
