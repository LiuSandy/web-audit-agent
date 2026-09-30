"""LLM model factory for Gemini and OpenAI-compatible providers."""

import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from src.utils.logger import create_logger

logger = create_logger("models")
load_dotenv(override=False)


def create_gemini_model(config=None):
    config = config or {}
    api_key = config.get("apiKey") or os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
    model_name = config.get("modelName") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"
    logger.info(f"正在创建 Gemini 模型：{model_name}")
    if not api_key:
        logger.error("环境或配置中缺少 GOOGLE_AI_STUDIO_API_KEY")
        raise ValueError("环境或配置中缺少 GOOGLE_AI_STUDIO_API_KEY")
    try:
        kwargs = {"model": model_name, "google_api_key": api_key,
                  "temperature": config.get("temperature", 0.7)}
        if config.get("maxTokens") is not None:
            kwargs["max_output_tokens"] = config["maxTokens"]
        model = ChatGoogleGenerativeAI(**kwargs)
        logger.success(f"Gemini 模型创建成功：{model_name}")
        return model
    except Exception as error:
        logger.error(f"创建 Gemini 模型失败：{error}")
        raise


def create_openai_model(config=None):
    config = config or {}
    api_key = config.get("apiKey") or os.environ.get("OPEN_AI_API_KEY")
    model_name = config.get("modelName") or os.environ.get("OPEN_AI_MODEL") or "gpt-3.5-turbo"
    base_url = config.get("baseUrl") or os.environ.get("OPEN_AI_API_URL")
    logger.info(f"正在创建 OpenAI 兼容模型：{model_name}，地址：{base_url or '默认地址'}")
    if not api_key:
        logger.warn("未找到 OPEN_AI_API_KEY；部分服务商可能需要此密钥")
    kwargs = {"model": model_name, "api_key": api_key or "not-needed",
              "temperature": config.get("temperature", 0.7)}
    if config.get("maxTokens") is not None:
        kwargs["max_tokens"] = config["maxTokens"]
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


def get_default_model():
    logger.info("正在获取默认模型……")
    if os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
        logger.info("已检测到 GOOGLE_AI_STUDIO_API_KEY，使用 Gemini 模型")
        return create_gemini_model()
    if os.environ.get("OPEN_AI_API_KEY"):
        logger.info("已检测到 OPEN_AI_API_KEY，使用 OpenAI 兼容模型")
        return create_openai_model()
    if os.environ.get("OPEN_AI_API_URL"):
        logger.info("已检测到 OPEN_AI_API_URL，使用 OpenAI 兼容模型")
        return create_openai_model()
    raise ValueError("未找到可用的模型服务。请在 .env 中设置 GOOGLE_AI_STUDIO_API_KEY 或 OPEN_AI_API_KEY，也可设置 OPEN_AI_API_URL")


def get_default_model_name():
    if os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
        return os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"
    if os.environ.get("OPEN_AI_API_KEY") or os.environ.get("OPEN_AI_API_URL"):
        return os.environ.get("OPEN_AI_MODEL") or "gpt-3.5-turbo"
    return "unknown"
