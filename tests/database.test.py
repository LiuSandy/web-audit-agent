"""Equivalent database checks plus cross-runtime persistence contracts."""

from __future__ import annotations

import pytest

from src.auth.credential_storage import CredentialStorage
from src.auth.session_manager import SessionManager
from src.database.database import AppDatabase
from src.repositories.session_repository import SessionRepository
from src.types.index import OrderedSet


@pytest.fixture
def db():
    instance = AppDatabase(":memory:")
    yield instance
    instance.close()


def test_should_create_all_3_tables_in_single_database(db):
    names = [row["name"] for row in db.getDatabase().execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )]
    assert "agent_sessions" in names
    assert "credentials" in names
    assert "browser_sessions" in names


@pytest.mark.asyncio
async def test_CredentialStorage_should_store_and_retrieve_credentials(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    storage = CredentialStorage(db.getDatabase())
    await storage.set("testapp", {"email": "test@example.com", "password": "SecurePass123!"})
    retrieved = await storage.get("testapp")
    assert retrieved["email"] == "test@example.com"
    assert retrieved["password"] == "SecurePass123!"


@pytest.mark.asyncio
async def test_CredentialStorage_should_list_stored_credentials(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    storage = CredentialStorage(db.getDatabase())
    await storage.set("app1", {"password": "p1"})
    await storage.set("app2", {"password": "p2"})
    names = await storage.list()
    assert "app1" in names and "app2" in names


def test_SessionRepository_should_save_and_load_agent_state(db):
    repository = SessionRepository(db.getDatabase())
    state = {
        "visitedUrls": OrderedSet(["http://example.com"]), "findings": [], "steps": 5,
        "history": [], "todoQueue": ["http://example.com/page2"],
    }
    repository.saveState("test-session-1", state)
    loaded = repository.loadState("test-session-1")
    assert loaded is not None
    assert loaded["steps"] == 5
    assert isinstance(loaded["visitedUrls"], set)
    assert "http://example.com" in loaded["visitedUrls"]


def test_SessionRepository_should_list_sessions(db):
    repository = SessionRepository(db.getDatabase())
    for identifier in ("session-1", "session-2"):
        repository.saveState(identifier, {
            "visitedUrls": OrderedSet(), "findings": [], "steps": 1,
            "history": [], "todoQueue": [],
        })
    assert {"session-1", "session-2"}.issubset(set(repository.listSessions()))


def test_should_use_single_database_file(db, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    connection = db.getDatabase()
    CredentialStorage(connection)
    SessionRepository(connection).listSessions()
    SessionManager(connection)


def test_SessionRepository_preserves_Set_insertion_order(db):
    repository = SessionRepository(db.getDatabase())
    urls = OrderedSet(["https://example.com/second", "https://example.com/first"])
    repository.saveState("ordered", {
        "visitedUrls": urls, "findings": [], "steps": 2,
        "history": [], "todoQueue": [],
    })
    loaded = repository.loadState("ordered")
    assert list(loaded["visitedUrls"]) == ["https://example.com/second", "https://example.com/first"]


@pytest.mark.parametrize("table,columns", [
    ("agent_sessions", {"id", "state", "created_at", "updated_at"}),
    ("credentials", {"app_identifier", "encrypted_data", "iv", "metadata", "created_at", "updated_at"}),
    ("browser_sessions", {"app_identifier", "cookies", "storage_state", "expires_at", "created_at", "updated_at"}),
])
def test_table_should_have_correct_schema(db, table, columns):
    actual = {row["name"] for row in db.getDatabase().execute(f"PRAGMA table_info({table})")}
    assert columns.issubset(actual)
