import pytest
import asyncio
import json
from pathlib import Path
import sys
from typing import Optional, Dict, Any, List

# Add src to path
project_root = Path(__file__).parent.parent.parent
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from src.agents.judge import JudgeDecision, JudgeType, judge_agent_tool
from src.config.parser import load_llm_config_from_toml
from autogen_core.models import ChatCompletionClient
from autogen_agentchat.base import TaskResult
from autogen_agentchat.messages import (
    ToolCallRequestEvent, 
    ToolCallExecutionEvent,
    FunctionExecutionResult,
    BaseChatMessage, 
)
from autogen_agentchat.agents import AssistantAgent

pytestmark = pytest.mark.integration

@pytest.fixture
def model_client() -> Optional[ChatCompletionClient]:
    client = load_llm_config_from_toml()
    if client is None:
        pytest.skip("Skipping integration tests: Failed to load LLM configuration.")
    return client

@pytest.fixture
def assistant_using_judge_tool(model_client: ChatCompletionClient) -> AssistantAgent:
    judge_tool_instance = judge_agent_tool(model_client)
    return AssistantAgent(
        name="TestAssistant",
        model_client=model_client,
        tools=[judge_tool_instance],
        description="An assistant agent that uses the JudgeAgent tool to classify tasks.",
        system_message="You are a helpful assistant. Use the 'JudgeAgent' tool when asked to classify a task."
    )

@pytest.mark.parametrize(
    "task_description, expected_type",
    [
        ("Please summarize this short paragraph about pytest fixtures.", "SIMPLE"),
        # ("What is the capital of Canada?", "SIMPLE"),
        # ("Develop a comprehensive marketing strategy for our new gadget, including market research, competitor analysis, budget allocation, and a multi-channel launch plan.", "PLAN"),
        # ("Organize a surprise birthday party for Sarah next month. This includes sending invitations, ordering a cake, and arranging entertainment.", "PLAN"),
        # ("Translate 'hello world' to French.", "SIMPLE"),
        # ("Write a detailed step-by-step guide on how to bake a sourdough bread, including starter maintenance.", "PLAN"),
    ],
    ids=["simple_summary",
         # "simple_question",
         # "complex_plan_strategy",
         # "complex_plan_party",
         # "simple_translation",
         # "complex_plan_guide"
         ]
)
@pytest.mark.asyncio
async def test_judge_tool_output_structure(
    assistant_using_judge_tool: AssistantAgent, task_description: str, expected_type: JudgeType
):
    print(f"\n--- Testing task: '{task_description}' ---")
    
    raw_tool_output_str: Optional[str] = None
    all_events: List[BaseChatMessage] = [] 
    found_tool_execution = False

    async for event in assistant_using_judge_tool.run_stream(task=task_description):
        all_events.append(event)
        print(f"Event type: {type(event)}")
        if isinstance(event, ToolCallExecutionEvent):
            found_tool_execution = True
            if event.content and isinstance(event.content, list) and len(event.content) > 0:
                func_exec_result = event.content[0]
                if isinstance(func_exec_result, FunctionExecutionResult):
                    raw_tool_output_str = func_exec_result.content
                    print(f"  Captured FunctionExecutionResult.content: '{raw_tool_output_str}'") 
            else:
                print("  ToolCallExecutionEvent.content was empty or not as expected.")
        print("--------------------------------")
    
    assert found_tool_execution, "ToolCallExecutionEvent was not found in the event stream."
    assert raw_tool_output_str is not None, \
        "FunctionExecutionResult.content was not captured from ToolCallExecutionEvent."
    assert isinstance(raw_tool_output_str, str), \
        f"FunctionExecutionResult.content is not a string, got: {type(raw_tool_output_str)}"

    print(f"Final raw_tool_output_str to parse: '{raw_tool_output_str}'")

    decision_obj: Optional[JudgeDecision] = None
    try:
        json_to_parse = raw_tool_output_str.strip()
        
        first_brace = json_to_parse.find('{')
        last_brace = json_to_parse.rfind('}')
        
        json_str_candidate: Optional[str] = None
        if first_brace != -1 and last_brace != -1 and last_brace >= first_brace:
            json_str_candidate = json_to_parse[first_brace : last_brace+1]
            print(f"  Attempting to parse JSON candidate with model_validate_json: '{json_str_candidate}'")
            decision_obj = JudgeDecision.model_validate_json(json_str_candidate)
        else:
            print(f"  Could not reliably find JSON braces in '{json_to_parse}'. Attempting direct parse with model_validate_json (may fail if prefixed/malformed).")
            decision_obj = JudgeDecision.model_validate_json(json_to_parse) 

    except Exception as e: # Catches Pydantic ValidationError and json.JSONDecodeError
        pytest.fail(f"Failed to validate/parse tool output string into JudgeDecision. Error: {e}. String was: '{raw_tool_output_str}'")

    assert decision_obj is not None, "Failed to create JudgeDecision object from tool output."
    
    assert decision_obj.type == expected_type, \
        f"For task '{task_description}', expected type '{expected_type}' but got '{decision_obj.type}'. Parsed object: {decision_obj}"
    assert decision_obj.reason is not None and len(decision_obj.reason.strip()) > 0, \
        f"Reason must be a non-empty string for task '{task_description}'. Got: '{decision_obj.reason}'. Parsed object: {decision_obj}"

    print(f"  Successfully validated: type='{decision_obj.type}', reason='{decision_obj.reason}'")

    final_task_result_event = next((e for e in reversed(all_events) if isinstance(e, TaskResult)), None)
    assert final_task_result_event is not None, "TaskResult event not found in the stream."

# Removed SOP related tests and definitions as JudgeAgent no longer handles SOPs directly. 