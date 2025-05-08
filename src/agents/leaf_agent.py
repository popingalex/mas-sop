from typing import Optional, List, Dict, Any, AsyncGenerator, Union
from loguru import logger

from autogen_agentchat.messages import TextMessage, BaseChatMessage, ChatMessage
from autogen_core import CancellationToken
from autogen_core.models import ChatCompletionClient
from autogen_agentchat.base import Response

from .base_sop_agent import BaseSOPAgent
from src.types.plan import Plan, Step
from ..config.parser import AgentConfig
from ..tools.plan.manager import PlanManager

class LeafAgent(BaseSOPAgent):
    """执行者（SOP任务执行者），负责具体任务的执行和自我分解。"""

    def __init__(
        self,
        name: str,
        agent_config: AgentConfig,
        model_client: ChatCompletionClient,
        plan_manager: PlanManager,
        artifact_manager: Optional[Any] = None,
        timeout_config: Optional[Dict[str, int]] = None, 
        **kwargs,
    ):
        super().__init__(
            name=name,
            agent_config=agent_config,
            model_client=model_client,
            plan_manager=plan_manager,
            artifact_manager=artifact_manager,
            timeout_config=timeout_config,
            **kwargs
        )
        # Leaf-specific initializations, if any, can go here.

    async def _process_plan(self, plan: Union[Plan, dict], original_task_description: str) -> str:
        """处理计划任务，执行所有步骤，并返回执行摘要或状态 (migrated from SOPAgent).
        Used by LeafAgent for self-decomposition of a complex assigned SOP task.
        """
        if isinstance(plan, dict):
            steps_data = plan.pop("steps", [])
            if not isinstance(steps_data, list):
                logger.warning(f"{self.name}: 'steps' in plan data is not a list or missing. Defaulting to empty. Data: {plan}")
                steps_data = []
            steps = [Step(**step_data) for step_data in steps_data]
            
            if "name" not in plan:
                plan["name"] = f"Internal sub-plan for {original_task_description[:30]}..."

            try:
                plan_obj = Plan(**plan)
                plan_obj.steps = steps
            except Exception as e:
                logger.error(f"{self.name}: Error creating Plan object from dict: {e}. Plan data: {plan}, Steps data: {steps_data}")
                return f"Error: Could not create internal sub-plan object from provided data. Details: {e}"
        elif isinstance(plan, Plan):
            plan_obj = plan
        else:
            logger.error(f"{self.name}: Invalid type for plan argument in _process_plan: {type(plan)}")
            return "Error: Invalid plan data type provided for processing."

        completed_steps = 0
        failed_steps = 0
        step_results = []

        if not plan_obj.steps:
            logger.info(f"{self.name}: Internal sub-plan for task '{original_task_description[:30]}...' has no steps.")
            return f"Internal sub-plan for task '{original_task_description}' was empty or had no steps to execute."

        for step in plan_obj.steps:
            try:
                step_execution_prompt = f"Regarding overall task \"{original_task_description}\", now execute this specific step from your self-generated plan: {step.description}"
                response = await self.llm_cached_aask(
                    step_execution_prompt,
                    raise_on_timeout=True,
                )
                
                step.status = "completed"
                completed_steps += 1
                step_results.append(f"Step {getattr(step, 'index', 'N/A')} ('{step.description[:30]}...'): Completed. Result: {response[:50]}...")
                logger.success(f"{self.name}: Internal plan step {getattr(step, 'index', 'N/A')} ('{step.description[:30]}...') for task '{original_task_description[:30]}...' completed.")

            except Exception as e:
                logger.error(f"{self.name}: Error executing internal plan step {getattr(step, 'index', 'N/A')} ('{step.description[:30]}...') for task '{original_task_description[:30]}...': {e}", exc_info=True)
                step.status = "failed"
                failed_steps += 1
                step_results.append(f"Step {getattr(step, 'index', 'N/A')} ('{step.description[:30]}...'): Failed. Error: {str(e)[:50]}...")
        
        if failed_steps > 0:
            return f"Self-decomposed plan for task '{original_task_description}' executed with {failed_steps} failed step(s) out of {len(plan_obj.steps)}. Results: {'; '.join(step_results)}"
        else:
            return f"Self-decomposed plan for task '{original_task_description}' successfully completed all {completed_steps} step(s). Summary: {step_results[0] if step_results else 'No specific step results for an empty plan.'}"
    
    async def on_messages_stream(
        self,
        messages: List[BaseChatMessage],
        cancellation_token: Optional[CancellationToken] = None,
    ) -> AsyncGenerator[BaseChatMessage, None]:
        """处理消息流，主要负责：
        1. 接收Nexus分配的具体SOP任务指令。
        2. 执行SOP任务（可能涉及自我分解调用_process_plan，或直接调用llm_cached_aask）。
        3. 将执行结果作为消息产出。
        """
        assigned_task_str = ""
        nexus_assignment_prefix = "NEXUS_ASSIGNMENT:"
        for msg in reversed(messages):
            if msg.source == "NexusAgent" and msg.content and msg.content.startswith(nexus_assignment_prefix):
                assigned_task_str = msg.content
                break
        
        if not assigned_task_str:
            task_content = self._extract_task(messages)
            if not task_content:
                logger.warning(f"{self.name}: No user task found in incoming messages.")
                # Yield a message indicating no task was found, using the agent's name
                yield TextMessage(content=f"{self.name}: No task found in messages.", source=self.name)
                # Optionally yield Response with empty content or specific error marker
                yield Response(chat_message=TextMessage(content="[NO_TASK_FOUND]", source=self.name))
                return
            logger.warning(f"{self.name}: Could not find specific Nexus assignment. Falling back to last user message as task: {task_content[:100]}...")

        parsed_task_description = task_content
        sop_task_id = "N/A"
        sop_task_name = "N/A"

        if task_content.startswith(nexus_assignment_prefix):
            try:
                lines = task_content.split('\n')
                details = {}
                for line in lines[1:]:
                    if line == "--- END OF ASSIGNMENT ---":
                        break
                    if ": " in line:
                        key, value = line.split(": ", 1)
                        details[key.strip()] = value.strip()
                
                parsed_task_description = details.get("DESCRIPTION", task_content)
                sop_task_id = details.get("SOP_TASK_ID", "N/A")
                sop_task_name = details.get("SOP_TASK_NAME", "N/A")
                logger.info(f"{self.name}: Received SOP Task '{sop_task_name}' (ID: {sop_task_id}). Description: {parsed_task_description[:100]}...")
            except Exception as e:
                logger.error(f"{self.name}: Error parsing Nexus assignment: {e}. Raw content: {task_content[:200]}... Defaulting to full content as task.")

        else:
            logger.info(f"{self.name}: Processing task: {parsed_task_description[:100]}...")

        try:
            execution_result = await self.llm_cached_aask(parsed_task_description)
            
            logger.info(f"{self.name}: Task '{sop_task_name}' (ID: {sop_task_id}) execution result: {execution_result[:100]}...")
            yield TextMessage(
                content=f"LEAF_AGENT_RESULT:\nSOP_TASK_ID: {sop_task_id}\nSOP_TASK_NAME: {sop_task_name}\nRESULT: {execution_result}", 
                source=self.name
            )
                
        except Exception as e:
            logger.error(f"{self.name}: Error in on_messages_stream for task '{sop_task_name}': {e}", exc_info=True)
            yield TextMessage(
                content=f"name: {self.name}\nsource: LEAF_INTERNAL_ERROR\nSOP_TASK_ID: {sop_task_id}\nSOP_TASK_NAME: {sop_task_name}\nreason: Error: {str(e)}\noutput: TASK_FAILED_LEAF_PROCESSING",
                source=self.name
            ) 