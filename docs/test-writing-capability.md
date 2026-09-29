# Python 端到端测试生成

WebAudit 根据探索阶段记录的问题生成浏览器测试。生成器、保存的测试、运行器和执行报告均使用 Python；测试框架为 pytest 与 Python Playwright。

## 处理流程

1. `TestGenerator.generateTestsFromFindings()` 按问题类别分组，并请求所配置的模型生成 Python 测试代码。
2. 生成器只接受语法有效且包含顶层 `test_` 函数的代码。文件保存为 `generated-tests/<category>/e2e-<date>-<number>_spec.py`。
3. `TestExecutor.saveTests()` 写入文件。除“仅生成”模式外，`executeTests()` 使用当前 Python 解释器和 pytest 执行测试。
4. `reports/` 中的中文执行报告记录通过、失败、耗时、文件路径和原始错误。

命令行支持仅生成、顺序执行和并行执行。`testMaxConcurrency`、`testTimeout` 与 `testRetryCount` 控制并发、超时和重试。每个生成的测试文件应自带浏览器和页面 fixture，确保可以独立运行。

## 准备环境

~~~bash
uv sync
uv run python -m playwright install chromium
cp .env.example .env
uv run python -m src.index
~~~

在 `.env` 中配置模型服务，详见项目 [README](../README.md)。

## 运行生成的测试

~~~bash
# 交互式运行器
uv run python -m src.cli.run-tests

# 运行全部生成的测试
uv run pytest generated-tests/

# 运行一个类别或文件
uv run pytest generated-tests/broken-images/
uv run pytest generated-tests/broken-images/e2e-2026-09-25-1_spec.py
~~~

`pyproject.toml` 配置了 `*.test.py` 和 `*_spec.py` 的发现规则。生成文件必须包含 `test_` 函数。函数名、URL、选择器等技术标识保持原值；用例说明和报告显示文字使用中文。

## 示例

~~~python
import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            yield browser
        finally:
            browser.close()


@pytest.fixture
def page(browser):
    context = browser.new_context()
    page = context.new_page()
    try:
        yield page
    finally:
        context.close()


def test_home_page_has_content(page):
    """首页正文应可见。"""
    page.goto("https://example.com")
    expect(page.locator("body")).to_be_visible()
~~~

浏览器 fixture 在文件中复用；每个测试使用新的 context 和 page，避免状态互相影响。
