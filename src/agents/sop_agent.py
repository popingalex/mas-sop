from typing import Optional, List, Dict, Any, AsyncGenerator, Union, Callable
from pydantic import BaseModel
from loguru import logger
import hashlib
import asyncio
import logging

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage, ChatMessage
from autogen_core.models import ChatCompletionClient, SystemMessage
from autogen_core import CancellationToken

from ..tools.plan.manager import PlanManager
from src.types.plan import Plan, Step
from ..config.parser import AgentConfig
from ..types import JudgeDecision
from autogen_agentchat.tools import AgentTool
from autogen_agentchat.base._handoff import Handoff

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
请严格遵循以下要求：

1. 任务执行
- 必须严格按照给定的计划（plan_id）推进所有任务，不允许随意创建新计划或子计划，除非有明确指令。
- 每次收到任务时，先简要复述任务内容，包括计划ID、步骤ID、任务ID、任务名称、任务描述。
- 明确说明你的处理思路和执行过程。
- 任务完成后，简要总结本次任务的结果。
- **只有当前任务的Assignee（负责人）才可以修改该任务的状态，非Assignee只能添加Note，不得变更任务状态。**
- **所有工具调用必须基于真实、精确的ID参数（如plan_id、step_id、task_id），严禁凭空猜测或假设ID。**
- **如果只提供了计划ID，必须先用get_plan工具查询计划结构和最新任务，再推进后续操作。**
- **工具调用前，务必先通过get_plan/get_task等工具获取到最新的ID。**

2. 任务流转与handoff
- 如果计划还未全部完成，必须明确指出下一个要执行的任务，包括计划ID、步骤ID、任务ID、任务名称、任务描述、负责人（assignee）。
- 用自然语言表达"将任务转交给该负责人"，如：
  - "接下来由【XXX】负责执行下一个任务。"
  - "请【XXX】继续完成后续任务。"
- 如果需要handoff，直接用自然语言说明，并确保LLM能够理解handoff对象。

3. 计划终止
- 如果所有任务都已完成，请用自然语言说明计划已全部完成，例如：
  - "所有任务已完成，计划执行结束。"
- 不要遗漏任何终止信号。

4. 工具调用
- 你只能使用系统提供的工具（如get_task、update_task）来推进任务，不允许随意调用create_sub_plan等创建新计划的工具，除非有明确指令。
- 工具调用时要确保参数准确，避免无效调用。
- **调用update_task时，只有Assignee可以变更任务状态，非Assignee只能添加Note。**

5. 其他约束
- 回复内容要简洁明了，避免冗余。
- 不要重复执行已完成的任务。
- 不要擅自更改任务分配。
- 如遇到异常或无法推进，请用自然语言说明原因。
- 遇到任务ID/步骤ID错误时，只能请求更多信息或等待人工干预，不能自作主张分解任务或创建新计划。

严格按照以上要求推进每一步业务。
"""
    SOP_DEBUG_MESSAGE = (
        "重要！！！现在是调试流程阶段，请直接把分配给你的任务状态更新为'完成'，不需要真的执行任务！！！"
    )
    
    def __init__(
        self,
        name: str,
        model_client: Any,
        plan_manager: PlanManager,
        agent_config: AgentConfig,
        turn_manager: TurnManager,  # 必须传入，提前到可选参数前
        prompt: Optional[str] = None,
        artifact_manager: Optional[Any] = None,
        handoffs: Optional[List[Handoff | str]] = None,
        tools: Optional[List[Callable]] = [],  # 显式声明tools参数
        **kwargs,
    ):
        assert turn_manager is not None, "turn_manager 不能为空，必须传入 TurnManager 实例"
        self.handoffs = handoffs  # 保持与父类一致，None即为None
        # 只注册LLM需要的推进/查询/更新类方法为工具（排除create_plan）
        plan_tools = [
            plan_manager.get_plan,
            plan_manager.create_sub_plan,
            plan_manager.get_task,
            plan_manager.update_task,
        ]
        
        super().__init__(
            name=name,
            tools=list(set(tools + plan_tools)),
            model_client=model_client,
            system_message=None,
            handoffs=handoffs
        )
        # 1. 注入自我认知system_message
        self._system_messages.append(SystemMessage(content=f"你是{self.name}"))
        # 2. 注入配置文件自定义prompt（如有）
        self._system_messages.append(SystemMessage(content=prompt))
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


    def _extract_task(self, messages: List[BaseChatMessage]) -> str:
        """从消息列表中提取最后一条用户消息作为任务。"""
        if not messages:
            return ""
        for msg in reversed(messages):
            if msg.source == "user":
                return msg.content
        return ""

    def _has_search_tool(self) -> bool:
        """检查是否有搜索工具。"""
        assigned_tools = getattr(self.agent_config, 'assigned_tools', None)
        if assigned_tools and isinstance(assigned_tools, (list, dict)):
            return "search" in assigned_tools
        return False

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
        # 只做最小覆盖，直接交由LLM根据提示词和工具链推进业务
        async for event in super().on_messages_stream(messages, cancellation_token, **kwargs):
            yield event 