from typing import Optional, AsyncGenerator
from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from .manager import PlanManager

class PlanManagerAgent(AssistantAgent):
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
        """初始化 PlanManagerAgent。"""
        plan_manager = plan_manager if plan_manager is not None else PlanManager()
        self._plan_manager = plan_manager

        description = """
PlanManagerAgent 负责计划（Plan）、步骤（Step）、任务（Task）的信息管理（查询、创建、更新、删除）。
不负责业务流转和实际任务执行。
调用本工具时，参数需结构化，且必须包含调用者真实身份（如author字段）。
"""

        if system_message is None:
            system_message = (
                "你是一个专门负责计划、步骤、任务信息管理的智能体，只能进行信息的查询、创建、更新、删除（CRUD）操作，不能主动执行业务任务。\n"
                "每次只能执行一次工具调用。如果用户的需求需要多步操作，请明确告知用户：你一次只能完成一个操作，请分步提出请求。\n"
                "如果用户提供的参数不完整或缺失（如缺少author、plan_id等），请直接回复缺少哪些参数，并用如下结构化格式返回：\n"
                "---\n"
                "你的请求内容: <原始请求/arguments>\n"
                "对应函数: <函数名>\n"
                "已解析参数: <已识别参数及其值>\n"
                "缺失参数: <缺失参数列表>\n"
                "格式错误: <如有格式错误请说明，否则可省略>\n"
                "---\n"
                "遇到非CRUD或业务流转类请求，请直接拒绝，并说明你的职责范围。\n"
                "请始终保持结构化、简洁、专业的回复。"
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