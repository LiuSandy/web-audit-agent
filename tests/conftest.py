"""Keep every test away from real user configuration, databases and credentials."""
import pytest

from src.database.database import AppDatabase
from src.runtime import set_runtime, reset_runtime


@pytest.fixture(autouse=True)
def isolated_webaudit_home(tmp_path, monkeypatch):
    monkeypatch.setenv("WEBAUDIT_HOME", str(tmp_path / "webaudit-home"))
    for name in ("WEBAUDIT_DATA_DIR", "WEBAUDIT_PROVIDER", "WEBAUDIT_MODEL", "WEBAUDIT_MAX_STEPS", "WEBAUDIT_MAX_FAILURES",
                 "OPENAI_API_KEY", "OPEN_AI_API_KEY", "OPENAI_BASE_URL", "OPEN_AI_API_URL", "GOOGLE_AI_STUDIO_API_KEY",
                 "OPENAI_MODEL", "OPEN_AI_MODEL", "GEMINI_MODEL", "CREDENTIAL_ENCRYPTION_KEY"):
        monkeypatch.delenv(name, raising=False)
    token = set_runtime(None)
    AppDatabase.reset()
    yield
    AppDatabase.reset()
    reset_runtime(token)
