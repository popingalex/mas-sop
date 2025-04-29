# Plan Tool 规范 v1.2

## 1. 概述

`Plan Tool` 是一个为多智能体框架设计的通用工具。其核心职责是作为一个**被动的状态管理器**，用于存储、检索和更新由结构化模板（如 SOP / `workflows`）实例化的**顶层计划 (Top-Level Plan)** 中各个任务的状态。它使智能体能够查询其在该顶层计划中的任务、更新任务进度，并允许驱动智能体（如 `Strategist` Agent）监控和协调高层流程的执行。

`Plan Tool` **不包含**任何特定业务逻辑，不主动驱动流程，不存储智能体为执行复杂任务而生成的内部子计划，并且**不管理任务间的执行顺序依赖**。任务的执行顺序由 `workflows` 的结构定义，并由与 `Plan Tool` 交互的智能体负责执行。

## 2. 核心概念

*   **计划 (Plan)**: 由 `Plan Tool` 管理的、代表一个完整的、结构化的顶层执行流程的实例，该实例通常在流程开始时由某个智能体根据 SOP 模板 (`workflows`) 创建。每个计划有一个唯一的 `plan_id`。
*   **步骤 (Step)**: 计划中的一个主要阶段或逻辑分组，包含一个或多个任务。有 `step_id`。
*   **任务 (Task)**: 计划中的一个具体工作单元。每个任务有唯一的 `task_id` (在计划内)，包含描述 (`description`)、指定的负责人 (`assignee`) 和当前状态 (`status`)。**注意：任务间执行顺序不由本工具强制规定。**
*   **状态 (Status)**: 任务的执行状态，例如 `ready` (任务已定义，等待被执行), `inprogress` (执行中), `completed` (成功完成), `error` (执行出错), `skipped` (被跳过)。计划本身也有整体状态，如 `running`, `completed`, `error`。

## 3. 数据结构 (概念性)

`Plan Tool` 内部需要维护计划及其组成部分的状态。这可以通过嵌套的字典或专门的 Pydantic/dataclass 模型来实现。

```python
# --- 概念性数据结构 (示例) ---
from typing import List, Dict, Optional, Literal

TaskStatus = Literal["ready", "inprogress", "completed", "error", "skipped"]
PlanStatus = Literal["running", "completed", "error"]

class TaskInfo:
    task_id: str
    name: str
    assignee: str
    description: str
    # dependencies: List[str] = [] # Removed
    status: TaskStatus = "ready" # 初始状态设为 ready
    result_summary: Optional[str] = None
    # Optional: step_id for grouping

class StepInfo:
    step_id: str
    name: str
    tasks: List[TaskInfo] = []
    # Optional: status derived from tasks

class PlanInstance:
    plan_id: str
    name: str
    description: str
    workflow_template_source: str # e.g., "SAFE_SOP_v9.0"
    steps: List[StepInfo] # Or a flat list/dict of tasks with step_id attribute
    task_map: Dict[str, TaskInfo] # For quick lookup by task_id
    status: PlanStatus = "running"
    # Optional: creation_time, completion_time

# Plan Tool 内部可能维护一个字典
# internal_storage: Dict[str, PlanInstance] = {}

```

## 4. API 方法定义

`Plan Tool` 应提供以下核心方法供智能体或框架调用：

*   **`create_plan_from_structure(plan_id: str, structure_data: dict) -> bool`**
    *   **描述**: 根据提供的结构化数据（通常解析自 `team.yaml` 的 `workflows`）创建一个新的顶层计划实例并存储。
    *   **参数**:
        *   `plan_id`: 为新计划指定的唯一 ID。
        *   `structure_data`: 包含计划名称、描述、步骤和任务信息的字典/对象，结构应与 `workflows` 兼容。
    *   **返回**: 如果创建成功返回 `True`，如果 `plan_id` 已存在或数据无效则返回 `False`。
    *   **逻辑**: 解析 `structure_data`，构建 `PlanInstance`，将所有任务的初始状态设为 `ready`，存入内部存储。

*   **`get_task(plan_id: str, task_id: str) -> Optional[dict]`**
    *   **描述**: 获取指定计划中特定任务的详细信息。
    *   **参数**: `plan_id`, `task_id`。
    *   **返回**: 包含任务信息的字典 (类似 `TaskInfo`)，如果未找到则返回 `None`。

*   **`update_task_status(plan_id: str, task_id: str, status: TaskStatus, result_summary: Optional[str] = None) -> bool`**
    *   **描述**: 更新指定任务的状态，并可选地记录结果摘要。
    *   **参数**: `plan_id`, `task_id`, `status` (必须是有效的 `TaskStatus`), `result_summary`。
    *   **返回**: 如果更新成功返回 `True`，如果计划/任务不存在或状态转换无效则返回 `False`。
    *   **逻辑**:
        1.  查找计划和任务。
        2.  验证状态转换是否有效。
        3.  更新任务的 `status` 和 `result_summary`。
        4.  ~~关键：触发依赖检查~~ (移除此步骤)
        5.  更新整个计划的总体状态 (例如，当所有任务都达到终态 `completed`, `error`, `skipped` 时更新计划状态)。

*   **`get_ready_tasks(plan_id: str) -> List[dict]`**
    *   **描述**: 获取指定计划中所有当前状态为 `ready` 的任务列表。**注意：此列表不保证执行顺序，调用者需根据 `workflows` 结构自行判断下一个要执行的任务。**
    *   **参数**: `plan_id`。
    *   **返回**: 包含就绪任务信息的字典列表。

*   **`get_tasks_for_role(plan_id: str, role_id: str, status: TaskStatus = 'ready') -> List[dict]`**
    *   **描述**: 获取指定计划中分配给特定角色且处于特定状态（默认为 `ready`）的任务列表。**同样，此列表不保证顺序。**
    *   **参数**: `plan_id`, `role_id` (与 `assignee` 匹配), `status`。
    *   **返回**: 任务信息字典列表。

*   **`get_plan_status(plan_id: str) -> Optional[PlanStatus]`**
    *   **描述**: 获取指定计划的整体状态。
    *   **参数**: `plan_id`。
    *   **返回**: 计划状态 (`running`, `completed`, `error`)，如果未找到则返回 `None`。

*   **(可选) `get_plan_structure(plan_id: str) -> Optional[dict]`**
    *   **描述**: 获取整个计划的结构和当前状态。
    *   **参数**: `plan_id`。
    *   **返回**: 包含计划完整信息的字典，或 `None`。

*   **(可选) `delete_plan(plan_id: str) -> bool`**
    *   **描述**: 删除一个计划实例。
    *   **参数**: `plan_id`。
    *   **返回**: 删除成功返回 `True`。

## 5. 状态管理

*   **初始化**: `create_plan_from_structure` 将所有任务的初始状态设为 `ready`。
*   **状态转换**: `update_task_status` 负责更新单个任务的状态。任务的执行流转（哪个 `ready` 任务被设为 `inprogress`）由外部逻辑控制。
*   **错误处理**: 如果一个任务更新为 `error`，计划的整体状态应在适当的时候（例如，检查是否所有任务都已结束）更新为 `error`。
*   **可选任务**: ... (保持不变，但跳过逻辑由外部控制)

## 6. 实现说明

*   **存储**: Phase 1 可以使用 Python 的内存字典作为 `internal_storage`。未来可以考虑替换为更持久化的存储（如数据库、文件）。
*   **并发**: 如果框架支持并发执行智能体，需要考虑对 `Plan Tool` 内部状态的访问加锁，以防止竞争条件。
*   **调用接口**: `Plan Tool` 的功能应通过框架提供的标准机制暴露给智能体调用。

## 7. 待讨论问题

*   **任务执行顺序**: 如何确保外部逻辑（调用 `Plan Tool` 的智能体）能够正确地按照 `workflows` 定义的顺序来执行任务？这需要清晰的智能体职责定义。
*   **错误状态的传播**: 计划整体状态何时以及如何精确地根据任务错误状态进行更新？
*   可选任务/步骤的具体跳过机制（由外部逻辑处理）。
*   `plan_id` 生成策略。

--- 