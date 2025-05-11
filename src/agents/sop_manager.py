from typing import Optional, List, Dict, Any, AsyncGenerator, Sequence, cast
from uuid import UUID
from loguru import logger
import traceback
import json

from autogen_agentchat.messages import TextMessage, BaseChatMessage, BaseTextChatMessage
from autogen_agentchat.base import Response

from autogen_core.models import ChatCompletionClient
from autogen_core import MessageContext

from .base_sop_agent import BaseSOPAgent
from .judge import judge_agent_tool, JudgeDecision
from ..config.parser import AgentConfig, TeamConfig
from ..tools.plan.manager import PlanManager, Step, Plan
from ..tools.errors import ErrorMessages
from ..types import ResponseType, success, error
from ..types.plan import Plan, Step, Task, PlanTemplate

# Placeholder for the actual tool schema if we were using AutoGen's tool registration
# For now, PlanManager methods will be called directly by NexusAgent's Python code,
# but this call is conceptually decided by the LLM.

ASSISTANT_MESSAGE_TERMINATE = "TERMINATE"
ASSISTANT_MESSAGE_ALL_TASKS_DONE = "ALL_TASKS_DONE"

# 定义常量用于LLM意图识别或生成的消息内容
TOOL_CREATE_PLAN = "create_plan"
TOOL_GET_PLAN = "get_plan"
TOOL_GET_NEXT_STEP = "get_next_pending_step"
TOOL_UPDATE_STEP = "update_step"
MSG_ALL_TASKS_DONE = "ALL_TASKS_DONE"
MSG_TERMINATE = "TERMINATE"

# System message for NexusAgent
NEXUS_AGENT_SYSTEM_MESSAGE = """你是 NexusCoordinator，一个经验丰富的SOP流程协调专家。

**核心职责**:
1.  **新任务处理**: 当收到全新的用户任务时：
    a.  **必须首先调用** `judge_task_type_tool` 工具来分析任务类型。
    b.  **分析工具结果**:
        *   如果类型是 `PLAN`，你的下一个任务是参照系统提供的可用SOP Workflow模板列表，选择最合适的一个，并为该计划设定一个清晰的标题。然后，**直接在你的响应中** 清晰地说明你选择的模板名称 (`chosen_template_name`) 和计划标题 (`plan_title`)，例如："已选择模板 '模板A'，计划标题为 '处理X的计划'。请创建主计划。" (系统将根据此信息创建主计划)。计划创建成功后 (系统会通知你计划ID)，你的下一个行动是调用 `get_next_pending_step_tool` 工具获取第一个待办步骤。
        *   如果类型是 `SIMPLE`，则尝试直接生成对用户请求的回应。
        *   如果类型是 `UNCLEAR` 或 `SEARCH`，你将告知用户并通常会终止当前交互 (输出 `TERMINATE`)。

2.  **进行中计划的驱动**:
    *   当一个主计划正在执行中（例如，你收到了一个LeafAgent完成步骤的消息，或者计划刚创建完毕），你需要驱动其按步骤进行。
    *   通常，你的行动是调用 `get_next_pending_step_tool` 来获取下一个待处理的步骤。
    *   在处理一个已完成的步骤后，你应该先调用 `update_step_status_tool` 将其标记为 `completed`，然后再调用 `get_next_pending_step_tool` 获取下一步。
    *   你**不负责**为LeafAgent创建或管理其内部的子计划。

3.  **工具使用 (可用工具列表)**:
    *   `judge_task_type_tool(task_description: str)`: 分析给定任务描述的类型 (PLAN, SIMPLE, SEARCH, UNCLEAR)。返回包含类型、置信度和原因的JSON字符串。
    *   `get_next_pending_step_tool(plan_id: str)`: 获取指定 plan_id 中主计划的下一个待处理步骤。返回步骤详情JSON或无待处理步骤的消息。
    *   `update_step_status_tool(plan_id: str, step_identifier: str, new_status: str)`: 更新指定 plan_id 中某个步骤的状态 (例如, 'completed', 'in_progress')。`step_identifier` 可以是步骤ID。
    *   `get_plan_details_tool(plan_id: str)`: 获取指定 plan_id 的主计划完整详情JSON。
    *   **注意**: 你**不直接调用** `create_plan` 工具来创建基于SOP的主计划。你只需要在判断任务为PLAN后，在你的文本响应中提供 `chosen_template_name` 和 `plan_title`。

4.  **任务分派与流程结束**:
    *   当你通过 `get_next_pending_step_tool` 获取到待办步骤后，提取步骤信息 (特别是 `assignee` 和任务描述)，然后生成并发送清晰的任务指令给对应的 `assignee` (LeafAgent)。标准格式为 "HANDOFF_TO_[AssigneeName]" 并在消息体中包含任务细节。
    *   当 `get_next_pending_step_tool` 返回主计划"没有待处理步骤"时，生成并发送内容为 `ALL_TASKS_DONE` 的消息给 `StopAgent`。

**重要沟通指令**:
*   **最高优先级 (SYSTEM_DIRECTIVE)**: 如果你的消息历史中，最新一条来自用户且内容以 "SYSTEM_DIRECTIVE:" 开头，你必须严格按照该指令的文本内容作为你的最终输出，忽略所有其他思考和工作流程。
*   当你需要调用工具时，必须使用结构化的工具调用格式（如果模型支持），或者清晰说明 "调用工具 `tool_name`，参数为：..."。

(LeafAgent能力信息相关的提示已移除，因为Nexus不直接使用它们创建子计划)
"""

class NexusAgent(BaseSOPAgent):
    """NexusAgent: 中心协调者, LLM驱动, 通过PlanManager工具管理SOP计划并分发任务。"""

    def __init__(
        self,
        name: str,
        agent_config: AgentConfig,
        model_client: ChatCompletionClient,
        plan_manager: PlanManager,
        team_config: Optional[TeamConfig] = None,
        artifact_manager: Optional[Any] = None,
        system_message: Optional[str] = None,
        **kwargs,
    ):
        effective_system_message = system_message or NEXUS_AGENT_SYSTEM_MESSAGE

        super().__init__(
            name=name,
            agent_config=agent_config,
            model_client=model_client,
            plan_manager=plan_manager,
            artifact_manager=artifact_manager,
            system_message=effective_system_message,
            **kwargs
        )
        self.team_config = team_config
        self.current_plan_id: Optional[UUID] = None
        self.last_dispatched_step: Optional[Step] = None

        # 注册 judge_agent_tool
        judge_tool = judge_agent_tool(self.model_client)
        self.register_tool(judge_tool)

        logger.info(f"[{self.name}] Initialized. PlanManager tools and judge_agent_tool are available.")

    async def on_messages_stream(
        self,
        messages: List[BaseChatMessage],
        ctx: MessageContext,
        **kwargs,
    ) -> AsyncGenerator[BaseChatMessage, None]:
        """处理收到的消息流。
        
        主要职责：
        1. 接收用户任务或工作者反馈
        2. 使用 judge_agent_tool 判断任务类型
        3. 根据判断结果执行相应操作：
           - PLAN: 制定并执行计划
           - SEARCH: 请求更多信息
           - UNCLEAR: 请求澄清
        4. 管理任务分配和进度跟踪
        """
        if not messages:
            logger.warning(f"[{self.name}]: Received empty messages list")
            yield TextMessage(content=f"[{self.name}] 错误: 没有收到任何消息", source=self.name, role="assistant")
            yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
            return

        # 获取最后一条消息用于判断
        last_message = messages[-1]
        last_message_content = last_message.content if last_message else ""
        last_message_content_for_judge = last_message_content
        
        # 如果消息来自工作者，检查是否为任务完成报告
        if last_message.source != "user":
            if "TASK_COMPLETE" in last_message_content:
                # 更新计划状态
                try:
                    current_plan = await self.plan_manager.get_plan()
                    if current_plan:
                        # 找到并更新已完成的任务
                        for step in current_plan.steps:
                            if step.assignee == last_message.source and step.status == "in_progress":
                                await self.plan_manager.update_step(step.id, status="completed")
                                break
                        
                        # 获取下一个待处理的任务
                        next_step = await self.plan_manager.get_next_pending_step()
                        if next_step:
                            # 分配新任务
                            await self.plan_manager.update_step(next_step.id, status="in_progress")
                            assignment_message = f"""NEXUS_ASSIGNMENT:
SOP_TASK_ID: {next_step.id}
SOP_TASK_NAME: {next_step.name}
DESCRIPTION: {next_step.description}
--- END OF ASSIGNMENT ---"""
                            yield TextMessage(
                                content=f"HANDOFF_TO_{next_step.assignee}",
                                source=self.name,
                                role="assistant"
                            )
                            yield TextMessage(
                                content=assignment_message,
                                source=self.name,
                                role="assistant"
                            )
                            return
                        else:
                            # 没有更多任务，结束流程
                            yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                            return
                except Exception as e:
                    logger.error(f"[{self.name}]: Error updating plan status: {e}", exc_info=True)
                    yield TextMessage(content=f"[{self.name}] 错误: 更新计划状态失败 - {e}", source=self.name, role="assistant")
                    yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                    return
        
        try:
            # 通过 tool 机制调用 judge_agent_tool
            judge_decision_json_str: Optional[str] = None
            try:
                judge_tool_result = await self.call_tool(
                    tool_name="Judger",
                    input=last_message_content_for_judge,
                    ctx=ctx
                )
                if judge_tool_result and isinstance(judge_tool_result, TextMessage):
                    judge_decision_json_str = judge_tool_result.content
                    logger.info(f"[{self.name}]: judge_agent_tool decision: {judge_decision_json_str}")
                else:
                    raise ValueError("judge_agent_tool did not return a valid decision.")

                judge_decision = JudgeDecision.parse_raw(judge_decision_json_str)
                
                # 根据判断结果处理
                if judge_decision.type == "PLAN":
                    # 如果需要制定计划
                    if self.team_config and self.team_config.workflows:
                        # 有可用的 SOP 模板
                        logger.info(f"[{self.name}]: Creating plan using available SOP templates.")
                        try:
                            # 创建新计划
                            workflow = self.team_config.workflows[0]  # 使用第一个可用模板
                            plan = await self.plan_manager.create_plan(
                                title=f"处理任务: {last_message_content[:50]}...",
                                description=last_message_content,
                                steps=workflow.steps if workflow else None
                            )
                            
                            if plan and plan.steps:
                                # 获取第一个任务
                                first_step = plan.steps[0]
                                await self.plan_manager.update_step(first_step.id, status="in_progress")
                                
                                # 分配第一个任务
                                assignment_message = f"""NEXUS_ASSIGNMENT:
SOP_TASK_ID: {first_step.id}
SOP_TASK_NAME: {first_step.name}
DESCRIPTION: {first_step.description}
--- END OF ASSIGNMENT ---"""
                                
                                yield TextMessage(
                                    content=f"HANDOFF_TO_{first_step.assignee}",
                                    source=self.name,
                                    role="assistant"
                                )
                                yield TextMessage(
                                    content=assignment_message,
                                    source=self.name,
                                    role="assistant"
                                )
                                return
                            else:
                                raise ValueError("Created plan has no steps")
                                
                        except Exception as e:
                            logger.error(f"[{self.name}]: Failed to create or start plan: {e}", exc_info=True)
                            yield TextMessage(content=f"[{self.name}] 错误: 创建或启动计划失败 - {e}", source=self.name, role="assistant")
                            yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                            return
                    else:
                        # 没有可用的 SOP 模板
                        logger.warning(f"[{self.name}]: No SOP templates available in team_config.")
                        yield TextMessage(content=f"[{self.name}] 错误: 任务需要制定计划，但没有配置 SOP 模板。", source=self.name, role="assistant")
                        yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                        return
                        
                elif judge_decision.type in ["SEARCH", "UNCLEAR"]:
                    logger.info(f"[{self.name}]: Task classified as {judge_decision.type}. Reason: {judge_decision.reason}")
                    final_response_content = f"任务被判断为 {judge_decision.type}。原因: {judge_decision.reason}。我无法继续制定计划。请澄清您的请求或尝试其他任务。"
                    if judge_decision.type == "UNCLEAR":
                        final_response_content = f"任务不明确。judge_agent_tool 的原因: {judge_decision.reason}。请提供更多细节或澄清您的请求。"

                    yield TextMessage(content=final_response_content, source=self.name, role="assistant")
                    yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                    return
                    
                else:
                    logger.error(f"[{self.name}]: Unexpected decision type: {judge_decision.type}")
                    yield TextMessage(content=f"[{self.name}] 错误: judge_agent_tool 返回了意外的决策类型: {judge_decision.type}", source=self.name, role="assistant")
                    yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                    return
                    
            except Exception as e:
                logger.error(f"[{self.name}]: Error with judge_agent_tool: {e}", exc_info=True)
                yield TextMessage(content=f"[{self.name}] 错误: judge_agent_tool 调用失败 - {e}", source=self.name, role="assistant")
                yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                return
                
        except Exception as e:
            logger.error(f"[{self.name}]: General error: {e}", exc_info=True)
            yield TextMessage(content=f"[{self.name}] 错误: 处理失败 - {e}", source=self.name, role="assistant")
            yield TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
            return

    # ... existing code ...
    # ... rest of the original code ...
    # ... existing code ... 