from typing import Optional, List, Dict, Any, AsyncGenerator, Union, Callable
from pydantic import BaseModel
from loguru import logger
import hashlib
import asyncio
import logging
import yaml
import json

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage, ChatMessage, HandoffMessage
from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage
from autogen_core import CancellationToken
from autogen_core.tools import FunctionTool, BaseTool
from autogen_core.models._types import FunctionCall
from autogen_core.models import AssistantMessage

from ..tools.plan.manager import PlanManager
from src.types.plan import Plan, Step
from src.types import AgentConfig, TeamConfig
from ..types import JudgeDecision
from autogen_agentchat.tools import AgentTool
from autogen_agentchat.base._handoff import Handoff
from autogen_agentchat.base import Response
from autogen_agentchat.messages import BaseAgentEvent
# 新增TurnManager类
class TurnManager:
    def __init__(self) -> None:
        self._turn = 0
    @property
    def turn(self) -> int:
        return self._turn
    @turn.setter
    def turn(self, value: int) -> None:
        self._turn = value
    def __iadd__(self, value: int) -> 'TurnManager':
        self._turn += value
        return self

class SOPAgent(AssistantAgent):
    """基础SOP智能体，使用PlanManager的标准工具，严格依赖外部注入turn_manager。"""
    SOP_BEHAVIOR_REQUIREMENT = """
你只负责接收并完成分配给你的任务。
收到任务后，必须严格按照以下顺序操作：
1. 每次执行任务前，务必主动查询任务和计划的最新状态（如 get_task 或 get_plan），以判断当前任务是否有关联的子计划，并据此推进。
2. 所有工具调用必须严格遵循工具说明文档（docstring），包括幂等性、前置条件、错误处理等。
3. 禁止跳步、合并操作或只执行其中一项。
"""
    SOP_DEBUG_MESSAGE = """
重要：所有工具调用必须严格遵循工具说明文档（docstring），遇到错误或特殊返回值时，按工具文档处理，不要自行猜测或重复操作。
无需解释原因，也无需说明任务执行过程。
"""
    
    def __init__(
        self,
        model_client: Any,
        plan_manager: PlanManager,
        team_config: TeamConfig,  # 新增参数
        agent_config: AgentConfig,
        turn_manager: TurnManager,  # 必须传入，提前到可选参数前
        artifact_manager: Optional[Any] = None,
        handoffs: Optional[List[Handoff | str]] = None,
        tools: Optional[List[Callable]] = [],  # 显式声明tools参数
        **kwargs,
    ):
        assert turn_manager is not None, "turn_manager 不能为空，必须传入 TurnManager 实例"
        self.handoffs = handoffs  # 保持与父类一致，None即为None
        self.team_config = team_config  # 保存team_config
        # 只注册LLM需要的推进/查询/更新类方法为工具（排除create_plan）
        plan_tools = [
            plan_manager.get_plan,
            plan_manager.create_sub_plan,
            plan_manager.get_task,
            plan_manager.update_task,
        ]

        super().__init__(
            name=agent_config.name,
            tools=list(set(tools + plan_tools)),
            model_client=model_client,
            system_message=None,
            handoffs=handoffs
        )
        # 1. 注入自我认知system_message
        self._system_messages.append(SystemMessage(content=f"你是{self.name}"))
        # 2. 注入配置文件自定义prompt（如有）
        self._system_messages.append(SystemMessage(content=agent_config.prompt))
        # 2.5 注入actions（如有）
        if agent_config.actions:
            actions_yaml = yaml.dump({'角色能力': agent_config.actions}, allow_unicode=True, sort_keys=False)
            self._system_messages.append(SystemMessage(content=actions_yaml))
        # 3. 注入系统内置行为约束（始终兜底）
        self._system_messages.append(SystemMessage(content=self.SOP_BEHAVIOR_REQUIREMENT))
        # 4. 调试提示（如有）
        self._system_messages.append(SystemMessage(content=self.SOP_DEBUG_MESSAGE))

        self.agent_config = agent_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager
        self.judge_agent = None
        self.turn_manager = turn_manager
        msg_str = '\n'.join([msg.content for msg in self._system_messages])
        logger.info(f"[{self.name}] 提示词:{msg_str}")

    async def judge(self, task_content: str) -> JudgeDecision | None:
        from src.agents.judge import JUDGE_PROMPT, JudgeDecision
        from autogen_core.models import UserMessage
        # 适配 SOPManager YAML 格式 handoff message
        try:
            task_dict = yaml.safe_load(task_content)
            task_desc = task_dict.get("description", str(task_content))
        except Exception as e:
            logger.error(f"{self.name}: YAML解析失败: {e}, content: {task_content}")
            task_desc = str(task_content)
        messages = [
            SystemMessage(content=JUDGE_PROMPT),
            UserMessage(content=task_desc, source="user")
        ]
        logger.info(f"[judge] agent={self.name} 任务内容: {task_desc}")
        result = await self._model_client.create(
            messages,
            json_output=True  # 强制要求 LLM 输出纯 JSON
        )
        try:
            decision = JudgeDecision.model_validate_json(result.content)
            logger.info(f"[judge] agent={self.name} 判定结果: {decision.type}")
            return decision
        except Exception as e:
            logger.error(f"{self.name}: JudgeDecision parse error: {e}, content: {result.content}")
            return None
    
    async def create_sub_plan(self, task_content: str, parent_plan_info: dict = None) -> str:
        """调用 LLM 生成结构化子计划，并 function call create_sub_plan 工具。\n调用前需判断父任务是否已存在同 plan_id 的子计划，避免重复创建。"""
        team_actions = {agent.name: agent.actions for agent in self.team_config.agents}
        actions_yaml = yaml.dump({'团队成员能力': team_actions}, allow_unicode=True, sort_keys=False)
        plan_prompt = "你收到的任务较为复杂，请为该任务分解出一个包含多个步骤的子计划，并为每个子任务分配最合适的团队成员。"
        plan_messages = [
            SystemMessage(content=plan_prompt),
        ]
        # 父计划上下文补充
        parent_info_yaml = yaml.dump({'父任务标识': parent_plan_info}, allow_unicode=True, sort_keys=False)
        
        plan_messages.append(SystemMessage(content=parent_info_yaml))
        plan_messages.extend([
            SystemMessage(content=actions_yaml),
            SystemMessage(content="请直接调用 create_sub_plan 工具，参数需包含父计划/任务标识，输出结构化的子计划（每个子任务包含：步骤名称、描述、assignee）。"),
            UserMessage(content=task_content, source="user")
        ])
        plan_result = await self._model_client.create(
            plan_messages,
            tools=[FunctionTool(self.plan_manager.create_sub_plan, description=self.plan_manager.create_sub_plan.__doc__ or "")],
        )
        # 处理 function calling 返回
        if isinstance(plan_result.content, list):
            for call in plan_result.content:
                if isinstance(call, FunctionCall) and call.name == "create_sub_plan":
                    args = json.loads(call.arguments)
                    create_resp = self.plan_manager.create_sub_plan(**args)
                    plan_id = create_resp["data"]["id"] if create_resp.get("data") else None
                    return plan_id or str(create_resp)
        # 兼容 LLM 直接输出字符串的情况
        return str(plan_result.content)

    async def on_messages_stream(self, messages: list[BaseChatMessage], cancellation_token=None, **kwargs) -> AsyncGenerator[BaseAgentEvent | BaseChatMessage | Response, None]:
        yielded = False
        for msg in messages:
            if isinstance(msg, HandoffMessage) and msg.source == 'SOPManager':
                try:
                    task_dict = yaml.safe_load(msg.content)
                    parent_plan_info = {
                        "plan_id": task_dict.get("plan_id"),
                        "step_id": task_dict.get("step_id"),
                        "task_id": task_dict.get("task_id"),
                    }
                except Exception as e:
                    logger.error(f"handoff message YAML解析失败: {e}, content: {msg.content}")
                    parent_plan_info = None
                task_info = self.plan_manager.get_task(
                    plan_id=parent_plan_info["plan_id"],
                    step_id=parent_plan_info["step_id"],
                    task_id=parent_plan_info["task_id"]
                )
                sub_plans = []
                if task_info.get("status") == "success":
                    sub_plans = task_info["data"]["task"].get("sub_plans") or []
                    if sub_plans is not None and len(sub_plans) > 0:
                        logger.info(f"[on_messages_stream] 检测到已有子计划: {sub_plans}")
                logger.info(f"agent={self.name} 任务内容: {msg.content}，已有子计划: {sub_plans}")
                decision = await self.judge(msg.content)
                logger.info(f"agent={self.name} judge决策: {decision.type if decision else 'None'}，sub_plans: {sub_plans}")
                if decision and decision.type:
                    match decision.type.lower():
                        case "complex":
                            if sub_plans:
                                plan_ids = [sp["id"] for sp in sub_plans]
                                logger.info(f"agent={self.name} 已有子计划，跳过 create_sub_plan，plan_ids={plan_ids}")
                                plan_msg = TextMessage(
                                    content=f"子计划已存在，计划ID为 {plan_ids}，请等待所有子计划完成后父任务自动完成。",
                                    source=self.name
                                )
                                logger.info(f"agent={self.name} yield: {plan_msg.content}")
                                yield Response(chat_message=plan_msg)
                                yielded = True
                                await self._model_context.add_message(AssistantMessage(content=plan_msg.content, source=self.name))
                                return
                            else:
                                logger.info(f"agent={self.name} sub_plans 为空，准备调用 create_sub_plan")
                                plan_content = await self.create_sub_plan(msg.content, parent_plan_info=parent_plan_info)
                                logger.info(f"agent={self.name} create_sub_plan 返回: {plan_content}")
                                plan_msg = TextMessage(
                                    content=f"子计划已创建，计划ID为 {plan_content}，请等待所有子计划完成后父任务自动完成。",
                                    source=self.name
                                )
                                logger.info(f"agent={self.name} yield: {plan_msg.content}")
                                yield Response(chat_message=plan_msg)
                                yielded = True
                                await self._model_context.add_message(AssistantMessage(content=plan_msg.content, source=self.name))
                                return
                        case "simple":
                            logger.info(f"agent={self.name} simple 任务，走原有流程")
                            simple_msg = TextMessage(content="任务已完成。", source=self.name)
                            logger.info(f"agent={self.name} yield: {simple_msg.content}")
                            yield Response(chat_message=simple_msg)
                            yielded = True
                            await self._model_context.add_message(AssistantMessage(content=simple_msg.content, source=self.name))
                            return
        async for m in super().on_messages_stream(messages, cancellation_token, **kwargs):
            yield m
            yielded = True
        if not yielded:
            logger.warning(f"agent={self.name} 未产出任何响应，补充默认消息。")
            yield Response(chat_message=TextMessage(content="无操作，流程已结束。", source=self.name))