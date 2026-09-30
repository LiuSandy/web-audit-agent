"""WebAudit CLI 层的测试（ROADMAP #3）。"""
from typer.testing import CliRunner

from src.cli.app import app

runner = CliRunner()


def test_version_outputs_project_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output
