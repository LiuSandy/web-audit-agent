"""Check Chinese user-facing output without changing machine-readable values."""

import json

import pytest

from src.services.test_executor import TestExecutor as _TestExecutor
from src.utils.report import generate_report


@pytest.mark.asyncio
async def test_exploration_report_uses_chinese_labels(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "reports").mkdir()
    finding = {"type": "console_error", "severity": "medium",
               "url": "https://example.com", "description": "控制台错误：示例",
               "selector": "#submit", "occurrences": ["https://example.com/next"]}
    path = await generate_report([finding], ["https://example.com"], "test", "https://example.com")
    content = (tmp_path / path).read_text(encoding="utf-8")
    assert "# 探索性测试报告" in content
    assert "发现问题：1" in content
    assert "[控制台错误] [中]" in content
    assert "**其他出现页面**：另有 1 个页面" in content
    assert "**问题描述**：控制台错误：示例" in content
    assert finding["type"] == "console_error"


def test_execution_report_uses_chinese_labels():
    test = {"name": "test_example", "testType": "e2e", "priority": "high",
            "filePath": "generated-tests/example_spec.py"}
    result = {"test": test, "success": False, "error": "断言失败", "executionTime": 12}
    content = _TestExecutor().generate_test_report([result])
    assert "# 测试执行报告" in content
    assert "## 失败的测试" in content
    assert "**优先级：** 高" in content
    assert "**原始错误：** 断言失败" in content
    assert test["priority"] == "high"
    assert "通过率：0.0%" in _TestExecutor().generate_test_report([])


def test_execution_report_prefers_chinese_description_over_python_identifier():
    test = {"name": "test_login_with_invalid_password", "description": "错误密码应显示提示",
            "testType": "e2e", "priority": "medium", "filePath": "generated-tests/login_spec.py"}
    content = _TestExecutor().generate_test_report([{"test": test, "success": True, "executionTime": 10}])
    assert "**错误密码应显示提示**" in content
    assert "测试标识：`test_login_with_invalid_password`" in content


@pytest.mark.asyncio
async def test_single_page_findings_have_chinese_context_and_raw_details(monkeypatch):
    import src.agents.single_page as module
    agent = module.SinglePageTestingAgent.__new__(module.SinglePageTestingAgent)
    agent.page = type("Page", (), {"url": "https://example.com", "is_closed": lambda self: False,
        "evaluate": lambda self, _script: _async_value(False)})()
    agent.console_monitor = type("Monitor", (), {"get_errors": lambda self: [{"message": "Script error"}]})()
    agent.network_monitor = type("Monitor", (), {"get_errors": lambda self: [{"statusText": "Not Found"}]})()
    monkeypatch.setattr(module, "find_broken_images", lambda _page: _async_value([]))
    findings = await agent.validate_outcome({"name": "示例测试"})
    assert findings[0]["description"] == "控制台错误：Script error"
    assert findings[0]["metadata"]["rawMessage"] == "Script error"
    assert findings[1]["description"] == "网络请求异常：Not Found"


async def _async_value(value):
    return value


def test_mcp_description_is_chinese_without_changing_tool_name():
    from src.mcp.tools.definitions import TOOL_DEFINITIONS as definitions
    assert definitions[0]["name"] == "run_exploratory_test"
    assert definitions[0]["description"] == "开始探索性测试，发现并测试多个页面"
    assert definitions[0]["inputSchema"]["properties"]["baseUrl"]["description"] == "待测试网站的起始地址"


@pytest.mark.asyncio
async def test_single_page_mcp_status_has_chinese_display_text(monkeypatch):
    import src.mcp.tools.status as status_module
    state = {"status": "executing", "currentAction": "正在测试页面", "startTime": 1000,
             "testPlan": {"totalTests": 2}, "results": [{"findings": [
                 {"type": "console_error", "description": "控制台错误：示例",
                  "severity": "medium", "url": "https://example.com"}]}]}
    monkeypatch.setattr(status_module, "_active_tests", lambda: {"sp-1": {"state": state}})
    monkeypatch.setattr(status_module, "_get_agent_instance", lambda _session_id: None)
    response = await status_module.handle_get_test_status({"sessionId": "sp-1"})
    result = json.loads(response["content"][0]["text"])
    assert result["status"] == "executing"
    assert result["statusText"] == "执行中"
    assert result["progress"] == 50
    assert result["recentFindings"][0]["description"] == "控制台错误：示例"
