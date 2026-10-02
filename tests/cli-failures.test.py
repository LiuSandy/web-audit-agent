"""Failure boundary regressions for CLI outcomes and durable sessions."""
import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from typer.testing import CliRunner

from src.agents.exploratory import ExploratoryAgent, SessionTargetError
from src.cli.app import app
from src.cli.core.runner import ExplorationFailed, explore
from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository
from src.types.index import OrderedSet
from src.utils.report import generate_report
from tests.fakes import FakeAgent, STEP_A, STEP_B

runner = CliRunner()
FAILURE = {"action": "error", "reason": "invalid response", "completed": False, "success": False}


@pytest.fixture
def run_env(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    agent = FakeAgent()
    monkeypatch.setattr("src.cli.commands.run.ExploratoryAgent", lambda config: agent)
    return agent


@pytest.mark.asyncio
async def test_report_creates_directory_and_marks_partial_result(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = await generate_report([], [], "session", "https://example.com", {"terminationReason": "failed"})
    assert Path(path).is_file()
    assert "运行失败（部分结果）" in Path(path).read_text()


def test_report_write_failure_is_json_failure(run_env, monkeypatch):
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("disk full")))
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["status"] == "failed" and payload["reportPath"] is None
    assert "disk full" in result.stderr


def test_constructor_failure_outputs_json(monkeypatch):
    monkeypatch.setattr("src.cli.commands.run.ExploratoryAgent", Mock(side_effect=RuntimeError("API key missing")))
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["steps"] == 0 and payload["findings"] == []


def test_start_failure_cleans_up_and_saves_partial_report(run_env):
    run_env.start = AsyncMock(side_effect=RuntimeError("login failed"))
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 1 and run_env.stopped
    assert Path(payload["reportPath"]).is_file()


def test_target_conflict_does_not_overwrite_report(run_env):
    run_env.start = AsyncMock(side_effect=SessionTargetError("wrong site"))
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    assert result.exit_code == 2 and run_env.stopped
    assert json.loads(result.stdout)["reportPath"] is None
    assert not Path("reports").exists()


def test_consecutive_errors_fail_and_save_report(run_env):
    run_env.steps = [FAILURE]
    result = runner.invoke(app, ["run", "https://example.com", "--json", "--max-failures", "2"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 1
    assert payload["steps"] == payload["failedSteps"] == 2
    assert payload["terminationReason"] == "failed" and Path(payload["reportPath"]).is_file()


def test_step_limit_is_distinct_from_completed(run_env):
    run_env.steps = [STEP_A]
    result = runner.invoke(app, ["run", "https://example.com", "--json", "--max-steps", "1"])
    assert result.exit_code == 0
    assert json.loads(result.stdout)["terminationReason"] == "step_limit"


def test_cancelled_run_outputs_json_and_partial_report(run_env):
    run_env.cancelled_during = 1
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 130 and payload["terminationReason"] == "cancelled"
    assert Path(payload["reportPath"]).is_file() and run_env.stopped


def test_cancelled_report_failure_keeps_interrupt_exit(run_env, monkeypatch):
    run_env.cancelled_during = 1
    monkeypatch.setattr(Path, "write_text", Mock(side_effect=OSError("disk full")))
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    assert result.exit_code == 130
    assert json.loads(result.stdout)["errors"]


@pytest.mark.parametrize("args", [
    ["--max-steps", "0"], ["--max-steps", "-1"], ["--max-failures", "0"],
    ["--timeout", "0"], ["--max-concurrency", "0"], ["--retry-count", "-1"],
    ["--session-id", "../other"],
])
def test_invalid_options_exit_two_before_start(run_env, args):
    result = runner.invoke(app, ["run", "https://example.com", *args])
    assert result.exit_code == 2 and not run_env.started


def test_invalid_url_exit_two_before_start(run_env):
    result = runner.invoke(app, ["run", "not-a-url"])
    assert result.exit_code == 2 and not run_env.started


@pytest.mark.asyncio
async def test_success_resets_consecutive_failure_count():
    agent = FakeAgent(steps=[FAILURE, FAILURE, STEP_A, FAILURE, FAILURE, STEP_B])
    results = [result async for result in explore(agent, pause=0)]
    assert len(results) == 6 and agent.run_summary["failedSteps"] == 4
    assert agent.run_summary["terminationReason"] == "completed"


@pytest.mark.asyncio
async def test_failure_at_budget_exhaustion_is_not_success():
    agent = FakeAgent(steps=[FAILURE])
    with pytest.raises(ExplorationFailed):
        [result async for result in explore(agent, pause=0, max_steps=1)]
    assert agent.stopped


@pytest.mark.asyncio
async def test_cleanup_failure_preserves_original_error():
    agent = FakeAgent(error=RuntimeError("primary"))
    agent.stop = AsyncMock(side_effect=RuntimeError("cleanup"))
    with pytest.raises(RuntimeError, match="primary"):
        [result async for result in explore(agent, pause=0)]
    assert agent.run_summary["cleanupErrors"] == ["cleanup"]


def test_cleanup_failure_changes_success_to_failure(run_env):
    run_env.stop = AsyncMock(side_effect=RuntimeError("cleanup"))
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["cleanupErrors"] == ["cleanup"]


@pytest.mark.asyncio
async def test_browser_close_failure_still_stops_playwright():
    agent = object.__new__(ExploratoryAgent)
    agent.browser = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("close failed")))
    playwright = SimpleNamespace(stop=AsyncMock())
    agent.playwright = playwright
    with pytest.raises(RuntimeError, match="close failed"):
        await agent.stop()
    playwright.stop.assert_awaited_once()
    assert agent.browser is None and agent.playwright is None


@pytest.mark.parametrize("method,args", [("save_state", ("x", {})), ("load_state", ("x",)), ("list_sessions", ())])
def test_repository_errors_are_distinct_from_missing_session(method, args):
    db = AppDatabase(":memory:")
    repository = SessionRepository(db.get_database())
    db.close()
    with pytest.raises(RuntimeError):
        getattr(repository, method)(*args)


def test_report_database_failure_exit_one(monkeypatch):
    monkeypatch.setattr("src.cli.commands.report.AppDatabase.get_instance", Mock(side_effect=RuntimeError("db unavailable")))
    result = runner.invoke(app, ["report", "--list"])
    assert result.exit_code == 1 and "db unavailable" in result.stderr


def test_session_save_failure_exits_one(run_env):
    run_env.state = {"steps": 4}
    run_env.session_ready = True
    run_env.save_state = Mock(side_effect=RuntimeError("database full"))
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    assert result.exit_code == 1
    assert "database full" in result.stderr


@pytest.fixture
def bare_agent():
    agent = object.__new__(ExploratoryAgent)
    agent.config = {"sessionId": "test", "baseUrl": "https://example.com", "runId": "run-test", "artifactDir": "/tmp/bare-agent-test"}
    agent.session_ready = True
    agent.state = {"steps": 0, "visitedUrls": OrderedSet(), "history": [], "todoQueue": [], "findings": []}
    agent.session_repo = SimpleNamespace(save_state=Mock())
    agent.page = SimpleNamespace(url="https://example.com", title=AsyncMock(return_value="Demo"), evaluate=AsyncMock(return_value=[]))
    return agent


@pytest.mark.asyncio
async def test_invalid_model_response_is_saved_in_history(bare_agent):
    bare_agent.model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="not JSON")))
    result = await bare_agent.step()
    assert result["success"] is False
    assert bare_agent.state["history"][-1]["success"] is False
    bare_agent.session_repo.save_state.assert_called_once()


@pytest.mark.asyncio
async def test_action_failure_reaches_next_model_prompt(bare_agent):
    bare_agent.model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(
        content=json.dumps({"action": "click", "reason": "checkout", "params": "#missing"}))))
    bare_agent.page.click = AsyncMock(side_effect=RuntimeError("element missing"))
    bare_agent.perform_automatic_bug_scanning = AsyncMock()
    result = await bare_agent.step()
    assert result["success"] is False and "element missing" in result["result"]
    assert bare_agent.state["history"][-1]["result"] == result["result"]
    await bare_agent.step()
    prompt = bare_agent.model.ainvoke.call_args.args[0][0].content
    assert "element missing" in prompt


@pytest.mark.asyncio
async def test_step_save_failure_propagates(bare_agent):
    bare_agent.model = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(
        content=json.dumps({"action": "finish", "reason": "done"}))))
    bare_agent.session_repo.save_state.side_effect = RuntimeError("database full")
    with pytest.raises(RuntimeError, match="database full"):
        await bare_agent.step()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_resume_validates_target_before_browser_start(bare_agent, monkeypatch, legacy):
    saved = {**bare_agent.state, "steps": 2, "baseUrl": "https://other.example"}
    if legacy:
        saved.pop("baseUrl")
        saved["visitedUrls"] = OrderedSet(["https://other.example/page"])
    bare_agent.session_ready = False
    bare_agent.session_repo.load_state = Mock(return_value=saved)
    browser_start = Mock()
    monkeypatch.setattr("src.agents.exploratory.async_playwright", browser_start)
    with pytest.raises(SessionTargetError):
        await bare_agent.start()
    browser_start.assert_not_called()
    assert not bare_agent.session_ready


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_resume_restores_auth_and_uses_last_url(bare_agent, monkeypatch, legacy):
    saved = {**bare_agent.state, "steps": 9, "visitedUrls": OrderedSet(["https://example.com/page"]),
             "history": [{"url": "https://example.com/page", "action": "click", "reason": "old"}],
             "runConfig": {"authAppIdentifier": "saved-login"}}
    if not legacy:
        saved["baseUrl"] = "https://example.com"
    bare_agent.session_repo.load_state = Mock(return_value=saved)
    bare_agent.auth_manager = SimpleNamespace(authenticate=AsyncMock(return_value={"success": True, "method": "restore"}))
    bare_agent.page.goto = AsyncMock()
    browser = SimpleNamespace(new_page=AsyncMock(return_value=bare_agent.page))
    playwright = SimpleNamespace(chromium=SimpleNamespace(launch=AsyncMock(return_value=browser)))
    monkeypatch.setattr("src.agents.exploratory.async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=playwright)))
    monkeypatch.setattr("src.agents.exploratory.ConsoleMonitor", Mock())
    monkeypatch.setattr("src.agents.exploratory.NetworkMonitor", Mock())
    await bare_agent.start()
    bare_agent.auth_manager.authenticate.assert_awaited_once_with(bare_agent.page, "saved-login")
    assert bare_agent.page.goto.await_args_list[-1].args[0] == "https://example.com/page"
    assert bare_agent.state["steps"] == 9
    assert bare_agent.state["baseUrl"] == "https://example.com"
    assert "credentials" not in bare_agent.state["runConfig"]


@pytest.mark.asyncio
async def test_resume_budget_counts_new_steps_only():
    agent = FakeAgent(steps=[STEP_A])
    agent.state = {"steps": 20}
    [result async for result in explore(agent, pause=0, max_steps=2)]
    assert len(agent.step_calls) == 2 and agent.run_summary["steps"] == 2


def test_wizard_uses_failure_contract(monkeypatch, tmp_path):
    from src.cli.core.config import RunOptions
    from src.cli.wizard import run_wizard

    monkeypatch.chdir(tmp_path)
    agent = FakeAgent(steps=[FAILURE])
    monkeypatch.setattr("src.cli.wizard._collect_options", AsyncMock(return_value=RunOptions(
        base_url="https://example.com", max_failures=1)))
    monkeypatch.setattr("src.cli.wizard.ExploratoryAgent", lambda config: agent)
    assert asyncio.run(run_wizard()) == 1
    from src.runtime import get_runtime
    assert agent.stopped and list(get_runtime().runs.rglob("report.md"))


def test_cancel_during_test_generation_still_outputs_json(run_env):
    run_env.generate_tests = AsyncMock(side_effect=asyncio.CancelledError())
    result = runner.invoke(app, ["run", "https://example.com", "--json", "--generate-tests"])
    payload = json.loads(result.stdout)
    assert result.exit_code == 130 and payload["terminationReason"] == "cancelled"
    assert "用户中断" in Path(payload["reportPath"]).read_text()


@pytest.mark.asyncio
async def test_raised_step_error_counts_attempted_step():
    agent = FakeAgent(error=RuntimeError("save failed"))
    with pytest.raises(RuntimeError, match="save failed"):
        [result async for result in explore(agent, pause=0)]
    assert agent.run_summary["steps"] == agent.run_summary["failedSteps"] == 1
