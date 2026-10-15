"""模型调用异常消息格式化的单元测试（无 LLM、无浏览器）。"""
import asyncio

from src.agents.exploratory import describe_model_error


def test_timeout_error_gets_explicit_message():
    # asyncio.wait_for 抛出的 TimeoutError str 为空，必须显形为带毫秒数的消息
    message = describe_model_error(asyncio.TimeoutError(), 30000)
    assert "30000ms" in message
    assert "超时" in message


def test_empty_str_error_falls_back_to_type_name():
    class SilentError(Exception):
        def __str__(self):
            return ""

    assert describe_model_error(SilentError(), 30000) == "SilentError"


def test_normal_message_passes_through():
    assert describe_model_error(ValueError("429 too many requests"), 30000) == "429 too many requests"
