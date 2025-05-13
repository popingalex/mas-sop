from typing import Optional, List, Any, AsyncGenerator
from loguru import logger
import json

from autogen_agentchat.base import Response
from autogen_agentchat.messages import TextMessage, BaseChatMessage, ToolCallSummaryMessage

from autogen_core.models import ChatCompletionClient
from autogen_core import MessageContext
from autogen_core.models import SystemMessage, UserMessage
from .sop_agent import SOPAgent, TurnManager
from ..config.parser import AgentConfig, TeamConfig
from ..tools.plan.manager import PlanManager
from ..llm.utils import maybe_structured



PROMPT_MATCH = """
根据用户输入的任务在模板中查找匹配项，并按json格式返回：
{{ "name": 匹配项的name, "reason": 判断的理由 }}
用来匹配的模板如下：
{templates}
"""

PATTERN_DONE = "all_tasks_done"
PATTERN_TRANSFER = "transfer_to_{assignee}"

PROMPT_PROMOTE = f"""
查询计划，分析给定计划id对应的计划，然后进行以下行为中的一种：
1. 在所有步骤/任务完成完成，也就是cursor为空时，返回"{PATTERN_DONE}"。
2. 否则按以下json格式返回：
{{ plan: 计划id, step: 步骤id, task: 任务id, action: "{PATTERN_TRANSFER}" }}
"""



class SOPManager(SOPAgent):
    """SOPManager: 只负责SOP计划创建和任务分派，不直接推进或更新计划。"""

    def __init__(
        self,
        name: str,
        agent_config: AgentConfig,
        model_client: ChatCompletionClient,
        plan_manager: PlanManager,
        turn_manager: TurnManager,
        team_config: Optional[TeamConfig] = None,
        artifact_manager: Optional[Any] = None,
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
        self.counter = 0
        logger.info(f"[{self.name}] Initialized. PlanManager tools are available.")

    async def match_plan(self, message: TextMessage) -> AsyncGenerator[str, None]:
        sop_templates = [
            { "name": plan.name, "description": plan.description }
            for plan in self.team_config.workflows
        ]
        templates = json.dumps(sop_templates, ensure_ascii=False, indent=2) if sop_templates else "无"
        system_message = SystemMessage(content=PROMPT_MATCH.format(templates=templates))
        user_message = UserMessage(content=message.content, source=message.source)
        result = await self._model_client.create([system_message, user_message], json_output=True)
        match_result = maybe_structured(result.content)
        if match_result:
            logger.info(f"[{self.name}] 匹配到模板: {match_result['name']} 理由: {match_result['reason']}")
            return match_result['name']
        
    def create_plan_by_name(self, name: str) -> str:
        plan_tpl = next((tpl for tpl in self.team_config.workflows if tpl.name == name), None)
        if plan_tpl:
            self.plan_manager.create_plan(
                name=plan_tpl.name,
                description=plan_tpl.description,
                steps=plan_tpl.steps,
                plan_name=plan_tpl.name,
                plan_index='0'
            )
            return '0'

    async def on_messages_stream(
        self,
        messages: List[BaseChatMessage],
        ctx: MessageContext,
        **kwargs,
    ) -> AsyncGenerator[BaseChatMessage, None]:
        # 递归保护counter
        if not hasattr(self, "counter"):
            self.counter = 0
        self.counter += 1
        if self.counter > 5:
            raise Exception("递归死循环保护：counter > 5")
        logger.info(f"[{self.name}] on_messages_stream called. last message={messages[-1]}, ctx={ctx}, kwargs={kwargs}")
        if not messages:
            msg = TextMessage(content=f"[{self.name}] 错误: 没有收到任何消息", source=self.name, role="assistant")
            yield msg
            return

        # 如果是首次用户输入，先做plan匹配和创建
        last_message = messages[-1]
        if last_message.source == "user":
            result = await self.match_plan(last_message)
            plan_id = self.create_plan_by_name(result)
            self._system_messages.clear()
            self._system_messages.append(SystemMessage(content=PROMPT_PROMOTE))
            fck = TextMessage(content=f"计划已创建，id为: {plan_id}", source=self.name)
            messages = messages + [fck]
            yield fck

        # 主推进循环，无论消息来源
        max_rounds = 10
        rounds = 0
        while rounds < max_rounds:
            logger.info(f"[{self.name}] 推进计划循环第{rounds+1}次")
            # last_valid_event = None
            async for event in super().on_messages_stream(messages, ctx, **kwargs):
                yield event
                if isinstance(event, Response):
                    chat_message = event.chat_message
                    if isinstance(chat_message, (TextMessage, ToolCallSummaryMessage)):
                        content = chat_message.content
                        if content and ("all_tasks_done" in content or "transfer_to" in content):
                            return

            rounds += 1
        else:
            yield TextMessage(content="推进计划超出最大轮数，可能存在异常。", source=self.name)
        return