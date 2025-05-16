from typing import Optional, List, Any, AsyncGenerator
from loguru import logger
from autogen_agentchat.base import Response
from autogen_agentchat.messages import TextMessage, BaseChatMessage, HandoffMessage, LLMMessage, StructuredMessage
from autogen_core.models import ChatCompletionClient, SystemMessage
from autogen_core.models._types import UserMessage, AssistantMessage, FunctionExecutionResultMessage
from .sop_agent import SOPAgent, TurnManager
from src.types import AgentConfig, TeamConfig
from ..tools.plan.manager import PlanManager
from autogen_agentchat.agents import BaseChatAgent
from src.types.plan import PlanContext, Plan
from autogen_agentchat.conditions import FunctionalTermination
import yaml

class SOPManager(BaseChatAgent):
    """SOPManager: SOP计划调度者，负责推进和分发任务，不直接执行任务。"""
    PLAN_DONE_MESSAGE = "计划已全部完成"
    def __init__(
        self,
        plan_manager: PlanManager,
        team_config: Optional[TeamConfig] = None,
        artifact_manager: Optional[Any] = None,
        **kwargs,
    ):
        super().__init__(name="SOPManager", description="SOP计划调度者，负责推进和分发任务，不直接执行任务。")
        self.team_config = team_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager
        logger.info(f"[{self.name}] Initialized as SOPManager (调度者)")

    def get_termination_condition(self):
        """
        返回一个FunctionalTermination对象，自动根据消息流中的PlanContext判定计划是否完成。
        支持多计划/多次复用。
        """
        plan_manager = self.plan_manager
        async def plan_is_done(messages):
            for msg in messages:
                if isinstance(msg, StructuredMessage) and isinstance(msg.content, PlanContext):
                    plan_id = msg.content.plan_id
                    plan_response = plan_manager.get_plan(plan_id)
                    plan = Plan.model_validate(plan_response['data'])
                    if plan.status == 'completed':
                        return True
            return False
        return FunctionalTermination(plan_is_done)

    @property
    def produced_message_types(self):
        """本Agent可能产生的消息类型。"""
        return (StructuredMessage[PlanContext], HandoffMessage)

    async def get_next_task(self, plan_id: str) -> Optional[tuple]:
        """
        递归推进主计划和子计划，返回 (plan_id, step_id, task_id) 或 None（全部完成）。
        """
        plan_response = self.plan_manager.get_plan(plan_id)
        plan = plan_response["data"]
        plan_obj = Plan.model_validate(plan)
        if not plan_obj.next:
            return None
        step_id, task_id = plan_obj.next
        task = plan_obj.task_by_path(step_id, task_id)
        if task and task.sub_plans:
            for sub in task.sub_plans:
                if sub.status != 'completed':
                    return await self.get_next_task(sub.id)
            return await self.get_next_task(plan_id)
        else:
            return plan_id, step_id, task_id

    async def on_messages(self, messages, cancellation_token):
        for msg in messages:
            if isinstance(msg, StructuredMessage) and isinstance(msg.content, PlanContext):
                if msg.source == 'Starter':
                    self.plan_context = msg.content
                break
            else:
                print(f"{self.name} {type(msg)}================")
        plan_id = self.plan_context.plan_id
        plan_response = self.plan_manager.get_plan(plan_id)
        plan = plan_response["data"]
        plan_obj = Plan.model_validate(plan)
        if not plan or plan_obj.status == 'completed':
            logger.info(f"[SOPManager] 计划已完成: {plan_id}")
            return Response(chat_message=StructuredMessage[PlanContext](content=self.plan_context, source=self.name))

        next_task_info = await self.get_next_task(plan_id)
        if not next_task_info:
            logger.info(f"[SOPManager] 计划已完成: {plan_id}")
            return Response(chat_message=StructuredMessage[PlanContext](content=self.plan_context, source=self.name))
        plan_id, step_id, task_id = next_task_info
        plan_response = self.plan_manager.get_plan(plan_id)
        plan = plan_response["data"]
        plan_obj = Plan.model_validate(plan)
        task = plan_obj.task_by_path(step_id, task_id)
        assignee = task.assignee
        logger.info(f"[SOPManager] 分发任务: step={step_id}, task={task_id}, assignee={assignee}")
        task_desc_dict = {
            'task_name': task.name,
            'description': task.description,
            'plan_id': plan_id,
            'step_id': step_id,
            'task_id': task_id
        }
        task_desc = yaml.dump(task_desc_dict, allow_unicode=True, sort_keys=False)
        recent_context = [
            m for m in messages
            if isinstance(m, (SystemMessage, UserMessage, AssistantMessage, FunctionExecutionResultMessage))
        ][-2:]
        handoff_msg = HandoffMessage(
            source=self.name,
            target=assignee,
            content=task_desc,
            context=recent_context
        )
        return Response(chat_message=handoff_msg)

    async def on_reset(self, cancellation_token):
        """无状态可重置，直接pass。"""
        pass