import json
from typing import Dict, Any, Optional, List, Union
from loguru import logger
from pydantic import BaseModel, Field

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient # Import needed type
from ..config.parser import LLMConfig

# Define the structured output format for the JudgeAgent
class JudgeDecision(BaseModel):
    type: str = Field(..., description="The classified type of the task (e.g., TASK, QUICK, SEARCH, AMBIGUOUS).")
    sop: Optional[str] = Field(None, description="The content or ID of the relevant SOP template if type is TASK and a template is found, otherwise null.")
    reason: str = Field(..., description="A brief explanation for the classification decision.")


class JudgeAgent(AssistantAgent):
    """An agent specialized in analyzing task descriptions, classifying them,
    and identifying relevant SOP templates."""

    def __init__(
        self,
        model_client: ChatCompletionClient, # Expect a model client (Required first)
        name: str = "TaskJudge", # Name after required args
        sop_definitions: Optional[Dict[str, Any]] = None,
        caller_name: Optional[str] = None, # Added caller context
        is_system_logging_enabled: bool = True,
        **kwargs,
    ):
        """
        Args:
            model_client: The ChatCompletionClient instance.
            name: Agent name.
            sop_definitions: Pre-loaded SOP definitions.
            caller_name: Name of the agent calling this judge.
            is_system_logging_enabled: Whether to log system messages.
            **kwargs: Additional arguments for AssistantAgent.
        """
        self._is_system_logging_enabled = is_system_logging_enabled
        self.sop_definitions = sop_definitions or {}
        self.caller_name = caller_name

        # Define the specific system prompt for the JudgeAgent
        # SOP definitions are part of the prompt context
        judge_system_prompt = f"""
        You are a highly efficient task analyzer invoked by '{self.caller_name or 'another agent'}'.
        Your sole purpose is to analyze the given task description and classify its type.
        The possible types are:
        - TASK: Requires a multi-step plan or Standard Operating Procedure (SOP).
        - QUICK: Can be answered or executed directly in a single step.
        - SEARCH: Requires web search or knowledge base lookup.
        - AMBIGUOUS: The task description is unclear or lacks sufficient information.

        If you classify the type as TASK, you MUST check if any predefined SOP templates are relevant. Look for keywords or semantic matches in the following SOP definitions:
        --- SOP Definitions ---
        {json.dumps(self.sop_definitions, indent=2)}
        --- End SOP Definitions ---

        Respond ONLY with a JSON object matching this schema:
        {{
            "type": "TASK | QUICK | SEARCH | AMBIGUOUS",
            "sop": "relevant_sop_id_or_content | null (required if type is TASK, null otherwise)",
            "reason": "Your brief reasoning."
        }}
        Provide ONLY the JSON object in your response.
        """

        super().__init__(
            name=name,
            system_message=judge_system_prompt.strip(),
            model_client=model_client, # Pass the model client
            # human_input_mode="NEVER", # Removed: Not a valid argument in newer autogen-agentchat
            # JudgeAgent doesn't need external tools typically
            **kwargs,
        )

        logger.info(f"Initialized JudgeAgent: {self.name} (called by {self.caller_name or 'Unknown'})")
        if self._is_system_logging_enabled:
             logger.debug(f"  Judge System Message Snippet: {self._system_messages[0].content[:250]}...")
        logger.debug(f"  Judge Model Client: {self._model_client}") # Log client object, use _model_client
        logger.debug(f"  Loaded SOP Definitions: {list(self.sop_definitions.keys())}")

    # No internal tools needed for basic prompt-based lookup
    # If complex SOP searching is needed, add a dedicated tool here

    # JudgeAgent primarily relies on its prompt and LLM call via the parent's
    # message handling. It doesn't need complex overrides itself unless
    # we add sophisticated SOP lookup logic beyond simple prompting. 