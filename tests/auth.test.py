"""Tests for the auth modules."""

import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from src.auth.auth_manager import AuthenticationManager
from src.auth.credential_storage import CredentialStorage
from src.database.database import AppDatabase


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


@pytest.fixture(scope="module")
def test_server():
    directory = Path(__file__).parent / "test-resources" / "test-app"
    handler = partial(SimpleHTTPRequestHandler, directory=str(directory))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


@pytest.fixture
def auth_manager():
    db = AppDatabase(":memory:")
    manager = AuthenticationManager(db.get_database())
    storage = CredentialStorage(db.get_database())
    yield manager, storage
    db.close()


@pytest.mark.asyncio
async def test_detect_login_page(page, test_server):
    await page.goto(f"{test_server}/login.html")
    assert "Login" in await page.title()
    assert await page.locator('input[type="email"]').count() > 0
    assert await page.locator('input[type="password"]').count() > 0
    assert await page.locator('button[type="submit"]').count() > 0


@pytest.mark.asyncio
async def test_not_authenticated_on_login_page(page, test_server, auth_manager):
    manager, _ = auth_manager
    await page.goto(f"{test_server}/login.html")
    assert await manager.is_authenticated(page) is False


@pytest.mark.asyncio
async def test_successfully_login_with_valid_credentials(page, test_server, auth_manager):
    manager, storage = auth_manager
    await storage.set("testapp", {"email": "test@example.com", "password": "SecurePass123!"})
    await page.goto(f"{test_server}/login.html")
    await page.fill('input[type="email"]', "test@example.com")
    await page.fill('input[type="password"]', "SecurePass123!")
    await page.click('button[type="submit"]')
    await page.wait_for_url("**/dashboard.html", timeout=3000)
    assert "dashboard.html" in page.url
    assert await manager.is_authenticated(page) is True


@pytest.mark.asyncio
async def test_detect_authenticated_state_on_dashboard(page, test_server):
    await page.goto(f"{test_server}/login.html")
    await page.fill('input[type="email"]', "test@example.com")
    await page.fill('input[type="password"]', "SecurePass123!")
    await page.click('button[type="submit"]')
    await page.wait_for_url("**/dashboard.html", timeout=3000)
    has_logout_button = await page.evaluate("""() => {
      for (const el of document.querySelectorAll('button, a')) {
        const text = el.textContent?.toLowerCase() || '';
        if (text.includes('logout')) return true;
      }
      return false;
    }""")
    assert has_logout_button is True


@pytest.mark.asyncio
async def test_fail_login_with_invalid_credentials(page, test_server):
    await page.goto(f"{test_server}/login.html")
    await page.fill('input[type="email"]', "wrong@example.com")
    await page.fill('input[type="password"]', "WrongPassword!")
    await page.click('button[type="submit"]')
    await page.wait_for_timeout(1500)
    assert "login.html" in page.url
    error_visible = await page.evaluate("""() => {
      const errorMsg = document.getElementById('errorMessage');
      return errorMsg && errorMsg.style.display !== 'none';
    }""")
    assert error_visible is True


@pytest.mark.asyncio
async def test_logout_successfully(page, test_server, auth_manager):
    manager, _ = auth_manager
    await page.goto(f"{test_server}/login.html")
    await page.fill('input[type="email"]', "test@example.com")
    await page.fill('input[type="password"]', "SecurePass123!")
    await page.click('button[type="submit"]')
    await page.wait_for_url("**/dashboard.html", timeout=3000)
    await page.click('button:has-text("Logout")')
    await page.wait_for_url("**/login.html", timeout=3000)
    assert "login.html" in page.url
    assert await manager.is_authenticated(page) is False


@pytest.mark.asyncio
async def test_redirect_to_login_without_auth(page, test_server):
    await page.goto(f"{test_server}/dashboard.html")
    await page.evaluate("() => localStorage.clear()")
    await page.reload()
    await page.wait_for_url("**/login.html", timeout=3000)
    assert "login.html" in page.url
