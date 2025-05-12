from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field, ValidationError
from loguru import logger
import os
import json
import toml # Add toml import
from pathlib import Path
from autogen_ext.models.openai import OpenAIChatCompletionClient
from .llm_config import create_completion_client
from src.types.plan import PlanTemplate

# --- Pydantic 模型定义 ---

# 先定义基础和嵌套类型
class LLMConfig(BaseModel):
    model: Optional[str] = None
    temperature: Optional[float] = None
    # 可以根据需要添加其他 LLM 配置项
    class Config:
        extra = 'allow' # 允许额外字段

class GlobalSettings(BaseModel):
    default_llm_config: Optional[LLMConfig] = None
    shared_tools: Optional[List[str]] = None

class HandoffTarget(BaseModel):
    """Defines a handoff target for an agent."""
    target: str
    # description field removed as per user request

# 再定义依赖它们的 AgentConfig 和 TeamConfig
class AgentConfig(BaseModel):
    """Configuration for a single agent."""
    name: str
    prompt: Optional[str] = None
    llm_config: Optional[LLMConfig] = None
    sop_templates: Optional[Dict[str, Any]] = None
    judge_agent_llm_config: Optional[LLMConfig] = None
    expertise_area: Optional[str] = None
    eve_interface_config: Optional[Dict[str, Any]] = None
    actions: Optional[List[str]] = None
    handoffs: Optional[List[HandoffTarget]] = None
    assigned_tools: Optional[List[str]] = None

class TeamConfig(BaseModel):
    """Overall team configuration model."""
    version: str
    name: str
    task: Optional[str] = None
    agents: List[AgentConfig]
    workflows: Optional[List[PlanTemplate]] = None
    properties: Optional[Dict[str, Any]] = None
    nexus_settings: Optional[Dict[str, Any]] = None
    global_settings: Optional[GlobalSettings] = None

def load_team_config(filepath: str) -> TeamConfig:
    """Loads and parses the team's YAML configuration file using Pydantic models.
    支持如下用法：
    - 绝对路径或相对路径（如/xxx/yyy/config.yaml或teams/safe-sop/config.yaml）
    - 仅传teams下的文件夹名（如safe-sop），自动拼接为teams/safe-sop/config.yaml
    - 传文件夹名（如safe-sop/），自动补全config.yaml
    """
    yaml = YAML(typ='safe')
    # 智能路径解析
    orig_filepath = filepath
    path_obj = Path(filepath)
    
    # 尝试不同的路径组合
    possible_paths = [
        path_obj,  # 原始路径
        Path('teams') / path_obj,  # teams/原始路径
        Path('teams') / path_obj / 'config.yaml',  # teams/原始路径/config.yaml
        path_obj / 'config.yaml',  # 原始路径/config.yaml
    ]
    
    # 找到第一个存在的路径
    config_path = None
    for p in possible_paths:
        if p.exists() and p.is_file():
            config_path = p
            break
    
    if not config_path:
        logger.error(f"Configuration file not found: tried paths: {[str(p) for p in possible_paths]} (from input: {orig_filepath})")
        raise FileNotFoundError(f"Configuration file not found: tried multiple paths")
        
    logger.info(f"Attempting to load team configuration from '{config_path}'...")
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            raw_config = yaml.load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {config_path}")
        raise
    except YAMLError as e:
        logger.error(f"Configuration file YAML parsing error: {e}")
        raise

    if not isinstance(raw_config, dict):
        raise ValueError(f"The top level of the configuration file '{config_path}' must be a dictionary.")

    try:
        # Use Pydantic model validation for the entire structure
        loaded_config = TeamConfig.model_validate(raw_config)
        logger.success(f"Successfully loaded and validated configuration for team '{loaded_config.name}' v{loaded_config.version}")
        return loaded_config
    except ValidationError as ve:
        logger.error(f"Configuration validation failed: {ve}")
        # Optionally re-raise or handle differently
        raise ValueError(f"Invalid configuration in '{config_path}': {ve}")
    except Exception as e:
        logger.exception("An unexpected error occurred during configuration validation.")
        raise

# --- TOML LLM Config Loader ---

_config_cache = None

def load_llm_config() -> Dict[str, Any]:
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    # 获取项目根目录（src的父目录）
    src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    root_dir = os.path.dirname(src_dir)
    
    # 按优先级搜索配置文件
    search_paths = [
        root_dir,                    # 项目根目录
        src_dir,                     # src目录
        os.path.abspath(os.getcwd()) # 当前工作目录
    ]
    
    for path in search_paths:
        config_path = os.path.join(path, "config.toml")
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                _config_cache = toml.load(f)
                logger.success(f"Successfully loaded configuration from: {config_path}")
                return _config_cache
    
    # 如果所有目录都找不到，抛出异常
    raise FileNotFoundError(
        f"未找到配置文件config.toml（已在以下目录中搜索）：\n" + 
        "\n".join(f"- {path}" for path in search_paths)
    )

def load_llm_config_from_toml(provider: str = "ds", structured_output: bool = True) -> Optional[OpenAIChatCompletionClient]:
    try:
        config = load_llm_config()
        if "llm" not in config or provider not in config["llm"]:
            logger.error(f"Missing LLM configuration for provider '{provider}'")
            return None
            
        provider_config = config["llm"][provider]
        # provider_config['']
        logger.success(f"Successfully loaded LLM configurations for provider: {provider}")
        
        return create_completion_client(provider, provider_config)
        
    except Exception as e:
        logger.error(f"Failed to load LLM configuration: {e}")
        return None