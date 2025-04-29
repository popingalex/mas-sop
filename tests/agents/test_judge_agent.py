import pytest
import asyncio
import json
from unittest.mock import Mock, MagicMock # For mocking
from typing import Optional

# Assume JudgeAgent is importable. Adjust path if necessary based on project structure.
try:
    from src.agents.judge_agent import JudgeAgent, JudgeDecision # Assuming JudgeDecision is the Pydantic model for the output
except ImportError:
    # Add src to path if running tests directly
    import sys
    from pathlib import Path
    project_root = Path(__file__).parent.parent.parent # Adjust based on actual test file location
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
    from src.agents.judge_agent import JudgeAgent, JudgeDecision

# Import necessary AutoGen core types
from autogen_core.models import ChatCompletionClient, CreateResult, RequestUsage
from autogen_agentchat.base import TaskResult

# --- Mock ChatCompletionClient ---

class MockChatCompletionClient(Mock):
    def __init__(self, response_map: dict, **kwargs):
        super().__init__(spec=ChatCompletionClient, **kwargs)
        # Store expected responses based on keywords in the prompt's task
        self.response_map = response_map
        self.model_info = {"vision": False, "function_calling": False, "family": "mock"} # Basic info

    async def create(self, messages, **kwargs) -> CreateResult:
        """Simulates the LLM call based on keywords in the last message."""
        last_message_content = ""
        # Check if messages list is not empty and the last message has a content attribute
        if messages and hasattr(messages[-1], 'content') and isinstance(messages[-1].content, str):
            last_message_content = messages[-1].content # Access content directly

        response_content = '{"type": "AMBIGUOUS", "reason": "Mock default: Could not classify."}' # Default response
        
        # Simple keyword matching for mock responses
        # Use the longest matching keyword to avoid ambiguity (e.g., "onboard" vs "onboard new")
        best_match_keyword = None
        for keyword in self.response_map:
            if keyword.lower() in last_message_content.lower():
                if best_match_keyword is None or len(keyword) > len(best_match_keyword):
                    best_match_keyword = keyword

        if best_match_keyword:
            response_content = self.response_map[best_match_keyword]

        # Simulate the structure returned by a real client
        # Based on AutoGen 0.5.5 CreateResult structure and errors
        mock_choice = {
            "index": 0,
            "finish_reason": "stop", # Required field
            "message": {"role": "assistant", "content": response_content}
        }
        # Usage needs to be a dict-like object, not None
        mock_usage = RequestUsage(prompt_tokens=0, completion_tokens=0) # Use RequestUsage for type safety
        # Cached is also a required field apparently
        # According to new errors, finish_reason and content might be top-level fields
        # Content must be a string (or list[FunctionCall]), not None, when finish_reason is 'stop'.
        return CreateResult(
            choices=[mock_choice],
            finish_reason="stop", # Add finish_reason at the top level
            content=response_content, # Set top-level content to the actual response string
            usage=mock_usage,
            cached=False
        )

# --- Sample SOP Definitions ---

SAMPLE_SOP_DEFS = {
    "onboarding_v1": {
        "title": "Standard Employee Onboarding",
        "description": "Procedure for onboarding new hires.",
        "trigger_keywords": ["onboard", "new hire", "new employee", "入职"],
        # ... other potential SOP details ...
    },
    "incident_response_basic": {
         "title": "Basic Incident Response",
         "description": "Initial steps for responding to a reported incident.",
         "trigger_keywords": ["incident report", "security event", "应急响应", "事件报告"],
         # ...
    }
}

# --- Test Fixtures (Optional but helpful) ---

@pytest.fixture
def mock_llm_responses():
    # Define responses based on keywords expected in the JudgeAgent's prompt
    # Keywords should be specific enough to map to a single test case input ideally
    return {
        # Keywords for basic types
        "summarize this": '{"type": "QUICK", "reason": "Simple summarization task."}',
        "what is the capital": '{"type": "SEARCH", "reason": "Requires external knowledge lookup."}',
        "update the report": '{"type": "AMBIGUOUS", "reason": "Lacks specific details."}',
        "marketing strategy": '{"type": "TASK", "reason": "Complex planning required.", "sop": null}',
        # Keywords for SOP matching
        "onboard": '{"type": "TASK", "reason": "Complex process, matches onboarding SOP.", "sop": "onboarding_v1"}',
        "security incident report": '{"type": "TASK", "reason": "Complex process, matches incident response SOP.", "sop": "incident_response_basic"}',
    }

@pytest.fixture
def judge_agent_with_mock_client(mock_llm_responses):
    """Provides a JudgeAgent instance with a mocked LLM client."""
    mock_client = MockChatCompletionClient(response_map=mock_llm_responses)
    agent = JudgeAgent(
        model_client=mock_client,
        name="TestJudge",
        sop_definitions=SAMPLE_SOP_DEFS,
        caller_name="TestCaller"
    )
    return agent

# --- Test Functions (Refactored using parametrize) ---

@pytest.mark.parametrize(
    "task_input, expected_type, expected_sop",
    [
        # Quick Task
        ("Please summarize this short paragraph about pytest fixtures.", "QUICK", None),
        # Search Task
        ("what is the capital of canada?", "SEARCH", None),
        # Ambiguous Task
        ("Update the report for me.", "AMBIGUOUS", None),
        # Complex Task without SOP match
        ("Develop a comprehensive marketing strategy for our new gadget.", "TASK", None),
    ],
    ids=["quick", "search", "ambiguous", "task_no_sop"] # Test IDs for clarity
)
@pytest.mark.asyncio
async def test_judge_basic_types(judge_agent_with_mock_client: JudgeAgent, task_input: str, expected_type: str, expected_sop: Optional[str]):
    """Tests JudgeAgent classification for basic task types (QUICK, SEARCH, AMBIGUOUS, TASK w/o SOP)."""
    result: TaskResult = await judge_agent_with_mock_client.run(task=task_input)

    assert result.messages, "JudgeAgent should return messages"
    final_message_content = result.messages[-1].content
    assert isinstance(final_message_content, str), "Final message content should be a string"
    
    try:
        decision = json.loads(final_message_content)
        assert decision['type'] == expected_type
        assert decision.get('sop') == expected_sop # Use .get() for optional field
        assert 'reason' in decision # Check reason exists
    except (json.JSONDecodeError, KeyError, AssertionError) as e:
        pytest.fail(f"Failed to parse or validate JSON result for '{task_input}': {e}\nContent: {final_message_content}")

@pytest.mark.parametrize(
    "task_input, expected_sop_id",
    [
        # Task with Onboarding SOP
        ("We need to onboard the new software engineer starting next week.", "onboarding_v1"),
        # Task with Incident Response SOP
        ("Please handle the security incident report ASAP.", "incident_response_basic"),
    ],
    ids=["task_with_onboarding_sop", "task_with_incident_sop"]
)
@pytest.mark.asyncio
async def test_judge_sop_matching(judge_agent_with_mock_client: JudgeAgent, task_input: str, expected_sop_id: str):
    """Tests JudgeAgent classification for TASK type with SOP matching."""
    result: TaskResult = await judge_agent_with_mock_client.run(task=task_input)

    assert result.messages, "JudgeAgent should return messages"
    final_message_content = result.messages[-1].content
    assert isinstance(final_message_content, str), "Final message content should be a string"
    
    try:
        decision = json.loads(final_message_content)
        assert decision['type'] == "TASK"
        assert decision.get('sop') == expected_sop_id # Check for correct SOP match
        assert 'reason' in decision
    except (json.JSONDecodeError, KeyError, AssertionError) as e:
        pytest.fail(f"Failed to parse or validate JSON result for SOP matching task '{task_input}': {e}\nContent: {final_message_content}")

# Removed original individual test functions:
# test_judge_quick_task
# test_judge_search_task
# test_judge_ambiguous_task
# test_judge_complex_task_no_sop
# test_judge_complex_task_with_sop
# test_judge_complex_task_with_sop_variant

# Add more tests as needed, e.g., edge cases, different phrasing, etc. 