from typing import List, Optional
from pydantic import BaseModel

class Step(BaseModel):
    """步骤数据结构"""
    index: int
    description: str
    status: str = "pending"

class Plan(BaseModel):
    """计划数据结构"""
    id: str
    title: str
    description: str
    steps: List[Step] = [] 