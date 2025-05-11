from typing import List, Optional, Literal
from pydantic import BaseModel

# Status Literals
PlanStatus = Literal["not_started", "in_progress", "completed", "error"]
StepStatus = Literal["not_started", "in_progress", "completed", "error"]
TaskStatus = Literal["not_started", "in_progress", "completed", "error"]

class Task(BaseModel):
    """任务数据结构，嵌套在步骤内"""
    id: str # 来自原 WorkflowTask
    name: str    # 来自原 WorkflowTask
    assignee: Optional[str] = None # 来自原 WorkflowTask
    description: str # 来自原 WorkflowTask
    # 可以根据需要添加其他 Task 特定字段，例如 status
    status: TaskStatus = "not_started" # Use TaskStatus

class Step(BaseModel):
    """步骤数据结构"""
    id: Optional[str] = None
    name: Optional[str] = None
    index: Optional[int] = None
    description: str # 步骤的总体描述
    assignee: Optional[str] = None # 步骤的总体指派人，如果任务没有单独指派人则使用此指派人
    status: StepStatus = "not_started" # Use StepStatus
    tasks: List[Task] = [] # 步骤包含的任务列表

class Plan(BaseModel):
    """计划数据结构 (运行时实例)"""
    id: str
    title: str
    description: str
    steps: List[Step] = []
    status: PlanStatus = "not_started"

class PlanTemplate(BaseModel):
    """SOP计划模板数据结构 (配置时使用)"""
    name: str # Corresponds to WorkflowDefinition.name
    version: str # Corresponds to WorkflowDefinition.version
    description: Optional[str] = None # Corresponds to WorkflowDefinition.description
    steps: List[Step] = [] # Uses the unified Step model
    # Allow other fields if needed, mimicking WorkflowDefinition
    class Config:
        extra = 'allow' 