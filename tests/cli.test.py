"""WebAudit CLI 层的测试（ROADMAP #3）。"""
from typer.testing import CliRunner

from src.cli.app import app
from src.cli.core.config import RunOptions, build_config, new_session_id, validate_auth

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
