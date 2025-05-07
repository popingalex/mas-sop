from typing import Optional, List, Dict, Any, AsyncGenerator, Union
from pydantic import BaseModel
from loguru import logger
import hashlib

from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage
from autogen_core.models import ChatCompletionClient
from autogen_core import CancellationToken

from ..tools.plan.manager import PlanManager
from ..tools.plan.types import Plan, Step
from ..config.parser import AgentConfig
from .judge_agent import JudgeAgent, JudgeDecision

from ..types import JudgeDecision

# Default timeout config if not provided
DEFAULT_TIMEOUT_CONFIG = {"global_timeout": 120}

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
        system_message: Optional[str] = None,
        tools: Optional[List[Any]] = None,
        timeout_config: Optional[Dict[str, int]] = None,
        **kwargs,
    ):
        effective_system_message = system_message
        if effective_system_message is None:
            effective_system_message = getattr(agent_config, 'prompt', "")

        super().__init__(
            name=name,
            system_message=effective_system_message,
            model_client=model_client,
            tools=tools if tools else [],
            **kwargs,
        )
        
        # ADD DEBUG LOG HERE
        logger.debug(f"SOPAgent '{self.name}' AFTER super().__init__(): self.model_client is {getattr(self, 'model_client', 'NOT ACCESSIBLE')} (type: {type(getattr(self, 'model_client', None))}), self._model_client is {getattr(self, '_model_client', 'NOT ACCESSIBLE')} (type: {type(getattr(self, '_model_client', None))})")

        self.agent_config = agent_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager
        self.timeout_config = timeout_config if timeout_config is not None else DEFAULT_TIMEOUT_CONFIG.copy()

        # Initialize JudgeAgent
        self.judge_agent = None
        if hasattr(agent_config, 'sop_templates') and agent_config.sop_templates is not None:
            self.judge_agent = JudgeAgent(
                model_client=model_client,
                name=f"{name}_Judge",
                sop_definitions=agent_config.sop_templates,
                caller_name=name,
            )
            logger.info(f"Internal JudgeAgent '{self.judge_agent.name}' created for {name}.")
        else:
            logger.info(f"No sop_templates found in agent_config for {name}. JudgeAgent not created.")
        
        logger.debug(f"SOPAgent '{self.name}' initialized. Effective system message passed to base: '{effective_system_message[:100]}...'")

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

    async def _process_plan(self, plan: Union[Plan, dict], original_task_description: str) -> str:
        """处理计划任务，执行所有步骤，并返回执行摘要或状态。
        
        Args:
            plan: 要执行的计划对象或字典。
            original_task_description: 分配给此Agent的原始顶层任务描述，用于最终回复。

        Returns:
            str: 描述计划执行结果的摘要字符串。
        """
        if isinstance(plan, dict):
            # Ensure 'steps' key exists and is a list before creating Step objects
            steps_data = plan.pop("steps", [])
            if not isinstance(steps_data, list):
                steps_data = [] # Default to empty list if steps format is incorrect
            steps = [Step(**step) for step in steps_data]
            
            # Ensure 'name' key exists for Plan Pydantic model
            if "name" not in plan:
                plan["name"] = f"Sub-plan for {original_task_description[:30]}..."

            plan_obj = Plan(**plan)
            plan_obj.steps = steps
        else: # plan is already a Plan object
            plan_obj = plan

        completed_steps = 0
        failed_steps = 0
        step_results = []

        for step in plan_obj.steps:
            try:
                # 执行步骤
                # 注意：这里的prompt可能需要更具体，比如结合父任务和步骤描述
                step_execution_prompt = f"Regarding overall task \\\"{original_task_description}\\\", now execute this specific step: {step.description}"
                response = await self.llm_cached_aask(
                    step_execution_prompt,
                    raise_on_timeout=True,
                )
                
                # 更新步骤状态
                step.status = "completed"
                completed_steps += 1
                step_results.append(f"Step {step.index} ('{step.description[:30]}...'): Completed. Result: {response[:50]}...")
                logger.success(f"{self.name}: Internal plan step {step.index} ('{step.description[:30]}...') for task '{original_task_description[:30]}...' completed.")

            except Exception as e:
                logger.error(f"{self.name}: Error executing internal plan step {step.index} ('{step.description[:30]}...') for task '{original_task_description[:30]}...': {e}")
                step.status = "failed"
                failed_steps += 1
                step_results.append(f"Step {step.index} ('{step.description[:30]}...'): Failed. Error: {str(e)[:50]}...")
        
        if failed_steps > 0:
            return f"Internal sub-plan for task '{original_task_description}' executed with {failed_steps} failed step(s) out of {len(plan_obj.steps)}. Results: {'; '.join(step_results)}"
        elif not plan_obj.steps:
            return f"Internal sub-plan for task '{original_task_description}' was empty or had no steps."
        else:
            return f"Internal sub-plan for task '{original_task_description}' successfully completed all {completed_steps} step(s). Summary: {step_results[0] if step_results else 'No specific step results.'}"

    async def on_messages_stream(
        self,
        messages: List[BaseChatMessage],
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """处理消息流。"""
        task = self._extract_task(messages)
        if not task:
            yield TextMessage(
                content="No task found in messages.",
                source=self.name
            )
            return

        try:
            # 快速思考
            decision = await self.quick_think(task)
            
            # 默认回复内容，如果后续逻辑没有生成特定回复
            response_content = f"Task '{task[:50]}...' processed by {self.name}."
            reason_text = f"Task '{task[:50]}...' processed based on internal assessment."

            if not decision:
                # This branch is hit by Strategist (Nexus) if it has no JudgeAgent,
                # or if JudgeAgent fails.
                # For Nexus, the system_message (NEXUS_SYSTEM_MESSAGE_TEMPLATE) guides it
                # to produce a JSON response for planning/handoff.
                logger.info(f"{self.name}: No JudgeAgent decision or acting as Nexus. Task: {task[:50]}...")
                # llm_cached_aask will use the agent's system_message.
                # For Strategist (Nexus), this should be NEXUS_SYSTEM_MESSAGE_TEMPLATE.
                nexus_json_response_str = await self.llm_cached_aask(task, raise_on_timeout=True)
                
                # The Nexus agent's raw JSON string output is what the graph expects.
                # It should already be formatted according to NEXUS_SYSTEM_MESSAGE_TEMPLATE.
                logger.info(f"{self.name} (Nexus behavior): Yielding LLM output directly: {nexus_json_response_str[:200]}...")
                yield TextMessage(
                    content=nexus_json_response_str, # Yield the direct JSON string from LLM
                    source=self.name
                )
                return

            # 根据任务类型处理
            if decision.type == "PLAN":
                logger.info(f"{self.name}: Task '{task[:50]}...' judged as PLAN. Creating and processing internal sub-plan.")
                plan = await self.plan_manager.create_plan(task)
                plan_execution_summary = await self._process_plan(plan, task)
                reason_text = plan_execution_summary
                final_response_to_nexus = f"name: {self.name}\\nsource: [NexusNamePlaceholder] \\nreason: {reason_text}\\noutput: TASK_COMPLETE"
                
                yield TextMessage(
                    content=final_response_to_nexus,
                    source=self.name 
                )

            elif decision.type == "SIMPLE":
                logger.info(f"{self.name}: Task '{task[:50]}...' judged as SIMPLE. Executing directly.")
                response_content = await self.llm_cached_aask(task, raise_on_timeout=True)
                reason_text = f"Task '{task[:50]}...' executed directly as a simple task. Result: {response_content[:100]}..."
                yield TextMessage(
                    content=f"name: {self.name}\\nsource: [NexusNamePlaceholder] \\nreason: {reason_text}\\noutput: TASK_COMPLETE",
                    source=self.name
                )

            elif decision.type == "SEARCH":
                logger.info(f"{self.name}: Task '{task[:50]}...' judged as SEARCH.")
                if not self._has_search_tool():
                    logger.warning(f"{self.name}: Search capability required for task '{task[:50]}...' but not available.")
                    reason_text = f"Search capability required for task '{task[:50]}...' but not available. Unable to complete."
                    yield TextMessage(
                        content=f"name: {self.name}\\nsource: [NexusNamePlaceholder] \\nreason: {reason_text}\\noutput: TASK_COMPLETE",
                        source=self.name
                    )
                    return

                response_content = await self.llm_cached_aask(task, raise_on_timeout=True)
                reason_text = f"Task '{task[:50]}...' executed using search. Result: {response_content[:100]}..."
                yield TextMessage(
                    content=f"name: {self.name}\\nsource: [NexusNamePlaceholder] \\nreason: {reason_text}\\noutput: TASK_COMPLETE",
                    source=self.name
                )

            else:  # UNCLEAR or other types
                logger.info(f"{self.name}: Task '{task[:50]}...' judged as {decision.type if decision else 'UNCATEGORIZED'}. Returning unclear response.")
                reason_text = f"Task '{task[:50]}...' is unclear or lacks necessary information based on decision: {decision.type if decision else 'None'}. Please provide more details."
                yield TextMessage(
                    content=f"name: {self.name}\\nsource: [NexusNamePlaceholder] \\nreason: {reason_text}\\noutput: TASK_UNCLEAR",
                    source=self.name
                )

        except Exception as e:
            logger.error(f"{self.name}: Error in on_messages_stream for task '{task[:50]}...': {e}", exc_info=True)
            yield TextMessage(
                content=f"name: {self.name}\\nsource: [NexusNamePlaceholder] \\nreason: An error occurred processing task '{task[:50]}...': {str(e)}\\noutput: TASK_FAILED_INTERNAL_ERROR",
                source=self.name
            )

    async def llm_cached_aask(self, message: str, raise_on_timeout: bool = False) -> str:
        effective_system_message = self.system_message
        if self.name == "Strategist": # 仅为 Strategist 修改
            effective_system_message = "You are a helpful assistant named Strategist. Respond to the user."
            logger.warning(f"{self.name}: Using TEMPORARY simplified system message for testing.")

        try:
            logger.debug(f"{self.name}: In llm_cached_aask, accessing self._model_client: {self._model_client}, type: {type(self._model_client)}")
            
            llm_messages = [
                {"role": "system", "content": effective_system_message}, # 使用 effective_system_message
                {"role": "user", "content": message}
            ]

            logger.debug(f"{self.name}: Attempting to call self._model_client.create with messages: {llm_messages}")
            response = await self._model_client.create(
                messages=llm_messages
            )
            logger.info(f"{self.name}: self._model_client.create successfully returned. Type of response: {type(response)}. Response (partial): {str(response)[:500]}...")

            if isinstance(response, str):
                return response
            elif hasattr(response, 'choices') and response.choices and hasattr(response.choices[0], 'message') and hasattr(response.choices[0].message, 'content'):
                # Handles cases where response is an object with attributes (e.g., OpenAI SDK v0.x Completion object)
                content = response.choices[0].message.content
                return str(content) if content is not None else "Error: Response content was None."
            elif isinstance(response, dict):
                # Handles cases where response is a dictionary (e.g., OpenAI SDK v1.x or autogen_ext clients)
                choices = response.get("choices")
                if choices and isinstance(choices, list) and len(choices) > 0:
                    first_choice = choices[0]
                    if isinstance(first_choice, dict):
                        message_obj = first_choice.get("message")
                        if isinstance(message_obj, dict):
                            content = message_obj.get("content")
                            if content is not None:
                                logger.debug(f"{self.name}: Successfully extracted content from dict response: {str(content)[:200]}...")
                                return str(content) # Successfully extracted content
                
                # If extraction failed for any reason above for a dict response
                logger.error(f"{self.name}: Received dict response, but failed to extract 'choices[0].message.content'. Response structure: {str(response)[:500]}...")
                # Returning a specific error message instead of the whole dict stringified.
                # This helps pinpoint that the LLM's output (inside the dict) was not as expected or parsing failed.
                return "Error: LLM_RESPONSE_PARSE_FAILURE - Could not extract content from LLM dictionary response. The expected structure 'choices[0].message.content' was not found or content was null."
            else:
                logger.error(f"{self.name}: Unknown response type from self._model_client.create: {type(response)}. Full response: {str(response)[:500]}")
                return f"Error: LLM_RESPONSE_TYPE_UNKNOWN - Unknown response type from LLM client: {type(response)}"

        except AttributeError as ae:
            logger.error(f"{self.name}: AttributeError in llm_cached_aask (likely accessing _model_client when it is None or deleted): {ae}. self._model_client is {getattr(self, '_model_client', 'NOT DEFINED AT ALL')}", exc_info=True)
            raise
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"{self.name}: Error in llm_cached_aask (using self._model_client). "
                f"Exception Type: {type(e)}, Exception Repr: {repr(e)}, Exception Str: {error_msg}",
                exc_info=True
            )
            if raise_on_timeout or not isinstance(e, TimeoutError):
                 pass
            return error_msg