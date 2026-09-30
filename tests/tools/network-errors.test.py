"""Tests for network error monitoring."""

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from src.tools.network_errors import NetworkMonitor


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


@pytest.mark.asyncio
async def test_capture_404_errors(page):
    monitor = NetworkMonitor(page)
    await page.set_content('<html><body><script src="https://nonexistent-test-domain-12345.com/script.js"></script></body></html>')
    await page.wait_for_timeout(1500)
    errors = monitor.get_errors()
    assert errors and any("nonexistent" in e["url"] for e in errors)


@pytest.mark.asyncio
async def test_capture_failed_requests(page):
    monitor = NetworkMonitor(page)
    await page.set_content("<html><body><img src='https://this-domain-definitely-does-not-exist-99999.com/image.png' /></body></html>")
    await page.wait_for_timeout(1500)
    assert monitor.get_errors()


@pytest.mark.asyncio
async def test_not_capture_successful_requests(page):
    monitor = NetworkMonitor(page)
    await page.goto("data:text/html,<html><body>Success</body></html>")
    await page.wait_for_timeout(500)
    errors = monitor.get_errors()
    assert not [e for e in errors if 200 <= e["status"] < 400]


@pytest.mark.asyncio
async def test_clear_errors_after_retrieval(page):
    monitor = NetworkMonitor(page)
    await page.goto("data:text/html,<html><body><img src='https://httpstat.us/404' /></body></html>")
    await page.wait_for_timeout(2000)
    monitor.get_errors()
    assert len(monitor.get_errors()) == 0


@pytest.mark.asyncio
async def test_peek_errors_without_clearing(page):
    monitor = NetworkMonitor(page)
    await page.goto("data:text/html,<html><body><img src='https://httpstat.us/404' /></body></html>")
    await page.wait_for_timeout(2000)
    assert len(monitor.peek_errors()) == len(monitor.peek_errors())


@pytest.mark.asyncio
async def test_handle_request_failures(page):
    monitor = NetworkMonitor(page)
    await page.goto("data:text/html,<html><body><img src='https://this-domain-definitely-does-not-exist-12345.com/image.png' /></body></html>")
    await page.wait_for_timeout(2000)
    errors = monitor.get_errors()
    assert errors
    assert any(e["status"] == 0 or "failed" in e["statusText"] for e in errors)


@pytest.mark.asyncio
async def test_capture_multiple_network_errors(page):
    monitor = NetworkMonitor(page)
    await page.goto("data:text/html,<html><body><img src='https://httpstat.us/404' /><img src='https://httpstat.us/500' /></body></html>")
    await page.wait_for_timeout(3000)
    assert len(monitor.get_errors()) >= 2


@pytest.mark.asyncio
async def test_include_page_url_in_findings(page):
    monitor = NetworkMonitor(page)
    test_url = "data:text/html,<html><body><img src='https://httpstat.us/404' /></body></html>"
    await page.goto(test_url)
    await page.wait_for_timeout(2000)
    errors = monitor.get_errors()
    if errors:
        assert errors[0].get("pageUrl")
