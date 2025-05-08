from typing import Optional, List, Dict, Any, AsyncGenerator, Union
from pydantic import BaseModel
from loguru import logger
import hashlib

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage, ChatMessage
from autogen_core.models import ChatCompletionClient
from autogen_core import CancellationToken

from ..tools.plan.manager import PlanManager
from src.types.plan import Plan, Step
from ..config.parser import AgentConfig
from ..types import JudgeDecision

class BaseSOPAgent(AssistantAgent):
    """基础SOP智能体，提供计划工具和基础功能。"""
    
    def __init__(
        self,
        name: str,
        agent_config: AgentConfig,
        model_client: ChatCompletionClient,
        plan_manager: PlanManager,
        artifact_manager: Optional[Any] = None,
        system_message: Optional[str] = None,
        **kwargs,
    ):
        super().__init__(name=name, model_client=model_client, system_message=system_message)
        self.agent_config = agent_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager
        self.model_client = model_client
        
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

    async def llm_cached_aask(self, message: str, system_message_override: Optional[str] = None, raise_on_timeout: bool = False) -> str:
        """通用LLM调用方法，简化版。缓存逻辑可后续添加。"""
        
        effective_system_message = system_message_override if system_message_override is not None else (self.system_message or getattr(self.agent_config, 'prompt', '') or "You are a helpful assistant.")

        try:
            llm_messages = [
                ChatMessage(role="system", content=effective_system_message),
                ChatMessage(role="user", content=message)
            ]

            logger.debug(f"{self.name}: Attempting to call self.model_client.create with messages: {llm_messages}")
            
            response = await self.model_client.create(messages=llm_messages)
            
            logger.info(f"{self.name}: self.model_client.create successfully returned. Type of response: {type(response)}.")

            if isinstance(response, str):
                return response
            elif hasattr(response, 'choices') and response.choices and hasattr(response.choices[0], 'message') and hasattr(response.choices[0].message, 'content'):
                content = response.choices[0].message.content
                return str(content) if content is not None else "Error: Response content was None."
            elif isinstance(response, BaseChatMessage): 
                return response.content if response.content is not None else "Error: Response content was None."
            elif isinstance(response, dict):
                choices = response.get("choices")
                if choices and isinstance(choices, list) and len(choices) > 0:
                    first_choice = choices[0]
                    if isinstance(first_choice, dict):
                        message_obj = first_choice.get("message")
                        if isinstance(message_obj, dict):
                            content_str = message_obj.get("content")
                            if content_str is not None:
                                return str(content_str)
                logger.error(f"{self.name}: Received dict response, but failed to extract content. Response: {str(response)[:500]}")
                return "Error: LLM_RESPONSE_PARSE_FAILURE - Could not extract content from LLM dictionary response."
            else:
                logger.error(f"{self.name}: Unknown response type from self.model_client.create: {type(response)}. Response: {str(response)[:500]}")
                return f"Error: LLM_RESPONSE_TYPE_UNKNOWN - Unknown response type from LLM client: {type(response)}"

        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"{self.name}: Error in llm_cached_aask (using self.model_client). "
                f"Exception Type: {type(e)}, Exception: {error_msg}",
                exc_info=True
            )
            return f"Error: LLM_CALL_FAILED - {error_msg}" 