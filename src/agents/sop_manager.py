from typing import Optional, List, Dict, Any, AsyncGenerator, Sequence, cast
from uuid import UUID
from loguru import logger
import traceback
import json

from autogen_agentchat.messages import TextMessage, BaseChatMessage, BaseTextChatMessage
from autogen_agentchat.base import Response

from autogen_core.models import ChatCompletionClient
from autogen_core import MessageContext

from .sop_agent import SOPAgent
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

class SOPManager(SOPAgent):
    """SOPManager: 只负责SOP计划创建和任务分派，不直接推进或更新计划。"""

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
        super().__init__(
            name=name,
            agent_config=agent_config,
            model_client=model_client,
            plan_manager=plan_manager,
            artifact_manager=artifact_manager,
            system_message=system_message,
            **kwargs
        )
        self.team_config = team_config
        self.current_plan_id: Optional[UUID] = None
        self.last_dispatched_step: Optional[Step] = None
        logger.info(f"[{self.name}] Initialized. PlanManager tools are available.")

    async def on_messages_stream(
        self,
        messages: List[BaseChatMessage],
        ctx: MessageContext,
        **kwargs,
    ) -> AsyncGenerator[BaseChatMessage, None]:
        logger.info(f"[{self.name}] on_messages_stream called. messages={messages}, ctx={ctx}, kwargs={kwargs}")
        inner_messages = []
        final_msg = None
        try:
            if not messages:
                logger.warning(f"[{self.name}]: Received empty messages list")
                final_msg = TextMessage(content=f"[{self.name}] 错误: 没有收到任何消息", source=self.name, role="assistant")
                yield final_msg
                inner_messages.append(final_msg)
            else:
                last_message = messages[-1]
                last_message_content = last_message.content if last_message else ""
                logger.info(f"[{self.name}] last_message: {last_message}")

                if last_message.source == "user":
                    logger.info(f"[{self.name}] 进入用户消息分支，尝试创建计划")
                    try:
                        if self.team_config and self.team_config.workflows:
                            workflow = self.team_config.workflows[0]
                            plan_resp = self.plan_manager.create_plan(
                                title=f"处理任务: {last_message_content[:50]}...",
                                description=last_message_content,
                                steps=workflow.steps if workflow else None
                            )
                            logger.info(f"[{self.name}] plan_manager.create_plan返回: {plan_resp}")
                            if plan_resp and plan_resp.get("status") == "success":
                                plan_obj = Plan.parse_obj(plan_resp["data"])
                                if plan_obj.steps:
                                    # 找到第一个未完成的step和其下第一个未完成的task
                                    first_pending_step = next((s for s in plan_obj.steps if s.status != "completed"), None)
                                    first_pending_task = None
                                    if first_pending_step and first_pending_step.tasks:
                                        first_pending_task = next((t for t in first_pending_step.tasks if t.status != "completed"), None)
                                    if first_pending_step and first_pending_task:
                                        assignment_message = (
                                            f"HANDOFF_TO_{first_pending_task.assignee or first_pending_step.assignee}\n"
                                            f"NEXUS_ASSIGNMENT:\n"
                                            f"PLAN_ID: {plan_obj.id}\n"
                                            f"PLAN_TITLE: {plan_obj.title}\n"
                                            f"STEP_ID: {first_pending_step.id}\n"
                                            f"STEP_NAME: {first_pending_step.name}\n"
                                            f"TASK_ID: {first_pending_task.id}\n"
                                            f"TASK_NAME: {first_pending_task.name}\n"
                                            f"DESCRIPTION: {first_pending_task.description}\n"
                                            f"--- END OF ASSIGNMENT ---"
                                        )
                                        final_msg = TextMessage(
                                            content=assignment_message,
                                            source=self.name,
                                            role="assistant"
                                        )
                                        yield final_msg
                                        inner_messages.append(final_msg)
                                    else:
                                        final_msg = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                                        yield final_msg
                                        inner_messages.append(final_msg)
                                else:
                                    final_msg = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                                    yield final_msg
                                    inner_messages.append(final_msg)
                            else:
                                final_msg = TextMessage(content=f"[{self.name}] 错误: 创建计划失败: " + plan_resp.get("message", "未知错误"), source=self.name, role="assistant")
                                yield final_msg
                                inner_messages.append(final_msg)
                                final_msg2 = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                                yield final_msg2
                                inner_messages.append(final_msg2)
                        else:
                            final_msg = TextMessage(content=f"[{self.name}] 错误: 任务需要制定计划，但没有配置 SOP 模板。", source=self.name, role="assistant")
                            yield final_msg
                            inner_messages.append(final_msg)
                            final_msg2 = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                            yield final_msg2
                            inner_messages.append(final_msg2)
                    except Exception as e:
                        logger.exception(f"[{self.name}]: 创建计划失败: {e}")
                        final_msg = TextMessage(content=f"[{self.name}] 错误: 创建计划失败 - {e}", source=self.name, role="assistant")
                        yield final_msg
                        inner_messages.append(final_msg)
                        final_msg2 = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                        yield final_msg2
                        inner_messages.append(final_msg2)
                elif last_message.source != "user" and "TASK_COMPLETE" in last_message_content:
                    logger.info(f"[{self.name}] 进入TASK_COMPLETE分支")
                    try:
                        plan_resp = self.plan_manager.get_plan()
                        logger.info(f"[{self.name}] plan_manager.get_plan返回: {plan_resp}")
                        if plan_resp and plan_resp.get("status") == "success":
                            plan_obj = Plan.parse_obj(plan_resp["data"])
                            # 找到下一个未完成的step和其下第一个未完成的task
                            next_pending_step = next((s for s in plan_obj.steps if s.status != "completed"), None)
                            next_pending_task = None
                            if next_pending_step and next_pending_step.tasks:
                                next_pending_task = next((t for t in next_pending_step.tasks if t.status != "completed"), None)
                            if next_pending_step and next_pending_task:
                                assignment_message = (
                                    f"HANDOFF_TO_{next_pending_task.assignee or next_pending_step.assignee}\n"
                                    f"NEXUS_ASSIGNMENT:\n"
                                    f"PLAN_ID: {plan_obj.id}\n"
                                    f"PLAN_TITLE: {plan_obj.title}\n"
                                    f"STEP_ID: {next_pending_step.id}\n"
                                    f"STEP_NAME: {next_pending_step.name}\n"
                                    f"TASK_ID: {next_pending_task.id}\n"
                                    f"TASK_NAME: {next_pending_task.name}\n"
                                    f"DESCRIPTION: {next_pending_task.description}\n"
                                    f"--- END OF ASSIGNMENT ---"
                                )
                                final_msg = TextMessage(
                                    content=assignment_message,
                                    source=self.name,
                                    role="assistant"
                                )
                                yield final_msg
                                inner_messages.append(final_msg)
                            else:
                                final_msg = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                                yield final_msg
                                inner_messages.append(final_msg)
                        else:
                            final_msg = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                            yield final_msg
                            inner_messages.append(final_msg)
                    except Exception as e:
                        logger.exception(f"[{self.name}]: 计划推进失败: {e}")
                        final_msg = TextMessage(content=f"[{self.name}] 错误: 计划推进失败 - {e}", source=self.name, role="assistant")
                        yield final_msg
                        inner_messages.append(final_msg)
                        final_msg2 = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                        yield final_msg2
                        inner_messages.append(final_msg2)
                else:
                    logger.info(f"[{self.name}] 进入兜底分支，yield: ALL_TASKS_DONE")
                    final_msg = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                    yield final_msg
                    inner_messages.append(final_msg)
        except Exception as e:
            logger.exception(f"[{self.name}] Exception in on_messages_stream: {e}")
            final_msg = TextMessage(content=f"[{self.name}] Exception in on_messages_stream: {e}", source=self.name, role="assistant")
            yield final_msg
            inner_messages.append(final_msg)
        # 最后yield一个Response，chat_message为最后一条TextMessage，inner_messages为所有yield过的消息
        if final_msg is not None:
            yield Response(chat_message=final_msg, inner_messages=inner_messages)

    # ... existing code ...
    # ... rest of the original code ...
    # ... existing code ... 