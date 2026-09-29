"""Port of src/mcp/tools/definitions.ts."""
import json

_DATA = json.loads('{"tools":[{"name":"run_exploratory_test","description":"Start an exploratory testing session to discover and test multiple pages","inputSchema":{"type":"object","properties":{"baseUrl":{"type":"string","description":"Base URL of the application to test"},"maxSteps":{"type":"number","description":"Maximum number of exploration steps (default: 50)","default":50},"mode":{"type":"string","enum":["autonomous","guided"],"description":"Testing mode: autonomous or guided","default":"autonomous"},"sessionId":{"type":"string","description":"Optional session ID to resume existing session"},"authRequired":{"type":"boolean","description":"Whether authentication is required to access the application","default":false},"authEmail":{"type":"string","description":"Email / username for authentication"},"authPassword":{"type":"string","description":"Password for authentication"},"authAppIdentifier":{"type":"string","description":"App identifier to store/retrieve saved credentials (default: \'mcp-test\')","default":"mcp-test"}},"required":["baseUrl"]}},{"name":"run_single_page_test","description":"Run comprehensive testing on a single page using plan-execute approach","inputSchema":{"type":"object","properties":{"targetUrl":{"type":"string","description":"URL of the page to test"},"strategy":{"type":"string","enum":["comprehensive","critical-path","edge-cases"],"description":"Testing strategy to use","default":"comprehensive"},"maxTestCases":{"type":"number","description":"Maximum number of test cases to execute","default":20},"sessionId":{"type":"string","description":"Optional session ID to resume"},"authRequired":{"type":"boolean","description":"Whether authentication is required to access the application","default":false},"authEmail":{"type":"string","description":"Email / username for authentication"},"authPassword":{"type":"string","description":"Password for authentication"},"authAppIdentifier":{"type":"string","description":"App identifier to store/retrieve saved credentials (default: \'mcp-test\')","default":"mcp-test"}},"required":["targetUrl"]}},{"name":"get_test_status","description":"Get real-time status of a running test session","inputSchema":{"type":"object","properties":{"sessionId":{"type":"string","description":"Session ID of the test"}},"required":["sessionId"]}},{"name":"stop_test","description":"Stop a running test session and generate final report","inputSchema":{"type":"object","properties":{"sessionId":{"type":"string","description":"Session ID of the test to stop"}},"required":["sessionId"]}},{"name":"list_sessions","description":"List all test sessions with their status and metadata","inputSchema":{"type":"object","properties":{"status":{"type":"string","enum":["all","active","completed"],"description":"Filter sessions by status","default":"all"},"limit":{"type":"number","description":"Maximum number of sessions to return","default":10}}}}],"resources":[{"uri":"test-report://latest","name":"Latest Test Report","mimeType":"text/markdown","description":"The most recent test report generated"}],"prompts":[{"name":"test-login-page","description":"Comprehensive testing prompt for login pages","arguments":[{"name":"loginUrl","description":"URL of the login page","required":true}]},{"name":"test-checkout-flow","description":"E-commerce checkout flow testing prompt","arguments":[{"name":"checkoutUrl","description":"URL of the checkout page","required":true}]}]}')
TOOL_DEFINITIONS = _DATA["tools"]
RESOURCE_DEFINITIONS = _DATA["resources"]
PROMPT_DEFINITIONS = _DATA["prompts"]

_DESCRIPTIONS = {
    "Start an exploratory testing session to discover and test multiple pages": "开始探索性测试，发现并测试多个页面",
    "Base URL of the application to test": "待测试网站的起始地址",
    "Maximum number of exploration steps (default: 50)": "最多探索步数（默认 50）",
    "Testing mode: autonomous or guided": "测试模式：自主或引导",
    "Optional session ID to resume existing session": "可选的会话 ID，用于继续已有会话",
    "Whether authentication is required to access the application": "访问网站是否需要登录",
    "Email / username for authentication": "登录邮箱或用户名",
    "Password for authentication": "登录密码",
    "App identifier to store/retrieve saved credentials (default: 'mcp-test')": "保存或读取凭据的应用标识（默认 mcp-test）",
    "Run comprehensive testing on a single page using plan-execute approach": "规划并执行单个页面的完整测试",
    "URL of the page to test": "待测试页面地址",
    "Testing strategy to use": "测试策略",
    "Maximum number of test cases to execute": "最多执行的测试用例数",
    "Optional session ID to resume": "可选的会话 ID，用于继续测试",
    "Get real-time status of a running test session": "获取测试会话的实时状态",
    "Session ID of the test": "测试会话 ID",
    "Stop a running test session and generate final report": "停止测试会话并生成最终报告",
    "Session ID of the test to stop": "要停止的测试会话 ID",
    "List all test sessions with their status and metadata": "列出测试会话及其状态和信息",
    "Filter sessions by status": "按状态筛选会话",
    "Maximum number of sessions to return": "最多返回的会话数",
    "The most recent test report generated": "最近生成的测试报告",
    "Comprehensive testing prompt for login pages": "登录页面完整测试提示词",
    "URL of the login page": "登录页面地址",
    "E-commerce checkout flow testing prompt": "电商结账流程测试提示词",
    "URL of the checkout page": "结账页面地址",
}

for _group in _DATA.values():
    for _item in _group:
        if "description" in _item:
            _item["description"] = _DESCRIPTIONS.get(_item["description"], _item["description"])
        for _property in _item.get("inputSchema", {}).get("properties", {}).values():
            if "description" in _property:
                _property["description"] = _DESCRIPTIONS.get(_property["description"], _property["description"])
        for _argument in _item.get("arguments", []):
            if "description" in _argument:
                _argument["description"] = _DESCRIPTIONS.get(_argument["description"], _argument["description"])

RESOURCE_DEFINITIONS[0]["name"] = "最新测试报告"
