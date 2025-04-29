"""Integration tests for JudgeAgent."""

import pytest
import asyncio
import os
import json
from pathlib import Path
import sys
from typing import TypedDict, Optional, Dict, Any, List, Literal
from dotenv import load_dotenv
from loguru import logger
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import ModelInfo
from src.config.llm_config import create_completion_client
from src.config.parser import load_llm_config_from_toml

from tests.agents.test_judge_agent import SAMPLE_SOP_DEFS # Assuming this import works
from src.agents.judge_agent import JudgeAgent
from src.types.task import TaskType
from src.llm.utils import get_last_message_content, maybe_structured


project_root = Path(__file__).parent.parent.parent
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

pytestmark = pytest.mark.integration

class IntegrationTestCase(TypedDict):
    """集成测试用例的结构定义"""
    task: str                # 输入的任务描述
    expected_type: TaskType  # 期望的任务类型
    expected_sop: Optional[str] = None  # 期望的 SOP 名称，默认为 None

# 定义测试用例
INTEGRATION_TEST_CASES: List[IntegrationTestCase] = [
    {
        "task": "Please summarize this short paragraph about pytest fixtures.",
        "expected_type": "QUICK"
    },
    {
        "task": "what is the capital of canada?",
        "expected_type": "SEARCH"
    },
    {
        "task": "Update the report for me.",
        "expected_type": "AMBIGUOUS"
    },
    {
        "task": "Develop a comprehensive marketing strategy for our new gadget.",
        "expected_type": "TASK"
    },
    {
        "task": "We need to onboard the new software engineer starting next week.",
        "expected_type": "TASK",
        "expected_sop": "onboarding_v1"
    },
    {
        "task": "Please handle the security incident report ASAP.",
        "expected_type": "TASK",
        "expected_sop": "incident_response_basic"
    },
    {
        "task": "帮我办一下新员工入职手续",
        "expected_type": "TASK",
        "expected_sop": "onboarding_v1"
    },
    {
        "task": "处理一下服务器宕机的紧急事件报告",
        "expected_type": "TASK",
        "expected_sop": "incident_response_basic"
    },
]

def generate_test_id(case: IntegrationTestCase) -> str:
    """生成测试用例的 ID"""
    return f"type:{case['expected_type']}_sop:{case.get('expected_sop', 'None')}"

@pytest.fixture(scope="module")
def judge_agent_with_real_client():
    """提供配置好的 JudgeAgent 实例。"""
    client = load_llm_config_from_toml()  # 直接使用框架提供的函数
    if client is None:
        pytest.skip("Failed to load LLM configuration")

    try:
        agent = JudgeAgent(
            model_client=client,
            name="IntegrationJudge",
            sop_definitions=SAMPLE_SOP_DEFS,
            caller_name="PytestIntegration",
            is_system_logging_enabled=False,
        )
        return agent
    except Exception as e:
        pytest.skip(f"Failed to initialize JudgeAgent: {e}")

@pytest.mark.parametrize(
    "test_case",
    INTEGRATION_TEST_CASES,
    ids=lambda case: generate_test_id(case)
)
@pytest.mark.integration
@pytest.mark.asyncio
async def test_judge_integration(judge_agent_with_real_client: JudgeAgent, test_case: IntegrationTestCase):
    """运行 JudgeAgent 集成测试，检查类型和 SOP 匹配。"""
    logger.info(f"\nTesting task: {test_case['task']}")
    logger.info(f"Expected Type: {test_case['expected_type']}, Expected SOP: {test_case.get('expected_sop', 'None')}")

    try:
        result = await judge_agent_with_real_client.run(task=test_case['task'])
        assert result is not None, "Agent run did not return a result"
        
        content = get_last_message_content(result)
        assert content is not None, "Agent did not return any messages"
        
        final_response = maybe_structured(content)
        assert isinstance(final_response, dict), "Response could not be parsed as a dictionary"
        
        # 验证结构化数据
        assert final_response.get('type') == test_case['expected_type'], \
            f"Expected type '{test_case['expected_type']}' but got '{final_response.get('type')}'"
        assert final_response.get('sop') == test_case.get('expected_sop'), \
            f"Expected SOP '{test_case.get('expected_sop')}' but got '{final_response.get('sop')}'"
        assert 'reason' in final_response, "Mandatory 'reason' field is missing in the response"

        # 记录 token 使用情况
        if hasattr(result, 'cost') and result.cost:
            prompt_tokens = result.cost.get("prompt_tokens", "N/A")
            completion_tokens = result.cost.get("completion_tokens", "N/A")
            logger.info(f"Token Usage: Prompt={prompt_tokens}, Completion={completion_tokens}")
        elif hasattr(result, 'summary') and result.summary:
            summary_data = result.summary
            prompt_tokens = summary_data.get("prompt_tokens", "N/A")
            completion_tokens = summary_data.get("completion_tokens", "N/A")
            if prompt_tokens != "N/A":
                logger.info(f"Token Usage (from summary): Prompt={prompt_tokens}, Completion={completion_tokens}")

        logger.success(f"Test PASSED for task: {test_case['task']}")

    except Exception as e:
        logger.error(f"Test FAILED for task: {test_case['task']}")
        logger.error(f"Error: {e}")
        if content:
            logger.error(f"Raw response content:\n{content}")
        raise 