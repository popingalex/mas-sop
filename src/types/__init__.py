from typing import Optional, List, Dict, Any
from pydantic import BaseModel

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