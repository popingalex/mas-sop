import pytest
import asyncio
import json
from pathlib import Path
import sys
from typing import Optional, List


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
from autogen_agentchat.tools import AgentTool
from src.llm.utils import maybe_structured

pytestmark = pytest.mark.integration

@pytest.fixture
def model_client() -> Optional[ChatCompletionClient]:
    client = load_llm_config_from_toml()
    if client is None:
        pytest.skip("Skipping integration tests: Failed to load LLM configuration.")
    return client

@pytest.fixture
def judge_tool(model_client: ChatCompletionClient) -> AgentTool:
    return judge_agent_tool(model_client)

@pytest.fixture
def agent_with_tool(model_client: ChatCompletionClient, judge_tool: AgentTool) -> AssistantAgent:
    return AssistantAgent(
        name="TestAssistant",
        model_client=model_client,
        tools=[judge_tool],
        system_message="调用Judge工具判断输入的任务"
    )

@pytest.mark.parametrize(
    "task_description, expected_type",
    [
        ("Please summarize this short paragraph about pytest fixtures.", "SIMPLE"),
        ("What is the capital of Canada?", "SIMPLE"),
        ("Develop a comprehensive marketing strategy for our new gadget, including market research, competitor analysis, budget allocation, and a multi-channel launch plan.", "PLAN"),
        ("Organize a surprise birthday party for Sarah next month. This includes sending invitations, ordering a cake, and arranging entertainment.", "PLAN"),
        ("Translate 'hello world' to French.", "SIMPLE"),
        ("Write a detailed step-by-step guide on how to bake a sourdough bread, including starter maintenance.", "PLAN"),
    ],
    ids=[
        "simple_summary",
        "simple_question",
        "complex_plan_strategy",
        "complex_plan_party",
        "simple_translation",
        "complex_plan_guide"
        ]
)
@pytest.mark.asyncio
async def test_judge_tool_output_structure(
    judge_tool: AgentTool,
    agent_with_tool: AssistantAgent,
    task_description: str,
    expected_type: JudgeType
):
    parsed_result: Optional[JudgeDecision] = None

    async for event in agent_with_tool.run_stream(task=task_description):
        if isinstance(event, ToolCallExecutionEvent):
            tool_call_result = event.content[0].content
            assert judge_tool.name in tool_call_result, f"Expected {judge_tool.name} in {tool_call_result}"
            source, result = tool_call_result.split(':', 1)
            assert source.strip() == judge_tool.name, f"Expected {judge_tool.name} as source, got {source}"
            parsed_result = JudgeDecision.model_validate_json(result.strip())

    assert parsed_result, "No tool call results received"
    assert parsed_result.type == expected_type, f"Expected {expected_type}, got {parsed_result.type}"
    assert len(parsed_result.reason.strip()) > 0, f"Expected reason, got {parsed_result.reason}"