"""LLM configuration and client creation utilities."""

from typing import Dict, Any
from autogen_core.models import ModelInfo
from autogen_ext.models.openai import OpenAIChatCompletionClient
from loguru import logger
from openai.types.shared_params import ResponseFormatJSONObject

def get_model_info(provider: str) -> ModelInfo:
    """获取不同供应商的模型能力信息。
    
    Args:
        provider: 供应商标识，如 'ds' 代表 DeepSeek
        
    Returns:
        ModelInfo: 模型能力配置
    """
    MODEL_CAPABILITIES = {
        "ds": ModelInfo(
            vision=False,
            function_calling=True,
            json_output=True,
            family="deepseek",
            structured_output=True,
        ),
        # 其他供应商的配置...
    }
    
    if provider not in MODEL_CAPABILITIES:
        raise ValueError(f"Unknown provider: {provider}. Available providers: {list(MODEL_CAPABILITIES.keys())}")
    
    return MODEL_CAPABILITIES[provider]

def create_completion_client(provider: str, config: Dict[str, Any], structured_output: bool = True) -> OpenAIChatCompletionClient:
    model_info = get_model_info(provider)
    model_info["structured_output"] = structured_output
    logger.info(f"Creating completion client for provider '{provider}' with model_info: {model_info}")
    return OpenAIChatCompletionClient(**config, model_info=model_info)

def create_unstructured_completion_client(provider: str, config: Dict[str, Any]) -> OpenAIChatCompletionClient:
    """创建不强制使用结构化输出的 LLM 客户端。
    
    Args:
        provider: 供应商标识，如 'ds' 代表 DeepSeek
        config: 基础配置（model, api_key, base_url 等）
        
    Returns:
        OpenAIChatCompletionClient: 配置好的非结构化输出 LLM 客户端
    """
    model_info = get_model_info(provider)
    model_info["structured_output"] = False  # 覆盖结构化输出设置
    logger.info(f"Creating unstructured completion client for provider '{provider}' with model_info: {model_info}")
    return OpenAIChatCompletionClient(**config, model_info=model_info) 