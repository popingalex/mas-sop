from typing import Optional, List, Any, AsyncGenerator, Dict, Sequence
from loguru import logger

from pydantic import BaseModel

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage, StructuredMessage
from autogen_core.models import SystemMessage, UserMessage
from src.types import TeamConfig
from ..tools.plan.manager import PlanManager
from ..llm.utils import maybe_structured
from autogen_agentchat.base import Response, TaskResult
from ..tools.artifact_manager import ArtifactManager
from autogen_core import CancellationToken
from src.types.plan import Plan, PlanContext
import json

PROMPT_MATCH = """
请根据用户输入的任务，在SOP模板清单中查找最合适的匹配项。
按照如下JSON格式输出且仅输出匹配结果：
{{
  "task": "用户输入的任务",
  "name": "匹配项的name",
  "reason": "你选择该模板的理由"
}}
可选模板清单如下：
{templates}
"""

class MatchResult(BaseModel):
    task: str
    name: str
    reason: str

class Starter(AssistantAgent):
    """Starter: 只负责任务与SOP模板匹配，并自动创建计划。"""
    def __init__(self,
                 name: str,
                 model_client: Any,
                 team_config: TeamConfig,
                 plan_manager: PlanManager,
                 artifact_manager: ArtifactManager,
                 **kwargs):
        sop_templates = [
            {"name": plan.name, "description": plan.description}
            for plan in team_config.workflows
        ]
        templates = json.dumps(sop_templates, ensure_ascii=False, indent=2) if sop_templates else "无"
        system_message = PROMPT_MATCH.format(templates=templates)
        super().__init__(name=name, model_client=model_client, system_message=system_message, **kwargs)
        self.team_config = team_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager

    async def run(
        self,
        *,
        task: str | BaseChatMessage | Sequence[BaseChatMessage] | None = None,
        cancellation_token: CancellationToken | None = None,
    ) -> TaskResult:
        task_result = await super().run(task=task, cancellation_token=cancellation_token)
        try:
            user_message = task_result.messages[-1]
            parsed_user_message = MatchResult.model_validate_json(user_message.to_text())
            starter_result = self.artifact_and_plan(parsed_user_message)
            structured_msg = StructuredMessage[PlanContext](content=starter_result, source=self.name)
            return TaskResult(messages=[structured_msg])
        except Exception as e:
            logger.warning(f"[Starter] 匹配结果解析失败或计划创建失败: {e}")
            return task_result

    def artifact_and_plan(self, match_result: MatchResult) -> PlanContext:
        plan_tpl = next((tpl for tpl in self.team_config.workflows if tpl.name == match_result.name), None)
        if not plan_tpl:
            logger.warning(f"[Starter] 未找到计划模板: {match_result.name}")
            return None
        create_response = self.plan_manager.create_plan(
            id='0',
            name=plan_tpl.name,
            description=plan_tpl.description,
            steps=plan_tpl.steps,
            plan_name=plan_tpl.name
        )
        if not create_response or create_response.get('status') != 'success':
            logger.error(f"[Starter] 计划创建失败: {create_response}")
            return None
        plan_data = create_response['data']
        plan_obj = Plan.model_validate(plan_data)
        step_id = plan_obj.steps[0].id if plan_obj.steps else None
        task_id = plan_obj.steps[0].tasks[0].id if plan_obj.steps and plan_obj.steps[0].tasks else None
        # 保存初始资产
        artifact_title = f"SOP计划-{match_result.name}"
        artifact_content = match_result.model_dump(mode='json')
        artifact_desc = f"用户输入: {match_result.task}"
        result = self.artifact_manager.create_artifact(
            title=artifact_title,
            content=artifact_content,
            author=self.name,
            description=artifact_desc
        )
        artifact_id = result['data']['id'] if result.get('success') else None
        if result.get("success"):
            logger.info(f"[Starter] 已保存初始资产，artifact_id={artifact_id}")
        else:
            logger.warning(f"[Starter] 资产保存失败: {result.get('error')}") 
        # 返回所有关键ID
        return PlanContext(
            plan_id=plan_obj.id,
            artifact_id=artifact_id,
            event=match_result.task,
            step_id=step_id,
            task_id=task_id
        )