from typing import Optional, List, Dict, Any, AsyncGenerator, Union, Callable
from pydantic import BaseModel
from loguru import logger
import hashlib
import asyncio
import logging

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage, ChatMessage, HandoffMessage
from autogen_core.models import ChatCompletionClient, SystemMessage
from autogen_core import CancellationToken

from ..tools.plan.manager import PlanManager
from src.types.plan import Plan, Step
from ..config.parser import AgentConfig, TeamConfig
from ..types import JudgeDecision
from autogen_agentchat.tools import AgentTool
from autogen_agentchat.base._handoff import Handoff
from autogen_agentchat.base import Response

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
收到任务后，直接完成并将结果handoff回SOPManager。
不做任务分发、调度、复述或复杂推理。
"""
    SOP_DEBUG_MESSAGE = (
        "重要！！！直接把分配给的任务状态更新为'完成'，不需要真的执行任务！！！"
    )
    
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
        actions = None
        if agent_config and hasattr(agent_config, 'actions') and agent_config.actions:
            actions = agent_config.actions
        elif team_config is not None:
            # 兼容直接传入team_config的情况
            agent_entry = None
            if hasattr(team_config, 'agents'):
                for ag in team_config.agents:
                    if getattr(ag, 'name', None) == name:
                        agent_entry = ag
                        break
            if agent_entry and hasattr(agent_entry, 'actions'):
                actions = agent_entry.actions
        if actions:
            actions_str = '\n'.join(f'- {a}' for a in actions)
            self._system_messages.append(SystemMessage(content=f"--- 角色职责（actions） ---\n{actions_str}"))
        # 3. 注入系统内置行为约束（始终兜底）
        self._system_messages.append(SystemMessage(content=self.SOP_BEHAVIOR_REQUIREMENT))
        # 4. 调试提示（如有）
        self._system_messages.append(SystemMessage(content=self.SOP_DEBUG_MESSAGE))

        self.agent_config = agent_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager
        self.judge_agent = None
        self.turn_manager = turn_manager
        logger.info(f"[{self.name}] 已注册工具: {[t.__name__ if hasattr(t, '__name__') else str(t) for t in self._tools]}")
        logger.info(f"[{self.name}] 支持handoff给: {self.handoffs}")
        logger.info(f"[{self.name}] 提示词:")
        for msg in self._system_messages:
            if hasattr(msg, "content"):
                logger.info(f"\n--- {getattr(msg, 'type', '')} ---\n{msg.content}\n")
            else:
                logger.info(str(msg))

    async def quick_think(self, task_content: str):
        """快速思考，调用 judge_agent 判断任务类型。"""
        if not self.judge_agent:
            return None
        async for event in self.judge_agent.run(task_content):
            if isinstance(event, dict) and "chat_message" in event:
                msg = event["chat_message"]
                try:
                    from src.agents.judge import JudgeDecision
                    decision = JudgeDecision.model_validate_json(msg.content)
                    return decision
                except Exception as e:
                    logger.error(f"{self.name}: JudgeDecision parse error: {e}")
        return None
    
    async def on_messages_stream(self, messages: list[BaseChatMessage], cancellation_token=None, **kwargs):
        async for msg in super().on_messages_stream(messages, cancellation_token, **kwargs):
            print(f"{self.name} {type(msg)}================")
            # print(msg)
            # print(f"============================")
            # if isinstance(msg, Response):
            #     pass
            yield msg