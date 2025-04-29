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

# --- Pydantic 模型定义 ---

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

class AgentConfig(BaseModel):
    """Configuration for a single agent."""
    name: str
    agent: str # Renamed from role_class
    prompt: Optional[str] = None
    llm_config: Optional[LLMConfig] = None
    # --- New fields for SOPAgent internal tools --- 
    sop_templates: Optional[Dict[str, Any]] = None # Pass SOP definitions here
    judge_agent_llm_config: Optional[LLMConfig] = None # Optional dedicated LLM config for JudgeAgent
    expertise_area: Optional[str] = None
    eve_interface_config: Optional[Dict[str, Any]] = None
    actions: Optional[List[str]] = None
    handoffs: Optional[List[HandoffTarget]] = None
    assigned_tools: Optional[List[str]] = None # Keep for potentially loading external non-AgentTools by name

class TeamConfig(BaseModel):
    """Overall team configuration model."""
    version: str
    team_name: str
    global_settings: Optional[GlobalSettings] = None
    agents: List[AgentConfig] # Now strictly list of AgentConfig

def load_config(filepath: str) -> TeamConfig:
    """Loads and parses the team's YAML configuration file using Pydantic models."""
    yaml = YAML(typ='safe')
    logger.info(f"Attempting to load team configuration from '{filepath}'...")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_config = yaml.load(f)
    except FileNotFoundError:
        logger.error(f"Configuration file not found: {filepath}")
        raise
    except YAMLError as e:
        logger.error(f"Configuration file YAML parsing error: {e}")
        raise

    if not isinstance(raw_config, dict):
        raise ValueError(f"The top level of the configuration file '{filepath}' must be a dictionary.")

    try:
        # Use Pydantic model validation for the entire structure
        loaded_config = TeamConfig.model_validate(raw_config)
        logger.success(f"Successfully loaded and validated configuration for team '{loaded_config.team_name}' v{loaded_config.version}")
        return loaded_config
    except ValidationError as ve:
        logger.error(f"Configuration validation failed: {ve}")
        # Optionally re-raise or handle differently
        raise ValueError(f"Invalid configuration in '{filepath}': {ve}")
    except Exception as e:
        logger.exception("An unexpected error occurred during configuration validation.")
        raise

# --- TOML LLM Config Loader ---

_config_cache = None

def load_config() -> Dict[str, Any]:
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

def load_llm_config_from_toml(provider: str = "ds") -> Optional[OpenAIChatCompletionClient]:
    try:
        config = load_config()
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

# --- 示例用法更新 --- #
if __name__ == '__main__':
    # --- Example for YAML Team Config --- 
    try:
        script_dir = os.path.dirname(__file__)
        config_path = os.path.join(script_dir, '../../teams/safe-sop/config.yaml')
        logger.info(f"Loading example team configuration file: {config_path}")
        loaded_team_config: TeamConfig = load_config(config_path) # Type hint for clarity

        print("\n--- Team Config Load Result (Partial) ---")
        print(f"Team Name: {loaded_team_config.team_name}")
        print(f"Config Version: {loaded_team_config.version}")

        print("\nAgents Summary:")
        if loaded_team_config.agents:
            for agent_conf in loaded_team_config.agents:
                print(f"  - Name: {agent_conf.name}")
                print(f"    Agent Class: {agent_conf.agent}")
                if agent_conf.prompt:
                    print(f"    Prompt Snippet: {agent_conf.prompt[:50]}...")
                if agent_conf.actions:
                    print(f"    Actions ({len(agent_conf.actions)}): {agent_conf.actions[:2]}...") # Print first few actions
                if agent_conf.handoffs:
                    print(f"    Handoff Targets ({len(agent_conf.handoffs)}): {[h.target for h in agent_conf.handoffs]}")
                if agent_conf.assigned_tools:
                    print(f"    Assigned Tools: {agent_conf.assigned_tools}")
        else:
            print("  No agents defined.")

        print("\nExample completed for YAML config.")

    except (FileNotFoundError, YAMLError, ValueError, ValidationError) as e:
        logger.exception("Error loading or parsing team configuration file")
        print(f"\nError during team configuration loading: {e}")

    print("\n" + "="*30 + "\n")

    # --- Example for TOML LLM Config --- 
    try:
        toml_config_path = os.path.join(script_dir, '../../config.toml') # Adjust path if needed
        logger.info(f"Loading example LLM configuration file: {toml_config_path}")
        loaded_llm_configs = load_llm_config_from_toml(toml_config_path)

        print("\n--- LLM Config Load Result (from TOML) ---")
        if loaded_llm_configs:
            for provider, config in loaded_llm_configs.items():
                print(f"  Provider: {provider}")
                print(f"    Config: {config}")
        else:
            print("  No LLM configurations loaded from TOML file.")
        print("\nExample completed for TOML LLM config.")

    except Exception as e:
         logger.exception("Error loading or parsing LLM configuration file")
         print(f"\nError during LLM configuration loading: {e}") 