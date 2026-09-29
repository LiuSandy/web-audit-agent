"""Port of tests/tools/console-errors.test.ts."""

import importlib

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

ConsoleMonitor = importlib.import_module("src.tools.console-errors").ConsoleMonitor


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


@pytest.mark.asyncio
async def test_capture_console_errors(page):
    monitor = ConsoleMonitor(page)
    await page.set_content('<html><body><script>console.error("Test error message");</script></body></html>')
    await page.wait_for_timeout(500)
    errors = monitor.getErrors()
    assert len(errors) > 0
    assert errors[0]["type"] == "error"
    assert "Test error message" in errors[0]["message"]
    assert "url" in errors[0] and "timestamp" in errors[0]


@pytest.mark.asyncio
async def test_capture_console_warnings(page):
    monitor = ConsoleMonitor(page)
    await page.set_content('<html><body><script>console.warn("Test warning message");</script></body></html>')
    await page.wait_for_timeout(500)
    warnings = [e for e in monitor.getErrors() if e["type"] == "warning"]
    assert warnings and "Test warning message" in warnings[0]["message"]


@pytest.mark.asyncio
async def test_not_capture_console_log_messages(page):
    monitor = ConsoleMonitor(page)
    await page.set_content('<html><body><script>console.log("This should not be captured");</script></body></html>')
    await page.wait_for_timeout(500)
    assert len(monitor.getErrors()) == 0


@pytest.mark.asyncio
async def test_capture_page_errors(page):
    monitor = ConsoleMonitor(page)
    await page.set_content('<html><body><script>throw new Error("Uncaught exception");</script></body></html>')
    await page.wait_for_timeout(500)
    errors = monitor.getErrors()
    assert errors
    pageError = next((e for e in errors if "Uncaught exception" in e["message"]), None)
    assert pageError and pageError["type"] == "error"


@pytest.mark.asyncio
async def test_clear_errors_after_retrieval(page):
    monitor = ConsoleMonitor(page)
    await page.set_content('<html><body><script>console.error("Error 1");</script></body></html>')
    await page.wait_for_timeout(500)
    assert monitor.getErrors()
    assert len(monitor.getErrors()) == 0


@pytest.mark.asyncio
async def test_peek_errors_without_clearing(page):
    monitor = ConsoleMonitor(page)
    await page.set_content('<html><body><script>console.error("Error for peek");</script></body></html>')
    await page.wait_for_timeout(500)
    peeked = monitor.peekErrors()
    assert peeked and len(monitor.peekErrors()) == len(peeked)


@pytest.mark.asyncio
async def test_handle_multiple_errors(page):
    monitor = ConsoleMonitor(page)
    await page.set_content('<html><body><script>console.error("Error 1"); console.warn("Warning 1"); console.error("Error 2");</script></body></html>')
    await page.wait_for_timeout(500)
    assert len(monitor.getErrors()) == 3
