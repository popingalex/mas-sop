from typing import Optional, List, Dict, Any, TypedDict
from pydantic import BaseModel
from src.types.plan import PlanTemplate

# --- Standard Response Structure --- #
class ResponseType(TypedDict):
    """Standard response format for tool/manager operations."""
    success: bool
    message: str
    data: Optional[Any]

def success(message: str, data: Optional[Any] = None) -> ResponseType:
    """Helper function to create a success response."""
    return ResponseType(success=True, message=message, data=data)

def error(message: str, data: Optional[Any] = None) -> ResponseType:
    """Helper function to create an error response."""
    return ResponseType(success=False, message=message, data=data)

# --- Existing Definitions --- #
class AgentConfig(BaseModel):
    """智能体配置"""
    name: str
    agent: Optional[str] = None  # agent 类型（如有）
    prompt: Optional[str] = None
    sop_templates: Optional[Dict[str, Any]] = None
    assigned_tools: Optional[List[str]] = None  # 工具列表
    llm_config: Optional[Dict[str, Any]] = None  # LLM 配置
    judge_agent_llm_config: Optional[Dict[str, Any]] = None  # judge agent LLM 配置
    expertise_area: Optional[str] = None
    eve_interface_config: Optional[Dict[str, Any]] = None
    actions: Optional[List[str]] = None
    handoffs: Optional[List[Any]] = None  # HandoffTarget 类型如有可补充

class JudgeDecision(BaseModel):
    """判断决策"""
    type: str
    confidence: float
    reason: str 

# --- TeamConfig 及其依赖 --- #
class GlobalSettings(BaseModel):
    default_llm_config: Optional[Dict[str, Any]] = None
    shared_tools: Optional[List[str]] = None

class HandoffTarget(BaseModel):
    target: str

class TeamConfig(BaseModel):
    """Overall team configuration model."""
    version: str
    name: str
    task: Optional[str] = None
    agents: List[AgentConfig]
    workflows: Optional[List[PlanTemplate]] = None  # 明确类型
    global_settings: Optional[GlobalSettings] = None 