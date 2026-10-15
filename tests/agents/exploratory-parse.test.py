"""结构化输出三层的单元测试：JSON mode 绑定、解析容忍、修复回路（无 LLM、无浏览器）。"""
import pytest

from langchain_openai import ChatOpenAI

from src.agents.exploratory import ExploratoryAgent, _bind_json_mode, parse_action_json


class TestJsonModeBinding:
    def test_binds_response_format_for_chatopenai(self):
        model = ChatOpenAI(model="probe", api_key="none")
        bound = _bind_json_mode(model)
        assert bound is not model
        assert bound.kwargs["response_format"] == {"type": "json_object"}

    def test_non_openai_model_passes_through(self):
        class FakeModel:
            pass

        fake = FakeModel()
        assert _bind_json_mode(fake) is fake


class TestParseActionJson:
    def test_plain_json(self):
        assert parse_action_json('{"action": "finish", "reason": "完成"}')["action"] == "finish"

    def test_json_in_code_fence(self):
        content = '好的\n```json\n{"action": "navigate", "reason": "去首页"}\n```'
        assert parse_action_json(content)["action"] == "navigate"

    def test_json_embedded_in_prose(self):
        # Review Focus #1：prose 夹杂 JSON 必须能提取（json_object 下罕见，解析层仍兜底）
        content = '我决定下一步：{"action": "click", "reason": "点加购"}，请执行。'
        assert parse_action_json(content)["action"] == "click"

    def test_garbage_raises(self):
        with pytest.raises(ValueError):
            parse_action_json("完全没有 JSON 的输出")

    def test_unclosed_object_raises(self):
        with pytest.raises(ValueError):
            parse_action_json('{"action": "finish", "reason": "未闭合')

    def test_non_object_raises(self):
        with pytest.raises(ValueError):
            parse_action_json("[1, 2, 3]")


class TestRepairLoop:
    @pytest.mark.asyncio
    async def test_repair_parses_fixed_output(self):
        class FixedModel:
            async def ainvoke(self, messages):
                return type("R", (), {"content": '{"action": "finish", "reason": "ok"}'})()

        agent = ExploratoryAgent.__new__(ExploratoryAgent)
        agent.decision_model = FixedModel()
        fixed = await agent._repair_action_json("坏输出", "JSON 对象未闭合")
        assert fixed == {"action": "finish", "reason": "ok"}

    @pytest.mark.asyncio
    async def test_repair_returns_none_on_model_error(self):
        # Review Focus #2：修复回路自身失败必须降级为 None，不抛出
        class BoomModel:
            async def ainvoke(self, messages):
                raise RuntimeError("服务不可用")

        agent = ExploratoryAgent.__new__(ExploratoryAgent)
        agent.decision_model = BoomModel()
        assert await agent._repair_action_json("{}", "x") is None

    @pytest.mark.asyncio
    async def test_repair_returns_none_on_still_invalid_output(self):
        class StillBadModel:
            async def ainvoke(self, messages):
                return type("R", (), {"content": "还是不是 JSON"})()

        agent = ExploratoryAgent.__new__(ExploratoryAgent)
        agent.decision_model = StillBadModel()
        assert await agent._repair_action_json("{}", "x") is None
