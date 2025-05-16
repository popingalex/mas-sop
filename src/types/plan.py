from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, validator
from datetime import datetime

# Status Literals
PlanStatus = Literal["not_started", "in_progress", "completed"]
StepStatus = Literal["not_started", "in_progress", "completed"]
TaskStatus = Literal["not_started", "in_progress", "completed"]

class TaskNote(BaseModel):
    author: str
    content: str
    from_status: Optional[str] = None
    to_status: Optional[str] = None
    turn: int  # 轮次，必填

class TaskIOItem(BaseModel):
    """任务输入输出项数据结构"""
    name: str  # 英文名
    label: str  # 中文标签/友好展示名
    artifact_id: Optional[str] = None # 实际运行时填充的资产ID

class SubPlanRef(BaseModel):
    id: str
    name: Optional[str] = None
    status: Optional[str] = None  # 子计划状态，便于快速判断

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
    inputs: List[TaskIOItem] = [] # 新增，任务输入清单
    outputs: List[TaskIOItem] = [] # 新增，任务输出清单
    notes: List[TaskNote] = []
    sub_plans: Optional[List[SubPlanRef]] = None  # 子计划引用列表，包含状态

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
    next: 当前计划的下一个待办任务的索引路径（如 [step_id, task_id]），None 表示计划未开始或已全部完成。
    parent_task: 可选，记录父任务索引（plan_id, step_id, task_id），如为主计划则为 None。
    """
    id: str
    name: str  # 原title字段，改为name
    description: str
    steps: List[Step] = []
    status: PlanStatus = "not_started"
    next: Optional[List[str]] = None  # 指向下一个待完成任务的索引路径（如 [step_id, task_id]，均为字符串）
    parent_task: Optional[Dict[str, str]] = None  # 新增，父任务索引

    def task_by_path(self, step_id: str, task_id: str) -> Optional[Task]:
        step = next((s for s in self.steps if s.id == step_id), None)
        if not step:
            return None
        return next((t for t in step.tasks if t.id == task_id), None)

class PlanTemplate(BaseModel):
    """SOP计划模板数据结构 (配置时使用)"""
    name: str # Corresponds to WorkflowDefinition.name
    version: str # Corresponds to WorkflowDefinition.version
    description: str # Corresponds to WorkflowDefinition.description
    steps: List[Step] = [] # Uses the unified Step model

class PlanContext(BaseModel):
    """计划运行时上下文数据对象，包含事件、计划ID、资产ID、当前步骤和任务ID等。"""
    event: str
    plan_id: str
    artifact_id: str
    step_id: str = None  # 可选
    task_id: str = None  # 可选