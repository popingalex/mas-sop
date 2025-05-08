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
        # 1. 提取任务内容
        task_content = None
        task_id = None
        task_name = None
        
        # 从最近的消息开始查找任务分配
        for msg in reversed(messages):
            if msg.source == self.nexus_agent_name and msg.content:
                if msg.content.startswith("NEXUS_ASSIGNMENT:"):
                    try:
                        # 解析任务分配消息
                        lines = msg.content.split('\n')
                        details = {}
                        for line in lines[1:]:  # 跳过第一行的 "NEXUS_ASSIGNMENT:"
                            if line == "--- END OF ASSIGNMENT ---":
                                break
                            if ": " in line:
                                key, value = line.split(": ", 1)
                                details[key.strip()] = value.strip()
                        
                        task_content = details.get("DESCRIPTION")
                        task_id = details.get("SOP_TASK_ID")
                        task_name = details.get("SOP_TASK_NAME")
                        break
                    except Exception as e:
                        logger.error(f"{self.name}: Error parsing Nexus assignment: {e}")
                        continue

        if not task_content:
            # 如果没有找到正式的任务分配，尝试从最后一条消息提取内容
            task_content = self._extract_task(messages)
            if not task_content:
                logger.warning(f"{self.name}: No task found in messages")
                yield TextMessage(
                    content=f"{self.name}: No task found in messages",
                    source=self.name,
                    role="assistant"
                )
                return

        # 2. 执行任务
        try:
            # 记录任务开始
            logger.info(f"{self.name}: Starting task '{task_name or 'Unnamed'}' (ID: {task_id or 'N/A'})")
            
            # 调用 LLM 执行任务
            response = await self.llm_cached_aask(
                task_content,
                cancellation_token=cancellation_token
            )
            
            # 构建任务完成消息
            completion_message = f"""Task completed by {self.name}
Task ID: {task_id or 'N/A'}
Task Name: {task_name or 'Unnamed'}
Result: {response}
Status: TASK_COMPLETE"""

            # 发送任务完成消息
            yield TextMessage(
                content=completion_message,
                source=self.name,
                role="assistant"
            )
            
            # 发送状态标记
            yield TextMessage(
                content="TASK_COMPLETE",
                source=self.name,
                role="assistant"
            )

        except Exception as e:
            error_msg = f"{self.name}: Error executing task - {str(e)}"
            logger.error(error_msg, exc_info=True)
            yield TextMessage(
                content=error_msg,
                source=self.name,
                role="assistant"
            )
            yield TextMessage(
                content="TASK_COMPLETE",  # 即使失败也标记为完成，让流程继续
                source=self.name,
                role="assistant"
            ) 