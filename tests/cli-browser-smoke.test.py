"""Local end-to-end CLI run/resume/report smoke without an external LLM."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from src.cli.app import app
from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository


@pytest.fixture
def local_site():
    class Handler(BaseHTTPRequestHandler):
        logins = 0

        def log_message(self, *args):
            pass

        def do_GET(self):
            authenticated = "session=valid" in self.headers.get("Cookie", "")
            body = ('<title>Private</title><button>Logout</button>'
                    '<button id="go" class="hover:bg-black" onclick="this.textContent=\'Clicked\'">Go</button>') if authenticated else (
                    '<title>Login</title><form method="post" action="/login">'
                    '<input type="email" name="email"><input type="password" name="password">'
                    '<button type="submit">Login</button></form>')
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body.encode())

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            Handler.logins += 1
            self.send_response(302)
            self.send_header("Set-Cookie", "session=valid; Path=/; HttpOnly")
            self.send_header("Location", "/private")
            self.end_headers()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", Handler
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_run_resume_auth_and_report_on_real_browser(local_site, tmp_path, monkeypatch):
    url, handler = local_site
    monkeypatch.chdir(tmp_path)
    db = AppDatabase(":memory:")
    monkeypatch.setattr(AppDatabase, "instance", db)
    prompts = []

    class Model:
        async def ainvoke(self, messages):
            prompts.append(messages)
            assert "Private" in messages[0].content
            action = {"action": "click", "params": "#go", "reason": "test button"} if len(prompts) == 1 else {
                "action": "finish", "reason": "done"}
            return SimpleNamespace(content=json.dumps(action))

    monkeypatch.setattr("src.agents.exploratory.get_default_model", lambda: Model())
    runner = CliRunner()
    try:
        first = runner.invoke(app, ["run", url, "--session-id", "smoke", "--max-steps", "1", "--json",
                                   "--auth-email", "test@example.com", "--auth-password", "test-password",
                                   "--auth-app-identifier", "local-login"])
        assert first.exit_code == 0, first.output
        first_result = json.loads(first.stdout)
        assert first_result["terminationReason"] == "step_limit" and first_result["sessionSteps"] == 1
        saved = SessionRepository(db.get_database()).load_state("smoke")
        assert saved["history"][0]["success"] is True
        assert "test-password" not in json.dumps(saved, default=list)
        # Resume must reuse browser session cookies, without relying on stored credentials.
        db.get_database().execute("DELETE FROM credentials")
        second = runner.invoke(app, ["run", url, "--session-id", "smoke", "--max-steps", "1", "--json"])
        assert second.exit_code == 0, second.output
        second_result = json.loads(second.stdout)
        assert second_result["steps"] == 1 and second_result["sessionSteps"] == 2
        assert second_result["terminationReason"] == "completed" and handler.logins == 1
        report = runner.invoke(app, ["report", "smoke"])
        assert report.exit_code == 0, report.output
        report_path = Path(second_result["reportPath"])
        before = report_path.read_text()
        saved_before = SessionRepository(db.get_database()).load_state("smoke")
        conflict = runner.invoke(app, ["run", url.replace("127.0.0.1", "localhost"),
                                      "--session-id", "smoke", "--json"])
        assert conflict.exit_code == 2
        assert report_path.read_text() == before
        assert SessionRepository(db.get_database()).load_state("smoke") == saved_before
    finally:
        db.close()
