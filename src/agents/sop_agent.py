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
from src.tools.plan.agent import PlanManagingAgent
from autogen_agentchat.tools import AgentTool

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
    """基础SOP智能体，仅注册PlanManagingAgent的标准工具，严格依赖外部注入turn_manager。"""
    SOP_BEHAVIOR_REQUIREMENT = (
        "你必须根据自身工具完成被分配的任务，并及时更新任务状态。"
    )
    SOP_DEBUG_MESSAGE = (
        "你不需要真的执行任务，只需假装自己完成了任务并更新状态。"
    )
    
    def __init__(
        self,
        name: str,
        model_client: Any,
        plan_manager: PlanManager,
        agent_config: AgentConfig,
        prompt: Optional[str] = None,  # 只写能力/风格/专业
        artifact_manager: Optional[Any] = None,
        turn_manager: TurnManager = None,
        debug: bool = False,
        **kwargs,
    ):
        plan_manager_agent = PlanManagingAgent(
            plan_manager=plan_manager,
            model_client=model_client
        )
        tools = kwargs.get('tools', [])
        tools = list(tools)
        tools.append(AgentTool(agent=plan_manager_agent))
        super().__init__(
            name=name,
            tools=tools,
            model_client=model_client,
            system_message=None
        )
        # 1. 自动添加身份设定
        self._system_messages.append(SystemMessage(content=f"你是{name}"))
        # 2. 能力/风格/专业描述（如有）
        if prompt:
            self._system_messages.append(SystemMessage(content=prompt))
        # 3. 行为约束
        self._system_messages.append(SystemMessage(content=self.SOP_BEHAVIOR_REQUIREMENT))
        # 4. 调试提示（如有）
        if debug:
            self._system_messages.append(SystemMessage(content=self.SOP_DEBUG_MESSAGE))
        self.agent_config = agent_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager
        self.judge_agent = None
        self.turn_manager = turn_manager
        logger.info(f"[{self.name}] 已注册工具: {[t.__name__ if hasattr(t, '__name__') else getattr(t, 'name', str(t)) for t in tools]}")
        logger.info(f"[{self.name}] 当前turn: {self.turn_manager.turn}")

    async def call_tool(self, tool_name: str, input: Any, **kwargs) -> Any:
        """
        调用已注册的标准工具。
        Args:
            tool_name: 工具名称
            input: 工具输入参数
            **kwargs: 其他参数
        Returns:
            Any: 工具执行结果
        Raises:
            ValueError: 如果工具未注册
        """
        logger = logging.getLogger("SOPAgent.call_tool")
        logger.info(f"[call_tool] tool_name={tool_name}, input={input}, kwargs={kwargs}")
        if tool_name not in self._tools:
            logger.error(f"Tool '{tool_name}' not found")
            raise ValueError(f"Tool '{tool_name}' not found")
        tool = self._tools[tool_name]
        try:
            if hasattr(tool, 'run'):
                result = await tool.run(input, **kwargs)
            else:
                result = await tool(input, **kwargs)
            logger.info(f"[call_tool] result={result}")
            return result
        except Exception as e:
            logger.error(f"[call_tool] 调用工具 '{tool_name}' 异常: {e}")
            raise

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

    async def on_messages(self, messages: list[BaseChatMessage], cancellation_token=None):
        logger.error(f"!!! {self.name}: on_messages 被调用 (turn={self.turn_manager.turn}) !!!")
        return await super().on_messages(messages, cancellation_token)

    async def on_messages_stream(self, messages: list[BaseChatMessage], cancellation_token=None, **kwargs):
        logger.info(f"{self.name}: on_messages_stream called. last message={messages[-1]}, turn={self.turn_manager.turn}")
        # 打印每条收到的消息内容
        for idx, msg in enumerate(messages):
            logger.info(f"{self.name}: 收到消息[{idx}] - source: {getattr(msg, 'source', None)}, content: {getattr(msg, 'content', None)}, turn={self.turn_manager.turn}")
        # 查找NEXUS_ASSIGNMENT任务内容并打印
        task_content = None
        for msg in messages:
            if msg.content and "NEXUS_ASSIGNMENT:" in msg.content:
                task_content = msg.content
                break
        logger.info(f"{self.name}: 传递给LLM的任务内容: {task_content}, turn={self.turn_manager.turn}")
        # 正确用法：async for + yield 代理父类
        async for event in super().on_messages_stream(messages, cancellation_token, **kwargs):
            yield event
        # 处理完消息后自增turn
        self.turn_manager.turn += 1 