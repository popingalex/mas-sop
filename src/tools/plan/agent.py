from typing import Optional, AsyncGenerator
from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from .manager import PlanManager

class PlanManagingAgent(AssistantAgent):
    """一个专门用于管理计划 (Plan) 和步骤 (Step) 的 Agent。

    它内部封装了一个 PlanManager 实例，并注册其方法为tools。
    """
    def __init__(
        self,
        name: str = "PlanManagerAgent",
        plan_manager: Optional[PlanManager] = None,
        model_client: Optional[ChatCompletionClient] = None, # 需要一个 LLM 客户端来理解任务
        system_message: Optional[str] = None,
        **kwargs
    ):
        """初始化 PlanManagingAgent。"""
        plan_manager = plan_manager if plan_manager is not None else PlanManager()
        self._plan_manager = plan_manager

        description = (
            "PlanManagerAgent 负责计划（Plan）、步骤（Step）、任务（Task）的管理。\n"
            "所有ID均为字符串，不能用索引。\n"
            "主要接口：update_task(plan_id, step_id, task_id, update_data, author) ...\n"
            "调用本工具时，必须提供结构化参数，参数名与数据结构一致。\n"
            "请严格根据 assignment message 提取 plan_id、step_id、task_id、author 等字段。"
        )

        if system_message is None:
            system_message = (
                "You are a specialized assistant for managing hierarchical plans and their steps. "
                "Your goal is to understand user requests related to plan and step operations "
                "(creation, retrieval, listing, updating, deletion, adding notes) "
                "and use the provided tools to perform these actions."
            )

        super().__init__(
            name=name,
            system_message=system_message,
            model_client=model_client,
            tools=plan_manager.tool_list(),
            description=description,
            **kwargs
        )

    async def run_stream(self, task: str):
        """流式运行，yield 每一步 LLM 消息，兼容 test_judge.py 的调试方式。"""
        result = await self.run(task=task)
        yield result