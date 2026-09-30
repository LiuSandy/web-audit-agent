"""Tests for form validation error detection."""

import math

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from src.tools.validation_errors import find_validation_errors


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


@pytest.mark.asyncio
async def test_detect_role_alert(page):
    await page.set_content('<html><body><div role="alert">This is an error message</div></body></html>')
    findings = await find_validation_errors(page)
    assert len(findings) == 1 and findings[0]["message"] == "This is an error message"


@pytest.mark.asyncio
async def test_detect_error_class(page):
    await page.set_content('<html><body><div class="error">Form validation failed</div></body></html>')
    findings = await find_validation_errors(page)
    assert len(findings) == 1 and findings[0]["message"] == "Form validation failed"


@pytest.mark.asyncio
async def test_detect_alert_danger_class(page):
    await page.set_content('<html><body><div class="alert alert-danger">Danger alert</div></body></html>')
    findings = await find_validation_errors(page)
    assert len(findings) == 1 and findings[0]["message"] == "Danger alert"


@pytest.mark.asyncio
async def test_detect_invalid_form_inputs(page):
    await page.set_content('<html><body><form><input type="email" aria-invalid="true" aria-describedby="email-error" /><span id="email-error" class="error">Invalid email address</span></form></body></html>')
    findings = await find_validation_errors(page)
    assert findings and any("Invalid email" in f["message"] for f in findings)


@pytest.mark.asyncio
async def test_ignore_hidden_error_messages(page):
    await page.set_content('<html><body><div class="error" style="display: none;">Hidden error</div><div class="error">Visible error</div></body></html>')
    findings = await find_validation_errors(page)
    assert len(findings) == 1 and findings[0]["message"] == "Visible error"


@pytest.mark.asyncio
async def test_ignore_empty_error_messages(page):
    await page.set_content('<html><body><div class="error"></div><div class="error">   </div><div class="error">Real error</div></body></html>')
    findings = await find_validation_errors(page)
    assert len(findings) == 1 and findings[0]["message"] == "Real error"


@pytest.mark.asyncio
async def test_return_structured_findings(page):
    await page.set_content('<html><body><div id="error-msg" class="error">Test error</div></body></html>')
    findings = await find_validation_errors(page)
    assert len(findings) == 1
    for key in ("message", "selector", "location"):
        assert key in findings[0]
    assert "x" in findings[0]["location"] and "y" in findings[0]["location"]
    assert "error-msg" in findings[0]["selector"]


@pytest.mark.asyncio
async def test_handle_multiple_validation_errors(page):
    await page.set_content('<html><body><div class="error">Error 1</div><div role="alert">Error 2</div><div class="validation-error">Error 3</div></body></html>')
    assert len(await find_validation_errors(page)) == 3


@pytest.mark.asyncio
async def test_deduplicate_similar_errors_at_same_location(page):
    await page.set_content('''<html><body>
        <div class="error" style="position: absolute; top: 10px; left: 10px;">Same error</div>
        <div class="validation-error" style="position: absolute; top: 12px; left: 11px;">Same error</div>
        <div class="error" style="position: absolute; top: 100px; left: 100px;">Same error</div>
        <div class="error" style="position: absolute; top: 10px; left: 10px;">Different error</div>
        </body></html>''')
    findings = await find_validation_errors(page)
    assert len(findings) == 3
    messages = [f["message"] for f in findings]
    assert messages.count("Same error") == 2 and messages.count("Different error") == 1
    same = [f for f in findings if f["message"] == "Same error"]
    distance = math.hypot(same[0]["location"]["x"] - same[1]["location"]["x"],
                          same[0]["location"]["y"] - same[1]["location"]["y"])
    assert distance > 5


@pytest.mark.asyncio
async def test_detect_tailwind_error_classes(page):
    await page.set_content('<html><body><div class="text-red-500">Tailwind error message</div></body></html>')
    findings = await find_validation_errors(page)
    assert len(findings) == 1 and findings[0]["message"] == "Tailwind error message"


@pytest.mark.asyncio
async def test_handle_complex_form_validation(page):
    await page.set_content('''<html><body><form>
      <div class="form-group"><label for="username">Username</label><input type="text" id="username" aria-invalid="true" /><div class="invalid-feedback">Username is required</div></div>
      <div class="form-group"><label for="email">Email</label><input type="email" id="email" aria-invalid="true" /><div class="field-error">Invalid email format</div></div>
      </form></body></html>''')
    findings = await find_validation_errors(page)
    assert len(findings) >= 2
    messages = [f["message"] for f in findings]
    assert any("Username" in m for m in messages)
    assert any("email" in m for m in messages)
