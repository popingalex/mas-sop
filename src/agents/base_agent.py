from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage
from autogen_agentchat.base import Response, TaskResult
from autogen_core.models import ChatCompletionClient
from typing import Optional, List, Dict, Any, Sequence, AsyncGenerator, Union
from pydantic import BaseModel
from loguru import logger
import json
import re
from autogen_core import CancellationToken
from ..config.parser import AgentConfig
from .judge_agent import JudgeAgent, JudgeDecision

# Assuming config models are accessible, e.g., from src.config.parser
# We might need a better way to pass/access config later
# Import the managers
from ..tools.plan.manager import PlanManager, Step  # Assuming Step model is needed
from ..tools.artifact_manager import ArtifactManager
# Import Autogen core types if needed for cancellation token etc.
# Import SimpleJudge tool
# Import the new JudgeAgent
# Import placeholder tools
# from ..tools.plan_manager_tool import PlanManagerTool
# from ..tools.artifact_manager_tool import ArtifactManagerTool

# Define a Pydantic model for the task instruction structure for validation
class SopTaskInstruction(BaseModel):
    type: str
    plan_id: str
    step_index: int

class SOPAgent(AssistantAgent):
    """Base class for agents designed to execute SOP-based workflows.
    Prioritizes executing existing plan steps before processing new messages.
    Uses an internal JudgeAgent for new task analysis if configured.
    Requires PlanManager and ArtifactManager instances.
    """

    def __init__(
        self,
        name: str,
        agent_config: AgentConfig,
        model_client: ChatCompletionClient,
        plan_manager: PlanManager, # REQUIRED manager instance
        artifact_manager: ArtifactManager, # REQUIRED manager instance
        system_message: Optional[str] = "",
        tools: Optional[List[Any]] = None, # For external/LLM tools only
        **kwargs,
    ):
        self.agent_config = agent_config
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager

        # --- Initialize internal Judge agent based on config --- 
        self.judge_agent = None 
        if agent_config.sop_templates is not None:
            self.judge_agent = JudgeAgent(
                model_client=model_client,
                name=f"{name}_Judge",
                sop_definitions=agent_config.sop_templates,
                caller_name=name,
            )
            logger.info(f"Internal JudgeAgent '{self.judge_agent.name}' created.")

        # Tools passed are only external ones now
        all_agent_tools = tools or [] 

        # --- Determine System Message --- 
        base_system_message = system_message or agent_config.prompt or ""
        # General prompt, assumes tools might be available for planning/artifacts if passed
        core_instructions = """
        You are an agent designed to execute tasks, potentially as part of a larger plan.
        Prioritize completing steps assigned to you from an existing plan.
        For new tasks, analyze them and create a plan if they are complex.
        Use available tools (like PlanManagerTool or ArtifactManagerTool if provided) and your capabilities to achieve goals.
        Communicate your status and results clearly."""
        effective_system_message = f"{base_system_message.strip()}\n\n{core_instructions.strip()}"

        super().__init__(
            name=name,
            system_message=effective_system_message,
            model_client=model_client,
            tools=all_agent_tools, # Pass only external tools
            **kwargs
        )

        # Store other config elements
        self.actions = agent_config.actions or []
        self.assigned_tools_config = agent_config.assigned_tools or []

        logger.info(f"Initialized SOP Agent: {self.name} (Class: {agent_config.agent})")
        # Access the system message correctly for logging
        sys_msg_content = "[System Message Not Set or Inaccessible]"
        if hasattr(self, '_system_messages') and self._system_messages:
             # Assuming it's a list of SystemMessage objects
             first_sys_msg = self._system_messages[0]
             if hasattr(first_sys_msg, 'content') and isinstance(first_sys_msg.content, str):
                 sys_msg_content = first_sys_msg.content
        
        logger.debug(f"  System Message Snippet: {sys_msg_content[:300]}...")
        logger.debug(f"  Plan Manager: {self.plan_manager}")
        logger.debug(f"  Artifact Manager: {self.artifact_manager}")
        logger.debug(f"  Actions: {self.actions}")
        logger.debug(f"  Assigned Tools Config (External Names): {self.assigned_tools_config}")
        logger.debug(f"  Tools passed to parent: {[getattr(t, 'name', str(t)) for t in all_agent_tools or []]}")
        if self.judge_agent:
             logger.debug(f"  Internal JudgeAgent enabled: {self.judge_agent.name}")
        else:
             logger.debug("  Internal JudgeAgent disabled.")

    async def _execute_plan_step(
        self, 
        step_data: Step, # Use the imported Step type hint
        cancellation_token: CancellationToken
    ) -> AsyncGenerator[Union[Response, Any], None]:
        """Executes a single step from an existing plan."""
        step_name = step_data.get('title', f"Step {step_data.get('index', 'N/A')}")
        logger.info(f"Agent '{self.name}' starting execution of existing plan step: {step_name}")
        # TODO: Implement actual step execution logic here.
        # This might involve:
        # 1. Updating step status to in_progress via self.plan_manager
        # 2. Loading required input artifacts via self.artifact_manager
        # 3. Calling LLM (maybe using super().on_messages_stream with specific instructions?)
        # 4. Using assigned tools (check self.tools)
        # 5. Saving output artifacts via self.artifact_manager
        # 6. Updating step status to completed/failed via self.plan_manager
        
        # Placeholder response
        result_message_content = f"Placeholder: Successfully executed step '{step_name}'."
        result_message = TextMessage(content=result_message_content, source=self.name)
        yield result_message
        yield Response(chat_message=result_message, inner_messages=[result_message])
        logger.info(f"Agent '{self.name}' finished placeholder execution for step: {step_name}")
        # No return needed for async generator
        
    async def on_messages_stream(
        self,
        messages: Sequence[BaseChatMessage],
        cancellation_token: CancellationToken
    ) -> AsyncGenerator[Union[Response, Any], None]:
        """Overrides AssistantAgent to implement SOP execution logic:
        1. Check for existing plan steps to execute.
        2. If none, use JudgeAgent (if configured) on incoming message.
        3. If judging indicates TASK, create a plan via PlanManager.
        4. Otherwise, fallback to default AssistantAgent behavior.
        """
        # --- Priority 1: Check for existing executable step --- 
        try:
            # Assuming PlanManager has a method like this
            next_step: Optional[Step] = await self.plan_manager.get_next_executable_step(assignee=self.name)
        except Exception as e:
            logger.exception(f"Error checking for next executable step for agent '{self.name}': {e}")
            next_step = None
            
        if next_step:
            logger.info(f"Agent '{self.name}' found existing plan step to execute: {next_step.get('title', 'Untitled')}")
            # Execute the found step
            async for item in self._execute_plan_step(next_step, cancellation_token):
                yield item
            return # Finished turn by executing existing step

        # --- No existing step found, process incoming message --- 
        if not messages:
            logger.warning(f"Agent '{self.name}' received empty message list and no pending plan step.")
            # Let default handle potentially empty stream start?
            async for item in super().on_messages_stream(messages, cancellation_token):
                 yield item
            return

        # --- Priority 2: Quick Think (Judge) --- 
        if hasattr(self, 'judge_agent') and self.judge_agent:
            last_message: BaseChatMessage = messages[-1]
            task_description = str(last_message.content) if isinstance(last_message.content, str) else str(last_message.content)
            if not isinstance(last_message.content, str):
                 logger.warning(f"Agent '{self.name}' received non-string content: {type(last_message.content)}. Using string representation for judge.")

            logger.info(f"Agent '{self.name}' performing task analysis via {self.judge_agent.name} for: '{task_description[:100]}...'")
            
            try:
                judge_result: TaskResult = await self.judge_agent.run(task=task_description, cancellation_token=cancellation_token)
                decision_json_str = ""
                if judge_result.messages and isinstance(judge_result.messages[-1].content, str):
                    decision_json_str = judge_result.messages[-1].content.strip()
                else:
                     raise ValueError(f"JudgeAgent '{self.judge_agent.name}' did not return a valid final string message.")
                
                decision = json.loads(decision_json_str)
                judge_type = decision.get('type')
                judge_sop = decision.get('sop')
                judge_reason = decision.get('reason')
                logger.info(f"JudgeAgent decision: type={judge_type}, sop={judge_sop}, reason={judge_reason}")

                # --- Priority 3: Plan Creation --- 
                if judge_type == "TASK":
                    logger.info("Judge decided 'TASK'. Initiating plan creation.")
                    try:
                        # Call PlanManager to create the plan
                        plan_creation_result = await self.plan_manager.create_plan(
                            task_description=task_description, 
                            template=judge_sop # Pass template if found
                        )
                        # TODO: Check plan_creation_result for success/failure
                        plan_id = plan_creation_result.get("plan_id", "unknown")
                        if judge_sop:
                            planning_message_content = f"Task analysis complete (Reason: {judge_reason}). Planning required. Found relevant SOP template: '{judge_sop}'. Plan created with ID: {plan_id}. Now awaiting execution of the first step."
                        else:
                            planning_message_content = f"Task analysis complete (Reason: {judge_reason}). Planning required. No specific SOP template found. Plan created from scratch with ID: {plan_id}. Now awaiting execution of the first step."
                    except Exception as plan_e:
                        logger.exception(f"Error creating plan for task '{task_description[:50]}...': {plan_e}")
                        planning_message_content = f"Task analysis indicated planning required, but an error occurred during plan creation: {plan_e}"

                    planning_message = TextMessage(content=planning_message_content, source=self.name)
                    yield planning_message 
                    yield Response(chat_message=planning_message, inner_messages=[planning_message])
                    return # End turn after attempting plan creation
                else:
                    # Judge decided not TASK (QUICK, SEARCH, AMBIGUOUS, etc.)
                    # Fall through to default behavior below
                    logger.info(f"Judge decided '{judge_type or 'Unknown'}'. Delegating to standard execution flow.")
                    pass 

            except Exception as e:
                logger.exception(f"Error during task analysis with {self.judge_agent.name}: {e}. Falling back to default execution.")
                # Fall through to default behavior below on error
                pass
        
        # --- Priority 4: Default Execution Flow (or fallback) --- 
        logger.debug(f"Agent '{self.name}' proceeding with standard message processing for incoming message.")
        async for item in super().on_messages_stream(messages, cancellation_token):
            yield item
        return