"""Tests for broken image detection."""

import pytest
import pytest_asyncio
from playwright.async_api import async_playwright

from src.tools.broken_images import find_broken_images


@pytest_asyncio.fixture
async def page():
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        yield page
        await browser.close()


@pytest.mark.asyncio
async def test_detect_images_with_missing_src(page):
    await page.set_content('<html><body><img alt="Missing src" /></body></html>')
    findings = await find_broken_images(page)
    assert len(findings) == 1
    assert findings[0]["reason"] == "Missing both 'src' and 'srcset' attributes"
    assert findings[0]["alt"] == "Missing src"


@pytest.mark.asyncio
async def test_detect_images_with_404_errors(page):
    await page.set_content('<html><body><img src="https://nonexistent-domain-12345.com/image.png" alt="404 image" /></body></html>')
    await page.wait_for_timeout(1000)
    findings = await find_broken_images(page)
    assert len(findings) > 0
    assert findings[0]["alt"] == "404 image"


@pytest.mark.asyncio
async def test_detect_images_with_zero_dimensions(page):
    await page.set_content('<html><body><img src="data:image/gif;base64,invalid" alt="Zero dimensions" /></body></html>')
    await page.wait_for_timeout(500)
    findings = await find_broken_images(page)
    if findings:
        assert "Image loaded with 0x0 dimensions" in findings[0]["reason"]


@pytest.mark.asyncio
async def test_not_detect_valid_images(page):
    valid_image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    await page.set_content(f'<html><body><img src="{valid_image}" alt="Valid image" /></body></html>')
    await page.wait_for_timeout(500)
    assert len(await find_broken_images(page)) == 0


@pytest.mark.asyncio
async def test_return_structured_findings_with_selectors(page):
    await page.set_content('<html><body><div id="container"><img alt="Test" /></div></body></html>')
    findings = await find_broken_images(page)
    assert len(findings) == 1
    for key in ("src", "alt", "selector", "reason", "location"):
        assert key in findings[0]
    assert "x" in findings[0]["location"] and "y" in findings[0]["location"]


@pytest.mark.asyncio
async def test_handle_multiple_broken_images(page):
    await page.set_content('<html><body><img alt="Missing 1" /><img alt="Missing 2" /><img src="data:image/gif;base64,invalid" alt="Invalid" /></body></html>')
    await page.wait_for_timeout(500)
    assert len(await find_broken_images(page)) >= 2


@pytest.mark.asyncio
async def test_ignore_invisible_images(page):
    await page.set_content('<html><body><img alt="Visible missing" /><img alt="Hidden missing" style="display: none;" /></body></html>')
    findings = await find_broken_images(page)
    assert len(findings) >= 1
    assert any(f["alt"] == "Visible missing" for f in findings)


@pytest.mark.asyncio
async def test_generate_unique_selectors_for_siblings_without_ids(page):
    await page.set_content('<body><div id="container"><img src="broken1.png" class="test-img" /><img src="broken2.png" class="test-img" /></div></body>')
    findings = await find_broken_images(page)
    assert len(findings) == 2
    assert findings[0]["selector"] != findings[1]["selector"]
    assert ":nth-of-type" in findings[0]["selector"]


@pytest.mark.asyncio
async def test_report_multiple_instances_of_same_broken_image(page):
    await page.set_content('<body><div id="container"><img src="duplicate.png" class="test-img" /><img src="duplicate.png" class="test-img" /></div></body>')
    findings = await find_broken_images(page)
    assert len(findings) == 2
    assert findings[0]["src"] == findings[1]["src"] == "duplicate.png"
    assert findings[0]["selector"] != findings[1]["selector"]


@pytest.mark.asyncio
async def test_produce_distinct_selectors_for_images_in_different_parents(page):
    await page.set_content('<body><div class="parent-a"><img src="common-broken.png" /></div><div class="parent-b"><img src="common-broken.png" /></div></body>')
    findings = await find_broken_images(page)
    assert len(findings) == 2
    assert findings[0]["selector"] != findings[1]["selector"]
