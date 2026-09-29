"""Exercise the generated Python test path without an external model or website."""

import importlib
from pathlib import Path

import pytest


GeneratorClass = importlib.import_module("src.services.test-generator").TestGenerator
ExecutorClass = importlib.import_module("src.services.test-executor").TestExecutor
runner = importlib.import_module("src.cli.run-tests")


class FixedModel:
    def __init__(self, content):
        self.content = content

    async def ainvoke(self, messages):
        assert "pytest" in messages[0].content
        assert "playwright.sync_api" in messages[1].content
        return type("Response", (), {"content": self.content})()


@pytest.mark.asyncio
async def test_generated_python_test_runs_with_executor_and_cli(tmp_path, monkeypatch):
    html = tmp_path / "index.html"
    html.write_text("<h1>WebAudit</h1>", encoding="utf-8")
    code = f'''import pytest
from playwright.sync_api import expect, sync_playwright

@pytest.fixture
def page():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context()
        try:
            yield context.new_page()
        finally:
            context.close()
            browser.close()

def test_home_page(page):
    """The page displays its heading."""
    page.goto({html.as_uri()!r})
    expect(page.locator("h1")).to_have_text("WebAudit")
'''
    generator = GeneratorClass(FixedModel(f"```python\n{code}\n```"), {
        "outputDir": "generated-tests", "includeE2E": True,
    })
    monkeypatch.chdir(tmp_path)
    findings = [{"type": "functional_bug", "description": "Missing heading", "url": html.as_uri()}]
    tests = await generator.generateTestsFromFindings(findings, {}, html.as_uri())
    assert len(tests) == 1
    assert tests[0]["name"] == "test_home_page"
    assert tests[0]["description"] == "The page displays its heading."
    assert tests[0]["filePath"].endswith("_spec.py")

    executor = ExecutorClass({"retryCount": 0})
    assert await executor.saveTests(tests) == [tests[0]["filePath"]]
    assert Path(tests[0]["filePath"]).is_file()
    results = await executor.executeTests(tests)
    assert results[0]["success"], results[0]["output"]
    runner.runAllTests()


def test_generator_rejects_non_python_or_uncollectable_output():
    generator = GeneratorClass(None, {"outputDir": "generated-tests", "includeE2E": True})
    assert generator.parseTestResponse("```typescript\ntest('old', () => {});\n```", "general") == []
    assert generator.parseTestResponse("```python\nprint('no test')\n```", "general") == []
