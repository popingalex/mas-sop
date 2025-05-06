import pytest
import asyncio
import json
from pathlib import Path
import sys
from typing import Optional, Dict, Any, List, TypedDict

# Add src to path if running tests directly (important for imports)
project_root = Path(__file__).parent.parent.parent # Adjust based on actual test file location
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Now import necessary components
from src.agents.judge_agent import JudgeAgent, JudgeDecision
from src.config.llm_config import create_completion_client # Assumes this function exists and works
from src.config.parser import load_llm_config_from_toml # Assumes this function exists
from src.types.task import TaskType # Import the Enum if you have one, or use strings
from src.llm.utils import get_last_message_content, maybe_structured # Assuming these helpers exist

# Import necessary AutoGen core types
from autogen_core.models import ChatCompletionClient, CreateResult, RequestUsage
from autogen_agentchat.base import TaskResult

# --- Sample SOP Definitions (Keep this) ---

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

# Mark all tests in this file as integration tests
pytestmark = pytest.mark.integration

# --- Test Fixture using Real LLM Client ---

@pytest.fixture(scope="module") # Use module scope for efficiency
def judge_agent_with_real_client():
    """Provides a JudgeAgent instance with a real LLM client from config."""
    client = load_llm_config_from_toml() # Load client using your config loading function
    if client is None:
        pytest.skip("Skipping integration tests: Failed to load LLM configuration.")

    try:
        agent = JudgeAgent(
            model_client=client,
            name="TestJudgeIntegration", # Give it a distinct name
            sop_definitions=SAMPLE_SOP_DEFS,
            caller_name="PytestUnitTurnedIntegration",
            is_system_logging_enabled=False # Reduce noise in test logs
        )
        return agent
    except Exception as e:
        pytest.skip(f"Skipping integration tests: Failed to initialize JudgeAgent - {e}")


# --- Test Functions (Updated for Integration and New Types) ---

@pytest.mark.parametrize(
    "task_input, expected_type, expected_sop",
    [
        # Simple Task
        ("Please summarize this short paragraph about pytest fixtures.", "SIMPLE", None),
        # Search Task
        ("what is the capital of canada?", "SEARCH", None),
        # Uncertain Task
        ("Update the report for me.", "UNCERTAIN", None),
        # Plan Task without SOP match
        ("Develop a comprehensive marketing strategy for our new gadget.", "PLAN", None),
    ],
    ids=["simple", "search", "uncertain", "plan_no_sop"]
)
@pytest.mark.asyncio
async def test_judge_basic_types(judge_agent_with_real_client: JudgeAgent, task_input: str, expected_type: str, expected_sop: Optional[str]):
    """Tests JudgeAgent classification for basic task types using a real LLM."""
    result: Optional[TaskResult] = await judge_agent_with_real_client.run(task=task_input)

    assert result is not None, "Agent run did not return a result"
    content = get_last_message_content(result)
    assert content is not None, "Agent did not return any messages or content"

    try:
        decision = maybe_structured(content) # Use helper to parse JSON
        assert isinstance(decision, dict), f"Response was not a valid JSON object. Content: {content}"

        assert decision.get('type') == expected_type, f"Expected type '{expected_type}' but got '{decision.get('type')}'"
        # Use .get() for optional 'sop' field, comparing None explicitly if needed
        assert decision.get('sop') == expected_sop, f"Expected SOP '{expected_sop}' but got '{decision.get('sop')}'"
        assert 'reason' in decision, "Mandatory 'reason' field is missing" # Check reason exists

    except (json.JSONDecodeError, AssertionError) as e:
        # Combine the fail message into a single line f-string
        pytest.fail(f"Failed to parse or validate JSON result for '{task_input}': {e}\nContent: {content}")
    except Exception as e: # Catch other potential errors during processing
         # Combine the fail message into a single line f-string
         pytest.fail(f"An unexpected error occurred during test execution for '{task_input}': {e}\nContent: {content}")


@pytest.mark.parametrize(
    "task_input, expected_sop_id",
    [
        # Task with Onboarding SOP
        ("We need to onboard the new software engineer starting next week.", "onboarding_v1"),
        # Task with Incident Response SOP
        ("Please handle the security incident report ASAP.", "incident_response_basic"),
        # Chinese variant - Onboarding
        ("帮我为下周入职的新软件工程师办一下手续。", "onboarding_v1"),
        # Chinese variant - Incident
        ("尽快处理这份安全事件报告。", "incident_response_basic"),
    ],
    ids=["plan_with_onboarding_sop", "plan_with_incident_sop", "plan_onboarding_zh", "plan_incident_zh"]
)
@pytest.mark.asyncio
async def test_judge_sop_matching(judge_agent_with_real_client: JudgeAgent, task_input: str, expected_sop_id: str):
    """Tests JudgeAgent classification for PLAN type with SOP matching using a real LLM."""
    result: Optional[TaskResult] = await judge_agent_with_real_client.run(task=task_input)

    assert result is not None, "Agent run did not return a result"
    content = get_last_message_content(result)
    assert content is not None, "Agent did not return any messages or content"

    try:
        decision = maybe_structured(content)
        assert isinstance(decision, dict), f"Response was not a valid JSON object. Content: {content}"

        # Expect PLAN type when an SOP is matched
        assert decision.get('type') == "PLAN", f"Expected type 'PLAN' for SOP matching task, but got '{decision.get('type')}'"
        assert decision.get('sop') == expected_sop_id, f"Expected SOP '{expected_sop_id}' but got '{decision.get('sop')}'"
        assert 'reason' in decision, "Mandatory 'reason' field is missing"

    except (json.JSONDecodeError, AssertionError) as e:
        # Combine the fail message into a single line f-string
        pytest.fail(f"Failed to parse or validate JSON result for SOP matching task '{task_input}': {e}\nContent: {content}")
    except Exception as e:
         # Combine the fail message into a single line f-string
         pytest.fail(f"An unexpected error occurred during test execution for SOP matching task '{task_input}': {e}\nContent: {content}")


# Removed original individual test functions and Mock related code.
# This file now purely contains integration tests for JudgeAgent. 