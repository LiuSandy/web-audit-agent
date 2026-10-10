"""Gemini 模型工厂的请求级配置约束：google-genai 的自动函数调用（AFC）由 LangChain 接管，请求层必须关闭。"""
from google.genai import types as gtypes
from langchain_core.messages import HumanMessage

from src.services.llm import create_gemini_model


class _RecordingModels:
    def __init__(self):
        self.requests = []

    def generate_content(self, **kwargs):
        self.requests.append(kwargs)
        return gtypes.GenerateContentResponse(
            candidates=[gtypes.Candidate(content=gtypes.Content(role="model", parts=[gtypes.Part(text="ok")]))]
        )


class _RecordingClient:
    def __init__(self):
        self.models = _RecordingModels()


def _gemini_with_recording_client():
    model = create_gemini_model({"apiKey": "test-key", "modelName": "gemini-test"})
    client = _RecordingClient()
    model.client = client
    return model, client.models


def test_gemini_request_disables_sdk_automatic_function_calling():
    model, models = _gemini_with_recording_client()
    model._generate([HumanMessage(content="ok")])
    afc = models.requests[0]["config"].automatic_function_calling
    assert afc is not None and afc.disable is True


def test_gemini_per_call_automatic_function_calling_wins():
    model, models = _gemini_with_recording_client()
    model._generate([HumanMessage(content="ok")], automatic_function_calling={"disable": False})
    afc = models.requests[0]["config"].automatic_function_calling
    assert afc is not None and afc.disable is False
