"""CLI 测试共用假件：不出网、不开浏览器、不碰 LLM。"""
import asyncio

STEP_A = {"action": "navigate", "reason": "第一步原因", "completed": False,
          "stats": {"currentUrl": "https://x/1", "queueLength": 2, "visitedCount": 1, "findingsCount": 0}}
STEP_B = {**STEP_A, "reason": "最后一步原因", "completed": True,
          "stats": {"currentUrl": "https://x/2", "queueLength": 0, "visitedCount": 2, "findingsCount": 1}}


class FakeAgent:
    """ExploratoryAgent 的脚本化替身，实现其六个公开接口（spec §10）。"""

    def __init__(self, steps=None, error=None, cancelled_during=None):
        self.steps = list(steps) if steps is not None else [STEP_B]
        self.error = error                      # 非 None 时第 1 步抛出
        self.cancelled_during = cancelled_during  # 指定第几步抛 CancelledError
        self.started = False
        self.stopped = False
        self.step_calls = []
        self.generated = [{"name": "test_demo", "priority": "high", "testType": "smoke",
                           "filePath": "generated-tests/demo_spec.py"}]
        self.findings = [{"type": "console_error", "severity": "medium", "url": "https://x/2",
                          "description": "控制台错误：示例", "selector": "", "occurrences": 1}]

    async def start(self):
        self.started = True

    async def step(self, guidance=None):
        self.step_calls.append(guidance)
        index = len(self.step_calls)
        if self.cancelled_during == index:
            raise asyncio.CancelledError()
        if self.error is not None and index == 1:
            raise self.error
        return self.steps[min(index - 1, len(self.steps) - 1)]

    async def stop(self):
        self.stopped = True

    def get_findings(self):
        return self.findings

    def get_visited_urls(self):
        return {"https://x/1", "https://x/2"}

    async def generate_tests(self):
        return self.generated
