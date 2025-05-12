from typing import Optional, List, Dict, Any, AsyncGenerator, Sequence, cast
from uuid import UUID
from loguru import logger
import traceback
import json

from autogen_agentchat.messages import TextMessage, BaseChatMessage, BaseTextChatMessage
from autogen_agentchat.base import Response

from autogen_core.models import ChatCompletionClient
from autogen_core import MessageContext

from .sop_agent import SOPAgent, TurnManager
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
        turn_manager: Optional[TurnManager] = None,
        **kwargs,
    ):
        super().__init__(
            name=name,
            agent_config=agent_config,
            model_client=model_client,
            plan_manager=plan_manager,
            artifact_manager=artifact_manager,
            turn_manager=turn_manager,
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
        logger.info(f"[{self.name}] on_messages_stream called. last message={messages[-1]}, ctx={ctx}, kwargs={kwargs}")
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
                                plan_id = plan_obj.id
                                # 推进逻辑：循环分派所有未完成task
                                pending_resp = self.plan_manager.get_pending(plan_id)
                                logger.info(f"[{self.name}] get_pending返回: {pending_resp}")
                                if pending_resp and pending_resp.get("status") == "success":
                                    data = pending_resp.get("data")
                                    if data and data.get("status") == "pending":
                                        step = data["step"]
                                        task = data["task"]
                                        # 分派任务前，检查 assignee 是否为空
                                        if not task.get("assignee"):
                                            logger.error(f"[SOPManager] 任务 {task.get('id')}（{task.get('name')}）未指定负责人，跳过分派。")
                                            final_msg = TextMessage(content=f"[SOPManager] 任务 {task.get('id')}（{task.get('name')}）未指定负责人，无法分派。", source=self.name, role="assistant")
                                            yield final_msg
                                            inner_messages.append(final_msg)
                                            return
                                        assignment_message = f"""
HANDOFF_TO_{task.get('assignee') or step.get('assignee')}
plan_id: {plan_id}
step_id: {step.get('id')}
task_id: {task.get('id')}""".strip()
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
                elif last_message.source != "user":
                    # 只要有新消息（如任务完成），都检查是否还有未完成task
                    try:
                        # 需要获取当前plan_id
                        plan_id = self.current_plan_id
                        if not plan_id and hasattr(self, 'plan_manager'):
                            # 尝试从plan_manager获取最后一个plan
                            plans = self.plan_manager.list_plans().get('data', [])
                            if plans:
                                plan_id = plans[-1]['id']
                        if not plan_id:
                            final_msg = TextMessage(content="ALL_TASKS_DONE", source=self.name, role="assistant")
                            yield final_msg
                            inner_messages.append(final_msg)
                        else:
                            pending_resp = self.plan_manager.get_pending(plan_id)
                            logger.info(f"[{self.name}] get_pending返回: {pending_resp}")
                            if pending_resp and pending_resp.get("status") == "success":
                                data = pending_resp.get("data")
                                if data and data.get("status") == "pending":
                                    step = data["step"]
                                    task = data["task"]
                                    assignment_message = f"""HANDOFF_TO_{task.get('assignee') or step.get('assignee')}
根据以下任务索引查询任务并执行
- plan_id: {plan_id}
- step_id: {step.get('id')}
- task_id: {task.get('id')}
"""
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
            if hasattr(self, 'turn_manager') and self.turn_manager:
                self.turn_manager.turn += 1

    # ... existing code ...
    # ... rest of the original code ...
    # ... existing code ... 