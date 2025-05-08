from typing import Optional, List, Dict, Any, TypedDict
from pydantic import BaseModel

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
    agent: str  # 必需的 agent 类型
    prompt: Optional[str] = None
    sop_templates: Optional[Dict[str, Dict[str, Any]]] = None
    assigned_tools: Optional[List[str]] = None  # 添加工具列表
    llm_config: Optional[Dict[str, Any]] = None  # 添加 LLM 配置

class JudgeDecision(BaseModel):
    """判断决策"""
    type: str
    confidence: float
    reason: str 