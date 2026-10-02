"""Configuration and destructive command boundaries use isolated user directories."""
import asyncio
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli.app import app
from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository
from src.runtime import resolve_runtime, get_runtime, ensure_home, write_private
from src.runtime.secrets import get_api_key, save_api_key, service_name
from src.utils.report import generate_report

runner = CliRunner()


@pytest.mark.parametrize("args", [["--version"], ["--help"], ["paths"], ["config", "show", "--sources"]])
def test_information_commands_do_not_create_home(args):
    home = get_runtime().home
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert not home.exists()


def test_config_init_environment_is_private_and_lazy(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret-environment-value")
    runtime = get_runtime()
    result = runner.invoke(app, ["config", "init", "--non-interactive"])
    assert result.exit_code == 0, result.output
    content = runtime.config_file.read_text()
    assert "secret-environment-value" not in content
    assert runtime.config_file.stat().st_mode & 0o777 == 0o600
    assert not runtime.data.exists()
    assert not runtime.credentials.exists()
    shown = runner.invoke(app, ["config", "show", "--sources"])
    assert "secret-environment-value" not in shown.output
    assert "OPENAI_API_KEY" in shown.output


def test_unconfigured_run_leaves_no_database():
    result = runner.invoke(app, ["run", "https://example.com", "--json"])
    assert result.exit_code == 1
    assert json.loads(result.stdout)["status"] == "failed"
    assert not get_runtime().home.exists()


def test_explicit_env_file_existing_environment_wins_and_restores(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("OPENAI_API_KEY=file-secret\nWEBAUDIT_MODEL=from-file\n")
    monkeypatch.setenv("OPENAI_API_KEY", "existing-secret")
    result = runner.invoke(app, ["--env-file", str(path), "config", "show", "--sources"])
    assert result.exit_code == 0, result.output
    assert "from-file" in result.output
    import os
    assert "WEBAUDIT_MODEL" not in os.environ
    assert os.environ["OPENAI_API_KEY"] == "existing-secret"
    monkeypatch.chdir(tmp_path)
    shown = runner.invoke(app, ["config", "show"])
    assert "from-file" not in shown.output


def test_home_data_and_model_priority(tmp_path, monkeypatch):
    home = tmp_path / "config-home"
    write_private(home / "config.toml", '[llm]\nprovider="gemini"\nmodel="configured"\n[storage]\ndata_dir="relative-data"\n')
    runtime = resolve_runtime(home=home)
    assert runtime.data == home / "relative-data"
    monkeypatch.setenv("WEBAUDIT_DATA_DIR", str(tmp_path / "env-data"))
    monkeypatch.setenv("OPENAI_MODEL", "openai-env")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-env")
    assert resolve_runtime(home=home).settings["llm"]["model"] == "gemini-env"
    monkeypatch.setenv("WEBAUDIT_MODEL", "shared-env")
    assert resolve_runtime(home=home).settings["llm"]["model"] == "shared-env"
    result = resolve_runtime(home, tmp_path / "cli-data", overrides={"provider": "openai", "model": "cli-model"})
    assert result.data == tmp_path / "cli-data"
    assert result.settings["llm"]["model"] == "cli-model"
    assert result.credentials == home / "credentials"


def test_legacy_key_alias_and_conflict_warning(monkeypatch):
    monkeypatch.setenv("OPEN_AI_API_KEY", "legacy-secret")
    assert get_api_key("openai")[0] == "legacy-secret"
    monkeypatch.setenv("OPENAI_API_KEY", "standard-secret")
    with pytest.warns(UserWarning, match="使用 OPENAI_API_KEY"):
        assert get_api_key("openai")[0] == "standard-secret"


def test_interactive_file_secret_and_reset():
    result = runner.invoke(app, ["config", "init", "--secret-storage", "file"], input="openai\n\ngpt-4o-mini\nfile-secret\n")
    assert result.exit_code == 0, result.output
    runtime = get_runtime()
    key_file = runtime.credentials / "api_keys.json"
    assert key_file.stat().st_mode & 0o777 == 0o600
    assert get_api_key("openai")[0] == "file-secret"
    assert not runtime.database.exists()
    shown = runner.invoke(app, ["config", "show"])
    assert "file-secret" not in shown.output
    reset = runner.invoke(app, ["config", "reset", "--yes"])
    assert reset.exit_code == 0
    assert not runtime.config_file.exists() and key_file.exists()


def test_keyring_failure_never_falls_back_to_plaintext(monkeypatch):
    import keyring
    def unavailable(*args):
        raise RuntimeError("locked")
    monkeypatch.setattr(keyring, "set_password", unavailable)
    result = runner.invoke(app, ["config", "init"], input="openai\n\ngpt-4o-mini\nkeyring-secret\n")
    assert result.exit_code == 1
    assert "系统凭据库写入失败" in result.output
    assert not get_runtime().config_file.exists()
    assert not get_runtime().credentials.exists()


def test_keyring_namespace_and_uninstall(monkeypatch, tmp_path):
    import keyring
    values = {}
    monkeypatch.setattr(keyring, "set_password", lambda service, account, value: values.__setitem__((service, account), value))
    monkeypatch.setattr(keyring, "get_password", lambda service, account: values.get((service, account)))
    monkeypatch.setattr(keyring, "delete_password", lambda service, account: values.pop((service, account)))
    runtime = get_runtime()
    ensure_home(runtime)
    save_api_key("openai", "own-key", "keyring", runtime)
    other = resolve_runtime(home=tmp_path / "another-home")
    save_api_key("openai", "other-key", "keyring", other)
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert not runtime.home.exists()
    assert values[(service_name(other), "openai")] == "other-key"


def test_uninstall_preserves_external_data_config_and_symlink_target(tmp_path):
    runtime = get_runtime()
    ensure_home(runtime)
    external = tmp_path / "external"
    external.mkdir()
    (external / "keep").write_text("keep")
    (runtime.home / "link").symlink_to(external, target_is_directory=True)
    config = tmp_path / "external.toml"
    config.write_text('[storage]\ndata_dir="external"\n')
    result = runner.invoke(app, ["--config", str(config), "uninstall"])
    assert result.exit_code == 0, result.output
    assert not runtime.home.exists()
    assert config.exists() and (external / "keep").exists()
    assert "根目录外" in result.output


@pytest.mark.parametrize("kind", ["unmanaged", "symlink", "cwd"])
def test_uninstall_refuses_unsafe_root(tmp_path, monkeypatch, kind):
    root = tmp_path / "root"
    root.mkdir()
    (root / "keep").write_text("keep")
    if kind == "cwd":
        ensure_home(resolve_runtime(home=root))
        monkeypatch.chdir(root)
    elif kind == "symlink":
        link = tmp_path / "root-link"
        link.symlink_to(root, target_is_directory=True)
        root = link
    result = runner.invoke(app, ["--home", str(root), "uninstall"])
    assert result.exit_code == 2
    assert (root / "keep").exists()


def test_corrupt_config_does_not_block_uninstall():
    runtime = get_runtime()
    ensure_home(runtime)
    runtime.config_file.write_text("[broken")
    assert runner.invoke(app, ["paths"]).exit_code == 2
    result = runner.invoke(app, ["uninstall"])
    assert result.exit_code == 0, result.output
    assert not runtime.home.exists()


def test_database_switches_with_home_and_has_private_permissions(tmp_path, monkeypatch):
    first = AppDatabase.get_instance()
    first_path = Path(first.db_path)
    assert first_path == get_runtime().database
    assert first_path.stat().st_mode & 0o777 == 0o600
    monkeypatch.setenv("WEBAUDIT_HOME", str(tmp_path / "second-home"))
    second = AppDatabase.get_instance()
    assert second is not first
    assert Path(second.db_path) == get_runtime().database
    assert first_path.exists()


def seed_report(runtime, session="s", run="r", description="historical"):
    repository = SessionRepository(AppDatabase.get_instance().get_database())
    directory = runtime.run_dir(session, run)
    source = runtime.data / "old.png"
    write_private(source, "test-image")
    findings = [{"type": "bug", "severity": "high", "url": "https://example.com", "description": description, "screenshot": str(source)}]
    path = asyncio.run(generate_report(findings, [], session, "https://example.com", artifact_dir=str(directory), run_id=run))
    repository.save_state(session, {"baseUrl": "https://example.com", "findings": findings, "artifactDir": str(directory), "runId": run})
    repository.save_run(session, run, directory, path, {})
    return repository, Path(path)


def test_historical_reports_export_portable_attachments(tmp_path):
    runtime = get_runtime()
    repository, old = seed_report(runtime)
    _, latest = seed_report(runtime, run="r2", description="latest")
    export = tmp_path / "export"
    result = runner.invoke(app, ["report", "s", "--run-id", "r", "--output-dir", str(export)])
    assert result.exit_code == 0, result.output
    exported = export / "s" / "r" / "report.md"
    assert exported.read_text() == old.read_text()
    assert "historical" in exported.read_text() and "latest" not in exported.read_text()
    assert str(runtime.data) not in exported.read_text()
    assert list((exported.parent / "screenshots").iterdir())
    assert latest.exists()
    repository.save_run("s", "r", old.parent, None, {"updated": True})
    assert next(run for run in repository.list_runs() if run["id"] == "r")["report_path"] == str(old)


def test_clean_preview_updates_index_and_preserves_resume_state():
    runtime = get_runtime()
    repository, report = seed_report(runtime)
    preview = runner.invoke(app, ["clean", "--runs", "--session-id", "s", "--dry-run"])
    assert preview.exit_code == 0 and report.exists()
    result = runner.invoke(app, ["clean", "--runs", "--session-id", "s", "--yes"])
    assert result.exit_code == 0, result.output
    assert not report.exists() and repository.list_runs() == []
    state = repository.load_state("s")
    assert state["baseUrl"] == "https://example.com"
    assert "artifactDir" not in state
    assert runner.invoke(app, ["report", "s"]).exit_code == 0
    assert repository.latest_run("s")["report_path"]


def test_clean_refuses_symlink_run_root(tmp_path):
    runtime = get_runtime()
    ensure_home(runtime)
    runtime.data.mkdir()
    outside = tmp_path / "outside"
    (outside / "session" / "run").mkdir(parents=True)
    runtime.runs.symlink_to(outside, target_is_directory=True)
    result = runner.invoke(app, ["clean", "--runs", "--yes"])
    assert result.exit_code == 2
    assert (outside / "session" / "run").exists()


def test_mcp_report_never_returns_another_sessions_report():
    from src.mcp.resources.reports import handle_test_report_resource
    seed_report(get_runtime())
    with pytest.raises(FileNotFoundError):
        asyncio.run(handle_test_report_resource("test-report://missing"))
    result = asyncio.run(handle_test_report_resource("test-report://s"))
    assert "historical" in result["contents"][0]["text"]


@pytest.mark.parametrize("toml", ['[llm]\nmodel=1', '[llm]\nsecret_storage="unknown"', '[storage]\ndata_dir=2', '[run]\nmax_steps=0'])
def test_invalid_configuration_is_usage_error(toml):
    write_private(get_runtime().config_file, toml)
    result = runner.invoke(app, ["paths"])
    assert result.exit_code == 2
    assert "Traceback" not in result.output


def test_clean_credentials_removes_website_data_but_keeps_exploration():
    from src.auth.credential_storage import CredentialStorage
    runtime = get_runtime()
    repository, report = seed_report(runtime)
    db = AppDatabase.get_instance().get_database()
    storage = CredentialStorage(db)
    asyncio.run(storage.set("website", {"email": "a@example.com", "password": "password"}))
    db.execute("INSERT INTO browser_sessions(app_identifier,cookies,created_at,updated_at) VALUES ('website','[]',1,1)")
    result = runner.invoke(app, ["clean", "--credentials", "--yes"])
    assert result.exit_code == 0, result.output
    assert not runtime.credentials.exists()
    assert db.execute("SELECT count(*) FROM credentials").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM browser_sessions").fetchone()[0] == 0
    assert repository.load_state("s") and report.exists()


def test_single_page_report_uses_shared_storage(monkeypatch):
    from src.agents.single_page import SinglePageTestingAgent
    class Page:
        async def goto(self, *args, **kwargs):
            pass
    agent = SinglePageTestingAgent({"targetUrl": "https://example.com", "sessionId": "single", "model": object()})
    async def init():
        agent.page = Page()
    async def empty(*args):
        return []
    async def plan(*args):
        return {"testCases": [], "totalTests": 0}
    monkeypatch.setattr(agent, "init_browser", init)
    monkeypatch.setattr(agent, "discover_elements", empty)
    monkeypatch.setattr(agent, "generate_test_plan", plan)
    monkeypatch.setattr(agent, "run_layout_audit", empty)
    monkeypatch.setattr(agent, "run_visual_regression", empty)
    state = asyncio.run(agent.start())
    path = Path(state["reportPath"])
    assert path.is_relative_to(get_runtime().runs) and path.exists()
    repository = SessionRepository(AppDatabase.get_instance().get_database())
    assert repository.latest_run("single")["report_path"] == str(path)


def test_mcp_exploration_saves_report_once(monkeypatch):
    import src.mcp.tools.exploratory as module
    executions = {"mcp": {"status": "pending"}}
    calls = []
    class Agent:
        config = {"baseUrl": "https://example.com", "sessionId": "mcp", "runId": "run-mcp"}
        session_ready = False
        def __init__(self, config):
            pass
        async def start(self):
            self.session_ready = True
        async def step(self, guidance):
            return {"action": "finish", "completed": True, "success": True}
        async def stop(self):
            pass
        def get_findings(self):
            return []
        def get_visited_urls(self):
            return []
    async def finish(*args):
        calls.append(args)
        return "/report.md", None
    monkeypatch.setattr(module, "_active_tests", lambda: executions)
    monkeypatch.setattr(module, "ExploratoryAgent", Agent)
    monkeypatch.setattr(module, "finish_session", finish)
    asyncio.run(module.start_test_in_background({"baseUrl": "https://example.com", "sessionId": "mcp", "maxSteps": 1, "model": object()}))
    assert len(calls) == 1
    assert executions["mcp"]["status"] == "completed"
    assert executions["mcp"]["reportPath"] == "/report.md"
