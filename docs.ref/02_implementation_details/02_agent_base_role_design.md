# 通用智能体基类 (`AgentBaseRole`) 设计规范 v1.1

## 1. 概述

本文档概述了 `AgentBaseRole` 的设计，这是一个为多智能体框架设计的**抽象基类概念**。其主要目标是为所有智能体角色提供一套通用的核心能力，特别是处理任务执行、根据任务复杂度进行内部规划，以及在必要时发起跨智能体协作请求，从而增强代码可重用性、确保行为一致性并支持灵活的任务处理。

此设计旨在提供一个**框架无关**的基础，定义智能体应具备的核心行为逻辑和状态管理机制。

## 2. 核心目标

*   **任务分解与规划 (Task Decomposition & Planning)**: 使智能体能够接收高层任务目标，并自主将其分解为可执行的步骤（内部计划）。
*   **动态规划策略 (Dynamic Planning Strategy)**: 根据任务复杂度和可用信息，智能体能选择合适的规划方法（例如，简单执行、基于模板的规划、自由形式规划）。
*   **协作发起 (Collaboration Initiation)**: 标准化智能体请求其他智能体协助的方式 (`RequestCollaboration` Action)。
*   **状态管理 (State Management)**: 提供管理智能体内部状态（如当前任务、内部计划、等待状态）的机制。
*   **工具/能力使用 (Tool/Capability Usage)**: 封装调用已注册的 `actions` 和 `tools` 的逻辑。
*   **可重用性 (Reusability)**: 作为基类（或通过组合实现），减少在每个具体智能体中重复实现核心执行逻辑。

## 3. 核心组件与逻辑流

`AgentBaseRole` 的核心是其处理传入任务并执行的逻辑流。这可以概念化为以下阶段，在一个智能体的**执行周期 (Execution Cycle)** 中运行：

1.  **任务接收与解析 (Task Reception & Parsing)**:
    *   在智能体的消息处理循环中，接收到分配给它的任务指令（通常包含 `task_id`, `plan_id`, `description` 等）。
    *   解析任务信息，理解核心目标和约束。

2.  **规划策略选择 (Planning Strategy Selection)**:
    *   **评估复杂度**: 分析任务 `description` 和可用上下文，判断任务是简单任务还是复杂任务。
    *   **选择策略**:
        *   **简单任务**: 直接进入执行阶段。
        *   **复杂任务**: 进入内部规划阶段。可能进一步区分：
            *   **模板驱动规划**: 如果找到匹配的SOP片段或内部模板。
            *   **自由形式规划**: 如果需要从头生成计划。

3.  **内部规划 (Internal Planning) (针对复杂任务)**:
    *   **生成步骤**: 使用 LLM 或其他规划逻辑，将复杂任务分解为一系列内部步骤。
    *   **识别协作**: 确定哪些步骤可以自己完成，哪些需要通过 `RequestCollaboration` Action 委派给其他智能体。
    *   **存储内部计划**: 将生成的步骤序列存储在内部状态中。

4.  **执行 (Execution)**:
    *   按顺序（或根据内部计划逻辑）执行步骤。
    *   **执行自身步骤**: 调用智能体自身的 `actions` 或 `tools`。处理工具调用的结果或错误。
    *   **发起协作**: 当遇到需要协作的步骤时：
        *   调用 `RequestCollaboration.run()` 发送请求，并获得 `request_id`。
        *   **进入等待状态**: 将智能体内部状态标记为等待特定 `request_id` 的响应。暂停当前内部计划的执行。
    *   **处理协作响应**: 在后续的消息处理循环中：
        *   **监听响应**: 检查传入消息是否为等待的协作响应（匹配 `request_id`）。
        *   **处理结果**: 如果收到响应，根据响应状态（`completed`, `error`, `rejected`）更新内部计划状态，并可能恢复执行。
        *   **处理超时**: 如果等待超时（需要实现超时逻辑），标记协作步骤失败并决定下一步行动。

5.  **状态更新与完成 (Status Update & Completion)**:
    *   所有内部步骤（包括协作步骤）完成后，或任务因错误/无法完成而终止时，调用 `Plan Tool` 的 `update_task_status` 更新顶层计划中的任务状态。
    *   清理内部状态。

## 4. 关键接口/方法 (概念性)

一个实现 `AgentBaseRole` 概念的具体类，可能需要包含类似以下的方法（具体名称和签名取决于框架）：

*   `process_message(message: StructuredMessage)`: 处理接收到的消息，如果是任务分配，则启动任务处理流程。
*   `execute_task(task_info: dict)`: 任务执行的主入口点。
*   `_determine_planning_strategy(task_description: str) -> PlanningStrategy`: 内部方法，用于选择规划策略。
*   `_generate_internal_plan(task_description: str) -> InternalPlan`: 内部方法，用于生成内部计划。
*   `_execute_internal_plan(plan: InternalPlan)`: 内部方法，用于驱动内部计划的执行，包括调用 actions/tools 和发起协作。
*   `_handle_collaboration_response(response_message: StructuredMessage)`: 内部方法，用于处理收到的协作响应。
*   `_update_task_status_in_plan_tool(status: str, result: Optional[str])`: 内部方法，调用 `Plan Tool`。

## 5. 状态管理

需要维护智能体的内部状态，例如：

*   `current_task_id`: 当前处理的顶层计划任务 ID。
*   `internal_plan`: 当前执行的内部计划（步骤列表、状态）。
*   `current_step_index`: 内部计划的执行指针。
*   `status`: 智能体自身的高层状态 (e.g., `idle`, `planning`, `executing_step`, `waiting_for_collaboration`).
*   `pending_collaboration_request_id`: 如果正在等待协作响应，存储对应的 `request_id`。

## 6. 与框架的集成

*   具体的智能体类将**实现**这个 `AgentBaseRole` 定义的接口或行为（例如通过继承一个框架无关的抽象基类，或通过组合方式）。
*   框架负责将传入的消息路由到 `process_message` 或类似的方法。
*   框架需要提供调用 `actions` 和 `tools` 的机制。
*   框架需要提供通信机制以支持 `RequestCollaboration`。

## 7. 示例代码片段 (伪代码)

```python
# 这是一个高度简化的伪代码示例，说明核心逻辑
# 注意：这只是概念演示，不依赖任何特定框架的类或导入

# --- 概念定义 (可能在其他地方) ---
class StructuredMessage: pass
class AgentState: pass
class PlanningStrategy: SIMPLE, COMPLEX_TEMPLATE, COMPLEX_FREEFORM = range(3)
class StepType: EXECUTE_ACTION, USE_TOOL, REQUEST_COLLABORATION = range(3)
class InternalPlan: pass
# --- End Conceptual Definitions ---

class AgentBaseRoleConcept: # 这是一个概念，不是具体的实现

    def __init__(self, name, actions, tools, llm_config):
        self.name = name
        self.actions = actions # Map action names to callable functions/objects
        self.tools = tools     # Map tool names to callable functions/objects
        self.llm_config = llm_config
        self.state = AgentState() # Internal state management

    def is_task_assignment(self, message) -> bool: # Placeholder
        return False
    def parse_task(self, message) -> dict: # Placeholder
        return {}
    def is_collaboration_response(self, message) -> bool: # Placeholder
        return False
    def create_simple_plan(self, task_info) -> InternalPlan: # Placeholder
        return InternalPlan()

    def process_message(self, message: StructuredMessage):
        if self.is_task_assignment(message):
            task_info = self.parse_task(message)
            self.execute_task(task_info)
        elif self.is_collaboration_response(message):
            # Assume message has request_id attribute for checking
            if hasattr(message, 'request_id') and self.state.is_waiting_for(message.request_id):
                self._handle_collaboration_response(message)
        # ... other message types

    def execute_task(self, task_info: dict):
        self.state.set_current_task(task_info) # Assume state method exists
        strategy = self._determine_planning_strategy(task_info['description'])
        if strategy == PlanningStrategy.SIMPLE:
            self.state.internal_plan = self.create_simple_plan(task_info)
        else: # COMPLEX (Template or Free-form)
            self.state.internal_plan = self._generate_internal_plan(task_info['description'])

        self._execute_internal_plan()

    def _execute_internal_plan(self):
        # Assume state object manages plan steps, waiting status etc.
        while self.state.internal_plan and not self.state.is_waiting():
            step = self.state.get_next_step()
            if not step:
                self._finalize_task(status="completed")
                break

            try:
                if step.type == StepType.EXECUTE_ACTION:
                    # Assume actions is a dict-like object mapping name to callable
                    result = self.actions[step.action_name](**step.params)
                    self.state.update_step_status(result) # Assume state handles success/failure
                elif step.type == StepType.USE_TOOL:
                    # Assume tools is a dict-like object mapping name to callable
                    result = self.tools[step.tool_name](**step.params)
                    self.state.update_step_status(result)
                elif step.type == StepType.REQUEST_COLLABORATION:
                    collaboration_action = self.actions['RequestCollaboration'] # Assume capability exists
                    # Assume run returns dict with status and request_id
                    result = collaboration_action.run(target_name=step.target, subtask_description=step.description, context=step.context)
                    if result.get('status') == 'pending':
                        self.state.set_waiting_for(result['request_id'])
                    else: # Handle immediate error from sending
                        self.state.update_step_status(error=True, message="Collaboration request failed")
            except Exception as e:
                 # Log exception e
                 self.state.update_step_status(error=True, message=str(e))

            if self.state.current_step_failed():
                 self._finalize_task(status="error")
                 break

            self.state.advance_step()

    def _handle_collaboration_response(self, message: StructuredMessage):
        # Assume message has status, result_data attributes
        # Assume state handles updating based on response
        self.state.clear_waiting_state()
        self.state.update_collaboration_step_status(message.status, message.result_data)
        # Potentially resume execution if plan is not finished
        if not self.state.is_plan_finished():
             self._execute_internal_plan()

    def _finalize_task(self, status: str):
        plan_tool = self.tools['PlanTool'] # Assume tool access
        # Assume state methods exist
        plan_tool.update_task_status(self.state.plan_id, self.state.task_id, status, self.state.get_result_summary())
        self.state.reset()

    # --- Internal methods to be defined ---
    def _determine_planning_strategy(self, task_description: str) -> PlanningStrategy:
        # Logic to analyze task and decide strategy
        pass
    def _generate_internal_plan(self, task_description: str) -> InternalPlan:
        # LLM call or logic to break down task
        pass
    # --- End Internal methods --- 

```

## 8. 结论

`AgentBaseRole` 概念为智能体提供了一个标准化的、能力强大的基础。通过将复杂任务规划内部化并定义清晰的执行逻辑和协作接口，它使得智能体定义 (包括提示词) 可以更简洁、更易于维护，专注于其独特职责和能力，同时增强了智能体自主实现复杂目标的能力，且设计本身与特定多智能体框架解耦。

