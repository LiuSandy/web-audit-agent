"""LLM model factory for Gemini and OpenAI-compatible providers."""

import os

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_openai import ChatOpenAI

from src.utils.logger import createLogger

logger = createLogger("models")
load_dotenv(override=False)


def createGeminiModel(config=None):
    config = config or {}
    apiKey = config.get("apiKey") or os.environ.get("GOOGLE_AI_STUDIO_API_KEY")
    modelName = config.get("modelName") or os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"
    logger.info(f"正在创建 Gemini 模型：{modelName}")
    if not apiKey:
        logger.error("环境或配置中缺少 GOOGLE_AI_STUDIO_API_KEY")
        raise ValueError("环境或配置中缺少 GOOGLE_AI_STUDIO_API_KEY")
    try:
        kwargs = {"model": modelName, "google_api_key": apiKey,
                  "temperature": config.get("temperature", 0.7)}
        if config.get("maxTokens") is not None:
            kwargs["max_output_tokens"] = config["maxTokens"]
        model = ChatGoogleGenerativeAI(**kwargs)
        logger.success(f"Gemini 模型创建成功：{modelName}")
        return model
    except Exception as error:
        logger.error(f"创建 Gemini 模型失败：{error}")
        raise


def createOpenAIModel(config=None):
    config = config or {}
    apiKey = config.get("apiKey") or os.environ.get("OPEN_AI_API_KEY")
    modelName = config.get("modelName") or os.environ.get("OPEN_AI_MODEL") or "gpt-3.5-turbo"
    baseUrl = config.get("baseUrl") or os.environ.get("OPEN_AI_API_URL")
    logger.info(f"正在创建 OpenAI 兼容模型：{modelName}，地址：{baseUrl or '默认地址'}")
    if not apiKey:
        logger.warn("未找到 OPEN_AI_API_KEY；部分服务商可能需要此密钥")
    kwargs = {"model": modelName, "api_key": apiKey or "not-needed",
              "temperature": config.get("temperature", 0.7)}
    if config.get("maxTokens") is not None:
        kwargs["max_tokens"] = config["maxTokens"]
    if baseUrl:
        kwargs["base_url"] = baseUrl
    return ChatOpenAI(**kwargs)


def getDefaultModel():
    logger.info("正在获取默认模型……")
    if os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
        logger.info("已检测到 GOOGLE_AI_STUDIO_API_KEY，使用 Gemini 模型")
        return createGeminiModel()
    if os.environ.get("OPEN_AI_API_KEY"):
        logger.info("已检测到 OPEN_AI_API_KEY，使用 OpenAI 兼容模型")
        return createOpenAIModel()
    if os.environ.get("OPEN_AI_API_URL"):
        logger.info("已检测到 OPEN_AI_API_URL，使用 OpenAI 兼容模型")
        return createOpenAIModel()
    raise ValueError("未找到可用的模型服务。请在 .env 中设置 GOOGLE_AI_STUDIO_API_KEY 或 OPEN_AI_API_KEY，也可设置 OPEN_AI_API_URL")


def getDefaultModelName():
    if os.environ.get("GOOGLE_AI_STUDIO_API_KEY"):
        return os.environ.get("GEMINI_MODEL") or "gemini-2.5-flash-lite"
    if os.environ.get("OPEN_AI_API_KEY") or os.environ.get("OPEN_AI_API_URL"):
        return os.environ.get("OPEN_AI_MODEL") or "gpt-3.5-turbo"
    return "unknown"
