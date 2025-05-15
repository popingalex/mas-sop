from typing import Any
from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import SystemMessage
from ..tools.plan.manager import PlanManager
from ..tools.artifact_manager import ArtifactManager
from ..config.parser import TeamConfig

PROMPT_REVIEW = """
你是一个专业的SOP Reviewer。用户会输入一个结构化的PlanContext对象（JSON），请先通过plan_id调用get_plan工具获取计划详情，然后基于获取到的计划内容，输出结构化总结。
只输出如下JSON格式的总结，不要输出计划详情原文、工具调用过程或其他内容：
{
  "plan_id": "计划ID",
  "summary": "对整个计划执行过程的简要总结",
  "key_findings": ["主要发现1", "主要发现2"],
  "improvements": ["可改进点1", "可改进点2"],
  "lessons_learned": ["经验教训1", "经验教训2"]
}
如无内容可填请用空字符串或空数组，不要省略字段。
用户输入示例：{"event": "review", "plan_id": "0", "artifact_id": "xxx", "step_id": "1", "task_id": "2"}
"""

class Reviewer(AssistantAgent):
    """Reviewer: 负责输出SOP计划执行总结。"""
    def __init__(self,
                 model_client: Any,
                 plan_manager: PlanManager,
                 artifact_manager: ArtifactManager,
                 team_config: TeamConfig = None,
                 **kwargs):
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager
        self.team_config = team_config
        super().__init__(name="Reviewer",
                         tools=[plan_manager.get_plan] + artifact_manager.tool_list(),
                         model_client=model_client,
                         system_message=PROMPT_REVIEW,
                         reflect_on_tool_use=True,
                         **kwargs) 