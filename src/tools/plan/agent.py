from typing import Optional, List, Dict, Any, Annotated
from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ModelClient
from .manager import PlanManager
from ..types import ResponseType # Import from parent tools directory

class PlanManagingAgent(AssistantAgent):
    """一个专门用于管理计划 (Plan) 和步骤 (Step) 的 Agent。

    它内部封装了一个 PlanManager 实例，并提供自然语言接口
    来调用计划管理功能。
    """
    def __init__(
        self,
        name: str = "PlanManagerAgent",
        plan_manager: Optional[PlanManager] = None,
        model_client: Optional[ModelClient] = None, # 需要一个 LLM 客户端来理解任务
        system_message: Optional[str] = None,
        **kwargs
    ):
        """初始化 PlanManagingAgent。

        Args:
            name: Agent 名称。
            plan_manager: PlanManager 的实例。如果未提供，将创建一个默认实例。
            model_client: 用于驱动 Agent 的 LLM 模型客户端。
            system_message: Agent 的系统消息。
            **kwargs: 传递给父类 AssistantAgent 的其他参数。
        """
        plan_manager = plan_manager if plan_manager is not None else PlanManager()
        self._plan_manager = plan_manager

        if system_message is None:
            system_message = (
                "You are a specialized assistant for managing hierarchical plans and their steps. "
                "Your goal is to understand user requests related to plan and step operations "
                "(creation, retrieval, listing, updating, deletion, adding notes) "
                "and use the provided tools to perform these actions."
            )

        super().__init__(name=name, system_message=system_message, model_client=model_client, tools=plan_manager.tool_list(), **kwargs)