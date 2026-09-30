"""Generate Python Playwright E2E tests from agent findings."""

import ast
import re
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage, SystemMessage

from src.utils.logger import create_logger

logger = create_logger("test-generator")


class TestGenerator:
    def __init__(self, model, config):
        self.model = model
        self.config = config

    async def generate_tests_from_findings(self, findings, state, base_url):
        logger.info(f"正在根据 {len(findings)} 条发现生成端到端测试")
        generated_tests = []
        grouped_findings = self.group_findings_by_type(findings)
        for category, category_findings in grouped_findings.items():
            if not category_findings:
                continue
            if self.config["includeE2E"]:
                e2e_tests = await self.generate_e2e_tests(category, category_findings, base_url)
                generated_tests.extend(e2e_tests)
        logger.info(f"已生成 {len(generated_tests)} 个端到端测试")
        return generated_tests

    def group_findings_by_type(self, findings):
        grouped = {}
        for finding in findings:
            category = self.categorize_finding(finding)
            grouped.setdefault(category, []).append(finding)
        return grouped

    def categorize_finding(self, finding):
        return {"broken_image": "broken-images", "console_error": "console-errors",
                "network_error": "network-errors", "validation_error": "validation-errors",
                "functional_bug": "functional"}.get(finding["type"], "general")

    async def generate_e2e_tests(self, category, findings, base_url):
        prompt = self.create_e2e_test_prompt(category, findings, base_url)
        try:
            response = await self.model.ainvoke([
                SystemMessage(content="你是测试自动化工程师。只生成使用 pytest 和 playwright.sync_api 的可执行 Python 端到端测试。保留 pytest 可发现的 test_ 函数名和 Python 标识符；测试说明、docstring 与面向用户的断言消息使用简体中文。只返回 Python 代码，不生成 JavaScript 或 TypeScript。"),
                HumanMessage(content=prompt)])
            return self.parse_test_response(str(response.content), category)
        except Exception as error:
            logger.error(f"为 {category} 生成端到端测试失败：", error)
            return []

    def create_e2e_test_prompt(self, category, findings, base_url):
        findings_text = "\n".join(f"- {f['description']}，页面：{f['url']}（选择器：{f.get('selector') or '无'}）" for f in findings)
        return f"""请为以下 {category} 类问题生成完整的端到端测试：

目标地址：{base_url}

问题：
{findings_text}

要求：
1. 只编写 Python，使用 pytest 和 playwright.sync_api。
2. 按需导入 pytest、sync_playwright 和 playwright.sync_api.expect。
3. 定义 pytest 可发现的顶层 test_ 函数；函数名保持有效的 Python 标识符。
4. 用 fixture 初始化和关闭浏览器，每个测试使用独立的 context 和 page。
5. 断言应验证问题已经修复，同时覆盖正常和异常输入。
6. 按需使用 page.goto()、page.locator()、expect(...).to_be_visible()、page.wait_for_timeout()；必要时使用 page.route() 模拟 API。
7. 不导入 JavaScript 包，也不调用外部测试运行器。
8. 测试 docstring、注释及面向用户的说明使用简体中文，不翻译网站原始文案和技术标识符。

只返回一个可执行的 Python 测试文件，fixture 结构参考：

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

def test_specific_issue(page):
    page.goto("{base_url}")
    expect(page.locator("body")).to_be_visible()
"""

    def parse_test_response(self, response, category):
        tests = []
        for index, test_content in enumerate(self.extract_test_blocks(response)):
            try:
                tree = ast.parse(test_content)
            except SyntaxError as error:
                logger.error(f"为 {category} 生成的测试不是有效的 Python 代码：", error)
                continue
            if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                       and node.name.startswith("test_") for node in tree.body):
                logger.warn(f"为 {category} 生成的测试缺少 pytest test_ 函数")
                continue
            tests.append({"name": self.generate_test_name(category, "e2e", index, test_content),
                          "description": self.extract_test_description(test_content),
                          "filePath": self.generate_file_path(category, "e2e", index),
                          "content": test_content, "testType": "e2e",
                          "priority": self.determine_priority(category, "e2e")})
        return tests

    def extract_test_blocks(self, response):
        matches = re.findall(r"```(?:python|py)?\s*\n([\s\S]*?)\n```", response, re.IGNORECASE)
        if matches:
            return [match.strip() for match in matches]
        return [response.strip()]

    def generate_test_name(self, category, test_type, index, content):
        match = re.search(r"(?:async\s+)?def\s+(test_\w+)\s*\(", content)
        return match.group(1) if match else f"{category}-{test_type}-test-{index + 1}"

    def generate_file_path(self, category, test_type, index):
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return f"{self.config['outputDir']}/{category}/{test_type}-{timestamp}-{index + 1}_spec.py"

    def extract_test_description(self, content):
        match = re.search(r'(?:async\s+)?def\s+test_\w+\s*\([^)]*\):\s*\n\s*[\"\']{3}(.+?)[\"\']{3}', content, re.DOTALL)
        return match.group(1).strip() if match else "根据代理发现的问题生成的测试"

    def determine_priority(self, category, test_type):
        if category in ("functional", "network-errors"):
            return "high"
        if test_type == "e2e":
            return "medium"
        return "low"
