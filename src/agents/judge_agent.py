import json
from typing import Dict, Any, Optional, List, Union, AsyncGenerator
from loguru import logger
from pydantic import BaseModel, Field

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient # Import needed type
from ..config.parser import LLMConfig
from autogen_agentchat.messages import TextMessage, BaseChatMessage

# Define the structured output format for the JudgeAgent
class JudgeDecision(BaseModel):
    """任务判断结果。"""
    type: str  # PLAN, SIMPLE, SEARCH, UNCLEAR
    confidence: float  # 0.0 - 1.0
    reason: str  # 判断原因


class JudgeAgent(AssistantAgent):
    """任务分析智能体。
    
    负责快速分析任务类型，返回判断结果。
    """

    def __init__(
        self,
        model_client: ChatCompletionClient,
        name: str,
        sop_definitions: Dict[str, Any],
        caller_name: str,
    ):
        """初始化 JudgeAgent。

        Args:
            model_client: LLM 客户端
            name: 智能体名称
            sop_definitions: SOP 定义字典
            caller_name: 调用者名称
        """
        self.sop_definitions = sop_definitions
        self.caller_name = caller_name

        # 构建系统提示
        system_message = f"""
        You are a highly efficient task analyzer invoked by '{caller_name}'.
        Your sole purpose is to analyze the given task description and classify its type.
        The possible types are:
        - PLAN: Requires a multi-step plan or Standard Operating Procedure (SOP)
        - SIMPLE: Can be handled directly without a plan
        - SEARCH: Requires searching or retrieving information
        - UNCLEAR: Task description is unclear or lacks necessary information

        Available SOPs:
        {json.dumps(list(sop_definitions.keys()), indent=2)}

        You must respond in JSON format with the following structure:
        {{
            "type": "PLAN|SIMPLE|SEARCH|UNCLEAR",
            "confidence": float,  # 0.0 to 1.0
            "reason": string  # Brief explanation of your decision
        }}
        """

        logger.info(f"Initialized JudgeAgent: {name} (called by {caller_name})")
        logger.debug(f"  Judge System Message Snippet: {system_message[:200]}...")
        logger.debug(f"  Judge Model Client: {model_client}")
        logger.debug(f"  Loaded SOP Definitions: {list(sop_definitions.keys())}")

        super().__init__(
            name=name,
            system_message=system_message,
            model_client=model_client,
        )

    async def run(self, task: str) -> AsyncGenerator[Dict[str, Any], None]:
        """运行任务分析。

        Args:
            task: 任务描述

        Returns:
            判断结果
        """
        try:
            # 分析任务
            response = await self.llm_cached_aask(
                task,
                raise_on_timeout=True,
            )

            # 解析响应
            try:
                decision = JudgeDecision.parse_raw(response)
                yield {
                    "chat_message": TextMessage(
                        content=decision.json(),
                        source=self.name
                    )
                }
            except Exception as e:
                logger.error(f"Failed to parse JudgeAgent response: {e}")
                yield {
                    "chat_message": TextMessage(
                        content=json.dumps({
                            "type": "UNCLEAR",
                            "confidence": 0.0,
                            "reason": f"Failed to parse response: {str(e)}"
                        }),
                        source=self.name
                    )
                }

        except Exception as e:
            logger.error(f"Error in JudgeAgent.run: {e}")
            yield {
                "chat_message": TextMessage(
                    content=json.dumps({
                        "type": "UNCLEAR",
                        "confidence": 0.0,
                        "reason": f"Error during analysis: {str(e)}"
                    }),
                    source=self.name
                )
            }

    # No internal tools needed for basic prompt-based lookup
    # If complex SOP searching is needed, add a dedicated tool here

    # JudgeAgent primarily relies on its prompt and LLM call via the parent's
    # message handling. It doesn't need complex overrides itself unless
    # we add sophisticated SOP lookup logic beyond simple prompting. 