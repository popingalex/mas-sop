from typing import Optional, List, Any, AsyncGenerator, Dict
from loguru import logger
import json
from pydantic import BaseModel

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage
from autogen_core.models import SystemMessage, UserMessage
from ..config.parser import TeamConfig
from ..tools.plan.manager import PlanManager
from ..llm.utils import maybe_structured
from autogen_agentchat.base import Response
from ..tools.artifact_manager import ArtifactManager

class MatchResult(BaseModel):
    task: str
    plan_id: str = "0"
    plan_name: str
    plan_description: str

PROMPT_MATCH = """
根据用户输入的任务在模板中查找匹配项，并按json格式返回：
{{ "name": 匹配项的name, "description": 匹配项的描述, "reason": 判断的理由 }}
用来匹配的模板如下：
{templates}
"""

class SOPStarter(AssistantAgent):
    """SOPStarter: 只负责任务与SOP模板匹配，并自动创建计划。"""
    def __init__(self, name: str, model_client: Any, team_config: TeamConfig, plan_manager: PlanManager, artifact_manager: ArtifactManager, **kwargs):
        super().__init__(name=name, model_client=model_client, **kwargs)
        self.team_config = team_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager

    async def on_messages_stream(self, messages: List[BaseChatMessage], *args, **kwargs) -> AsyncGenerator[BaseChatMessage, None]:
        user_message = messages[-1] if messages else None
        async for event in super().on_messages_stream(messages, *args, **kwargs):
            yield event
            if isinstance(event, Response):
                response_message = event.chat_message
                if isinstance(response_message, TextMessage) and user_message:
                    await self._handle_match_result(response_message, user_message)

    async def _handle_match_result(self, response_message: TextMessage, user_message: TextMessage):
        """
        解析LLM推理结果，自动创建计划并保存资产，task字段写入原始用户输入。
        """
        try:
            match_result = MatchResult.model_validate_json(response_message.content)
            # 覆盖/补充 task 字段为原始用户输入
            match_result.task = user_message.to_text() if hasattr(user_message, 'to_text') else user_message.content
        except Exception as e:
            logger.warning(f"[SOPStarter] 匹配结果解析失败: {e}")
            return None
        plan_tpl = next((tpl for tpl in self.team_config.workflows if tpl.name == match_result.plan_name), None)
        if not plan_tpl:
            logger.warning(f"[SOPStarter] 未找到计划模板: {match_result.plan_name}")
            return None
        plan_id = self.plan_manager.create_plan(
            name=plan_tpl.name,
            description=plan_tpl.description,
            steps=plan_tpl.steps,
            plan_name=plan_tpl.name,
            plan_index='0'
        )
        match_result.plan_id = plan_id
        # 保存初始资产
        artifact_title = f"SOP计划-{match_result.plan_name}"
        artifact_content = match_result.model_dump(mode='json')
        artifact_author = getattr(user_message, 'source', 'user')
        artifact_desc = f"用户输入: {match_result.task}"
        result = self.artifact_manager.create_artifact(
            title=artifact_title,
            content=artifact_content,
            author=artifact_author,
            description=artifact_desc
        )
        if result.get("success"):
            logger.info(f"[SOPStarter] 已保存初始资产，artifact_id={result['data']['id']}")
        else:
            logger.warning(f"[SOPStarter] 资产保存失败: {result.get('error')}") 