from typing import List, Optional, Literal
from pydantic import BaseModel, validator
from datetime import datetime

# Status Literals
PlanStatus = Literal["not_started", "in_progress", "completed", "error"]
StepStatus = Literal["not_started", "in_progress", "completed", "error"]
TaskStatus = Literal["not_started", "in_progress", "completed", "error"]

class TaskNote(BaseModel):
    author: str
    content: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    turn: int  # 轮次，必填

class Task(BaseModel):
    """任务数据结构，嵌套在步骤内
    sub_plans: 可选，挂载的子计划列表，每项包含id、name。
    """
    id: str # 必填
    name: str # 必填
    label: Optional[str] = None  # 可选，任务的中文/友好展示名
    assignee: str # 必填
    description: str # 来自原 WorkflowTask
    status: TaskStatus = "not_started" # Use TaskStatus
    notes: List[TaskNote] = []
    sub_plans: Optional[List[dict]] = None  # 新增，子计划列表

class Step(BaseModel):
    """步骤数据结构"""
    id: str
    name: str
    index: Optional[int] = None
    description: str # 步骤的总体描述
    assignee: Optional[str] = None # 步骤的总体指派人，如果任务没有单独指派人则使用此指派人
    status: StepStatus = "not_started" # Use StepStatus
    tasks: List[Task] = [] # 步骤包含的任务列表

class Plan(BaseModel):
    """计划数据结构 (运行时实例)
    cursor: 当前计划的下一个待办任务的索引路径（如 [step_idx, task_idx]），None 表示计划未开始或已全部完成。
    """
    id: str
    name: str  # 原title字段，改为name
    description: str
    steps: List[Step] = []
    status: PlanStatus = "not_started"
    cursor: Optional[List[str]] = None  # 指向下一个待完成任务的索引路径（如 [step_idx, task_idx]，均为字符串）

class PlanTemplate(BaseModel):
    """SOP计划模板数据结构 (配置时使用)"""
    name: str # Corresponds to WorkflowDefinition.name
    version: str # Corresponds to WorkflowDefinition.version
    description: str # Corresponds to WorkflowDefinition.description
    steps: List[Step] = [] # Uses the unified Step model