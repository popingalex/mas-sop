from typing import Optional, List, Dict, Any, AsyncGenerator, Union
from pydantic import BaseModel
from loguru import logger

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage
from autogen_core.models import ChatCompletionClient
from autogen_core import CancellationToken

from ..tools.plan.manager import PlanManager
from ..tools.plan.types import Plan, Step
from ..config.parser import AgentConfig
from .judge_agent import JudgeAgent, JudgeDecision

from ..types import AgentConfig, JudgeDecision

class SOPAgent(AssistantAgent):
    """执行 SOP 工作流的智能体。
    
    工作流程：
    1. 快速思考：使用 JudgeAgent 分析任务类型
    2. 根据类型处理：
       - PLAN: 使用 PlanManager 生成计划
       - SIMPLE: 直接处理
       - SEARCH: 如果有搜索工具则处理，否则退回
       - UNCLEAR: 直接退回，表示任务描述不清晰或缺少必要信息
    3. 执行任务：使用 LLM 处理任务
    """

    def __init__(
        self,
        name: str,
        agent_config: AgentConfig,
        model_client: ChatCompletionClient,
        plan_manager: PlanManager,
        artifact_manager: Optional[Any] = None,
        system_message: Optional[str] = "",
        tools: Optional[List[Any]] = None,
        **kwargs,
    ):
        self.agent_config = agent_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager
        self.model_client = model_client

        # 初始化 JudgeAgent
        self.judge_agent = None
        if agent_config.sop_templates is not None:
            self.judge_agent = JudgeAgent(
                model_client=model_client,
                name=f"{name}_Judge",
                sop_definitions=agent_config.sop_templates,
                caller_name=name,
            )
            logger.info(f"Internal JudgeAgent '{self.judge_agent.name}' created.")

        # 构建系统提示
        base_system_message = system_message or agent_config.prompt or ""
        core_instructions = """
        You are an agent designed to execute tasks as part of a larger workflow.
        You will receive tasks that have been pre-analyzed by a JudgeAgent.
        Some tasks may come with a plan context that you should follow.
        Use your tools and capabilities to achieve the task goals.
        Always communicate your status and results clearly.
        """
        self.system_message = f"{base_system_message.strip()}\n\n{core_instructions.strip()}"

        super().__init__(
            name=name,
            system_message=self.system_message,
            model_client=model_client,
            tools=tools,
            **kwargs,
        )

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
        return bool(self.agent_config.assigned_tools and "search" in self.agent_config.assigned_tools)

    async def quick_think(self, task: str) -> Optional[JudgeDecision]:
        """快速思考，判断任务类型。
        
        Args:
            task: 需要分析的任务描述
            
        Returns:
            Optional[JudgeDecision]: 判断结果，如果发生错误则返回 None
            
        Raises:
            None: 所有异常都会被捕获并记录
        """
        if not self.judge_agent:
            logger.debug(f"{self.name}: No JudgeAgent available, skipping quick think")
            return None

        try:
            logger.debug(f"{self.name}: Starting quick think for task: {task[:100]}...")
            response_gen = self.judge_agent.run(task)
            
            try:
                response = await anext(response_gen)
            except StopAsyncIteration:
                logger.error(f"{self.name}: JudgeAgent returned empty response")
                return None
            except Exception as e:
                logger.error(f"{self.name}: Error getting response from JudgeAgent: {str(e)}")
                return None

            if not response:
                logger.error(f"{self.name}: Empty response from JudgeAgent")
                return None
                
            if not response.get("chat_message"):
                logger.error(f"{self.name}: No chat message in response: {response}")
                return None

            decision_json = response["chat_message"].content
            
            try:
                decision = JudgeDecision.model_validate_json(decision_json)
                logger.info(f"{self.name}: Task analyzed as {decision.type} with confidence {decision.confidence}")
                return decision
            except ValueError as e:
                logger.error(f"{self.name}: Invalid decision format: {str(e)}")
                return None
            
        except Exception as e:
            logger.error(f"{self.name}: Unexpected error in quick_think: {str(e)}", exc_info=True)
            return None

    async def _process_plan(self, plan: Union[Plan, dict]) -> AsyncGenerator[Dict[str, Any], None]:
        """处理计划任务。"""
        if isinstance(plan, dict):
            steps = [Step(**step) for step in plan.pop("steps", [])]
            plan = Plan(**plan)
            plan.steps = steps
            
        for step in plan.steps:
            try:
                # 执行步骤
                response = await self.llm_cached_aask(
                    f"Execute plan step: {step.description}",
                    raise_on_timeout=True,
                )
                
                # 更新步骤状态
                step.status = "completed"
                
                # 返回结果
                yield {
                    "chat_message": TextMessage(
                        content=response,
                        source=self.name
                    )
                }
            except Exception as e:
                logger.error(f"Error executing plan step {step.index}: {e}")
                step.status = "failed"
                yield {
                    "chat_message": TextMessage(
                        content=f"Failed to execute step {step.index}: {str(e)}",
                        source=self.name
                    )
                }

    async def on_messages_stream(
        self,
        messages: List[BaseChatMessage],
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """处理消息流。"""
        task = self._extract_task(messages)
        if not task:
            yield {
                "chat_message": TextMessage(
                    content="No task found in messages.",
                    source=self.name
                )
            }
            return

        try:
            # 快速思考
            decision = await self.quick_think(task)
            if not decision:
                # 如果没有 JudgeAgent，直接作为简单任务处理
                response = await self.llm_cached_aask(task, raise_on_timeout=True)
                yield {
                    "chat_message": TextMessage(
                        content=response,
                        source=self.name
                    )
                }
                return

            # 根据任务类型处理
            if decision.type == "PLAN":
                # 创建并执行计划
                plan = await self.plan_manager.create_plan(task)
                async for result in self._process_plan(plan):
                    yield result

            elif decision.type == "SIMPLE":
                # 直接处理简单任务
                response = await self.llm_cached_aask(task, raise_on_timeout=True)
                yield {
                    "chat_message": TextMessage(
                        content=response,
                        source=self.name
                    )
                }

            elif decision.type == "SEARCH":
                # 检查是否有搜索工具
                if not self._has_search_tool():
                    yield {
                        "chat_message": TextMessage(
                            content="Search capability required but not available.",
                            source=self.name
                        )
                    }
                    return

                # 使用搜索工具处理
                response = await self.llm_cached_aask(task, raise_on_timeout=True)
                yield {
                    "chat_message": TextMessage(
                        content=response,
                        source=self.name
                    )
                }

            else:  # UNCLEAR
                yield {
                    "chat_message": TextMessage(
                        content="Task is unclear or lacks necessary information. Please provide more details.",
                        source=self.name
                    )
                }

        except Exception as e:
            logger.error(f"Error in on_messages_stream: {e}")
            yield {
                "chat_message": TextMessage(
                    content=f"An error occurred while processing the task: {str(e)}",
                    source=self.name
                )
            }

    async def llm_cached_aask(self, message: str, raise_on_timeout: bool = False) -> str:
        """调用 LLM 并缓存结果。
        
        Args:
            message: 要发送给 LLM 的消息
            raise_on_timeout: 是否在超时时抛出异常
            
        Returns:
            str: LLM 的响应内容
            
        Raises:
            TimeoutError: 如果 raise_on_timeout=True 且发生超时
            Exception: 如果 raise_on_timeout=True 且发生其他错误
        """
        try:
            response = await self.model_client.create(
                messages=[
                    {"role": "system", "content": self.system_message},
                    {"role": "user", "content": message}
                ]
            )
            
            logger.debug(f"{self.name}: Raw LLM response: {response}")
            
            if not response:
                raise Exception("No response from LLM")
            
            # 处理不同类型的响应
            if isinstance(response, str):
                logger.debug(f"{self.name}: Response is string: {response}")
                return response
            elif isinstance(response, dict):
                logger.debug(f"{self.name}: Response is dict with keys: {list(response.keys())}")
                
                # DeepSeek API 格式
                if "choices" in response and response["choices"]:
                    choice = response["choices"][0]
                    logger.debug(f"{self.name}: Found choices, first choice: {choice}")
                    if isinstance(choice, dict):
                        if "message" in choice:
                            message = choice["message"]
                            if isinstance(message, dict) and "content" in message:
                                content = message["content"]
                                logger.debug(f"{self.name}: Found content in message: {content}")
                                return content
                            elif isinstance(message, str):
                                logger.debug(f"{self.name}: Message is string: {message}")
                                return message
                        elif "text" in choice:
                            text = choice["text"]
                            logger.debug(f"{self.name}: Found text in choice: {text}")
                            return text
                
                # 其他可能的格式
                if "content" in response:
                    content = response["content"]
                    logger.debug(f"{self.name}: Found content in response: {content}")
                    return content
                elif "message" in response:
                    message = response["message"]
                    logger.debug(f"{self.name}: Found message in response: {message}")
                    if isinstance(message, dict):
                        if "content" in message:
                            content = message["content"]
                            logger.debug(f"{self.name}: Found content in message dict: {content}")
                            return content
                    return str(message)
                
                # 如果找不到预期的字段，返回整个响应的字符串表示
                logger.warning(f"{self.name}: No standard fields found in response: {response}")
                return str(response)
            else:
                logger.warning(f"{self.name}: Response is neither string nor dict: {type(response)}")
                return str(response)
                
        except Exception as e:
            error_msg = str(e)
            logger.error(f"{self.name}: Error in llm_cached_aask: {error_msg}")
            if raise_on_timeout:
                raise
            return error_msg