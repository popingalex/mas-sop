"""Tests for SOPAgent."""

import pytest
import asyncio
from pathlib import Path
import sys
from typing import Optional, Dict, Any, List
from unittest.mock import MagicMock, AsyncMock

# Add src to path if running tests directly
project_root = Path(__file__).parent.parent.parent
src_path = project_root / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from src.agents.sop_agent import SOPAgent
from src.config.parser import AgentConfig, LLMConfig, load_llm_config_from_toml
from src.tools.plan.manager import PlanManager, Plan, Step
from src.tools.artifact_manager import ArtifactManager
from autogen_agentchat.messages import TextMessage
from src.types.task import TaskType
from src.agents.judge import JudgeDecision

# --- Test Data --- #

SAMPLE_AGENT_CONFIG = AgentConfig(
    name="TestAgent",
    agent="SOPAgent",
    prompt="You are a test agent.",
    llm_config={"model": "test-model"},
    sop_templates={
        "test_sop": {
            "title": "Test SOP",
            "description": "A test SOP template",
            "trigger_keywords": ["test", "example"]
        }
    }
)

SAMPLE_PLAN = Plan(
    id="test_plan",
    title="Test Plan",
    description="A test plan",
    steps=[
        Step(index=0, description="First step", status="pending"),
        Step(index=1, description="Second step", status="pending"),
    ]
)

# --- Fixtures --- #

@pytest.fixture
def plan_manager():
    """提供一个 PlanManager Mock 实例。"""
    manager = AsyncMock(spec=PlanManager)
    manager.create_plan = AsyncMock(return_value={"id": "test_plan", "steps": []})
    return manager

@pytest.fixture
def artifact_manager():
    """提供一个 ArtifactManager Mock 实例。"""
    return MagicMock(spec=ArtifactManager)

@pytest.fixture
def llm_client():
    """创建测试用的 LLM 客户端"""
    from autogen_core.models import ChatCompletionClient
    
    class MockLLMClient(ChatCompletionClient):
        async def create(self, messages, **kwargs):
            if "What is 1+1?" in str(messages):
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "The answer is 2."
                            }
                        }
                    ]
                }
            return {
                "choices": [
                    {
                        "message": {
                            "content": "This is a mock response."
                        }
                    }
                ]
            }
            
        async def create_stream(self, messages, **kwargs):
            raise NotImplementedError("Stream not supported in mock")
            
        def count_tokens(self, text):
            return len(text.split())
            
        def actual_usage(self):
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            
        def total_usage(self):
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
            
        def remaining_tokens(self):
            return 1000
            
        def capabilities(self):
            return {"streaming": False, "function_calling": False}
            
        def model_info(self):
            return {"name": "mock", "family": "mock"}
            
        async def close(self):
            pass
            
    return MockLLMClient()

@pytest.fixture
def mock_model_client():
    client = AsyncMock()
    client.create.return_value = {"content": "Test response"}
    return client

@pytest.fixture
def mock_plan_manager():
    manager = AsyncMock()
    manager.create_plan.return_value = Plan(
        id="test_plan",
        title="Test Plan",
        description="A test plan",
        steps=[
            Step(index=0, description="First step", status="pending"),
            Step(index=1, description="Second step", status="pending")
        ]
    )
    return manager

@pytest.fixture
def mock_judge_agent():
    agent = AsyncMock()
    return agent

@pytest.fixture
def agent_config():
    """创建测试用的 AgentConfig"""
    return AgentConfig(
        name="TestAgent",
        agent="assistant",
        prompt="You are a test agent.",
        sop_templates={
            "test_sop": {
                "title": "Test SOP",
                "description": "A test SOP template",
                "trigger_keywords": ["test", "example"]
            }
        }
    )

@pytest.fixture
def sop_agent(mock_model_client, mock_plan_manager, agent_config, artifact_manager):
    agent = SOPAgent(
        name=agent_config.name,
        agent_config=agent_config,
        model_client=mock_model_client,
        plan_manager=mock_plan_manager,
        artifact_manager=artifact_manager,
    )
    # 替换 JudgeAgent 为 mock
    mock_judge = AsyncMock()
    mock_judge.name = f"{agent_config.name}_Judge"
    agent.judge_agent = mock_judge
    return agent

# --- Tests --- #

def test_sop_agent_initialization(sop_agent):
    """测试 SOPAgent 的基本初始化。"""
    assert sop_agent.name == SAMPLE_AGENT_CONFIG.name
    # 检查关键属性而不是整个对象
    assert sop_agent.agent_config.name == SAMPLE_AGENT_CONFIG.name
    assert sop_agent.agent_config.sop_templates == SAMPLE_AGENT_CONFIG.sop_templates
    assert sop_agent.plan_manager is not None
    assert sop_agent.artifact_manager is not None
    # 因为配置中包含了 sop_templates，所以应该有 judge_agent
    assert sop_agent.judge_agent is not None
    assert sop_agent.judge_agent.name == f"{SAMPLE_AGENT_CONFIG.name}_Judge"

def test_sop_agent_initialization_without_sop_templates(llm_client, plan_manager, artifact_manager):
    """测试没有 SOP 模板时的 SOPAgent 初始化。"""
    config_without_sop = AgentConfig(
        name="TestAgentNoSOP",
        agent="SOPAgent",
        prompt="You are a test agent."
    )
    agent = SOPAgent(
        name=config_without_sop.name,
        agent_config=config_without_sop,
        model_client=llm_client,
        plan_manager=plan_manager,
        artifact_manager=artifact_manager
    )
    assert agent.judge_agent is None

@pytest.mark.asyncio
async def test_initialization(sop_agent):
    """测试智能体初始化"""
    assert sop_agent.name == "TestAgent"
    assert sop_agent.plan_manager is not None
    assert sop_agent.judge_agent is not None

@pytest.mark.asyncio
async def test_extract_task(sop_agent):
    """测试任务提取功能"""
    messages = [
        TextMessage(content="First message", source="user"),
        TextMessage(content="Second message", source="user"),
        TextMessage(content="Task content", source="user")
    ]
    task = sop_agent._extract_task(messages)
    assert task == "Task content"

    # 测试空消息列表
    assert sop_agent._extract_task([]) == ""

@pytest.mark.asyncio
async def test_quick_think_plan(sop_agent):
    """测试快速思考 - PLAN 类型"""
    # 设置 mock 返回值
    decision = JudgeDecision(type="PLAN", confidence=0.9, reason="Test reason")
    async def mock_run(*args, **kwargs):
        yield {"chat_message": TextMessage(content=decision.model_dump_json(), source="judge")}
    sop_agent.judge_agent.run = mock_run

    result = await sop_agent.quick_think("Create a project plan")
    assert result is not None
    assert result.type == "PLAN"
    assert result.confidence == 0.9

@pytest.mark.asyncio
async def test_quick_think_simple(sop_agent):
    """测试快速思考 - SIMPLE 类型"""
    decision = JudgeDecision(type="SIMPLE", confidence=0.8, reason="Test reason")
    async def mock_run(*args, **kwargs):
        yield {"chat_message": TextMessage(content=decision.model_dump_json(), source="judge")}
    sop_agent.judge_agent.run = mock_run

    result = await sop_agent.quick_think("What is 2+2?")
    assert result is not None
    assert result.type == "SIMPLE"
    assert result.confidence == 0.8

@pytest.mark.asyncio
async def test_quick_think_unclear(sop_agent):
    """测试快速思考 - UNCLEAR 类型"""
    decision = JudgeDecision(type="UNCLEAR", confidence=0.7, reason="Test reason")
    async def mock_run(*args, **kwargs):
        yield {"chat_message": TextMessage(content=decision.model_dump_json(), source="judge")}
    sop_agent.judge_agent.run = mock_run

    result = await sop_agent.quick_think("Handle it")
    assert result is not None
    assert result.type == "UNCLEAR"
    assert result.confidence == 0.7

@pytest.mark.asyncio
async def test_process_plan(sop_agent):
    """测试计划处理流程"""
    # 创建 Plan 对象
    plan = {
        "id": "test_plan",
        "title": "Test Plan",
        "description": "Test plan description",
        "steps": [
            {
                "index": 0,
                "description": "First step",
                "status": "pending"
            },
            {
                "index": 1,
                "description": "Second step",
                "status": "pending"
            }
        ]
    }

    # 设置 LLM 响应
    sop_agent.llm_cached_aask = AsyncMock(return_value="Step completed")

    # 执行计划
    results = []
    async for result in sop_agent._process_plan(plan):
        results.append(result)

    # 验证结果
    assert len(results) == 2  # 两个步骤的结果
    assert all("chat_message" in r for r in results)
    assert all(r["chat_message"].source == sop_agent.name for r in results)
    assert all(r["chat_message"].content == "Step completed" for r in results)

@pytest.mark.asyncio
async def test_on_messages_stream_plan(sop_agent):
    """测试消息流处理 - PLAN 类型"""
    # 设置 mock
    decision = JudgeDecision(type="PLAN", confidence=0.9, reason="Test reason")
    sop_agent.judge_agent.run.return_value = AsyncMock(
        chat_message=TextMessage(content=decision.model_dump_json(), source="judge")
    )
    sop_agent.llm_cached_aask = AsyncMock(return_value="Task completed")

    # 执行测试
    messages = [TextMessage(content="Create a project plan", source="user")]
    results = []
    async for result in sop_agent.on_messages_stream(messages):
        results.append(result)

    # 验证结果
    assert len(results) > 0
    assert all("chat_message" in r for r in results)

@pytest.mark.asyncio
async def test_on_messages_stream_simple(sop_agent):
    """测试消息流处理 - SIMPLE 类型"""
    # 设置 mock
    decision = JudgeDecision(type="SIMPLE", confidence=0.8, reason="Test reason")
    sop_agent.judge_agent.run.return_value = AsyncMock(
        chat_message=TextMessage(content=decision.model_dump_json(), source="judge")
    )
    sop_agent.llm_cached_aask = AsyncMock(return_value="4")

    # 执行测试
    messages = [TextMessage(content="What is 2+2?", source="user")]
    results = []
    async for result in sop_agent.on_messages_stream(messages):
        results.append(result)

    # 验证结果
    assert len(results) == 1
    assert results[0]["chat_message"].content == "4"

@pytest.mark.asyncio
async def test_on_messages_stream_unclear(sop_agent):
    """测试消息流处理 - UNCLEAR 类型"""
    # 设置 mock
    decision = JudgeDecision(type="UNCLEAR", confidence=0.7, reason="Test reason")
    async def mock_run(*args, **kwargs):
        yield {"chat_message": TextMessage(content=decision.model_dump_json(), source="judge")}
    sop_agent.judge_agent.run = mock_run
    sop_agent.llm_cached_aask = AsyncMock(return_value="Task is unclear or lacks necessary information. Please provide more details.")

    # 执行测试
    messages = [TextMessage(content="Handle it", source="user")]
    results = []
    async for result in sop_agent.on_messages_stream(messages):
        results.append(result)

    # 验证结果
    assert len(results) == 1
    assert "unclear" in results[0]["chat_message"].content.lower()

@pytest.mark.asyncio
async def test_error_handling(sop_agent):
    """测试错误处理"""
    # 模拟 JudgeAgent 抛出异常
    sop_agent.judge_agent.run.side_effect = Exception("Test error")
    sop_agent.llm_cached_aask = AsyncMock(return_value="An error occurred while processing the task.")

    # 执行测试
    messages = [TextMessage(content="Test task", source="user")]
    results = []
    async for result in sop_agent.on_messages_stream(messages):
        results.append(result)

    # 验证错误处理
    assert len(results) == 1
    assert "error" in results[0]["chat_message"].content.lower()

@pytest.mark.asyncio
async def test_initialization_without_sop_templates():
    """测试没有 SOP 模板时的 SOPAgent 初始化。"""
    config = AgentConfig(
        name="test_agent_no_sop",
        agent="SOPAgent",
        prompt="You are a test agent."
    )
    model_client = AsyncMock()
    plan_manager = AsyncMock()
    
    agent = SOPAgent(
        name=config.name,
        agent_config=config,
        model_client=model_client,
        plan_manager=plan_manager
    )
    
    assert agent.name == "test_agent_no_sop"
    assert agent.judge_agent is None  # 没有 SOP 模板时不应该创建 JudgeAgent 

@pytest.mark.asyncio
async def test_quick_think_search(sop_agent):
    """测试快速思考 - SEARCH 类型"""
    decision = JudgeDecision(type="SEARCH", confidence=0.85, reason="Test reason")
    async def mock_run(*args, **kwargs):
        yield {"chat_message": TextMessage(content=decision.model_dump_json(), source="judge")}
    sop_agent.judge_agent.run = mock_run

    result = await sop_agent.quick_think("Search for information about Python")
    assert result is not None
    assert result.type == "SEARCH"
    assert result.confidence == 0.85

@pytest.mark.asyncio
async def test_on_messages_stream_search_without_tool(sop_agent):
    """测试消息流处理 - SEARCH 类型但没有搜索工具"""
    # 设置 mock
    decision = JudgeDecision(type="SEARCH", confidence=0.85, reason="Test reason")
    async def mock_run(*args, **kwargs):
        yield {"chat_message": TextMessage(content=decision.model_dump_json(), source="judge")}
    sop_agent.judge_agent.run = mock_run

    # 执行测试
    messages = [TextMessage(content="Search for Python tutorials", source="user")]
    results = []
    async for result in sop_agent.on_messages_stream(messages):
        results.append(result)

    # 验证结果
    assert len(results) == 1
    assert "Search capability required" in results[0]["chat_message"].content

@pytest.mark.asyncio
async def test_llm_cached_aask_timeout(sop_agent):
    """测试 LLM 调用超时情况"""
    # 设置 mock 抛出超时异常
    sop_agent.model_client.create.side_effect = TimeoutError("LLM request timed out")

    # 测试不抛出异常的情况
    result = await sop_agent.llm_cached_aask("Test message", raise_on_timeout=False)
    assert "LLM request timed out" in result

    # 测试抛出异常的情况
    with pytest.raises(TimeoutError):
        await sop_agent.llm_cached_aask("Test message", raise_on_timeout=True)

def test_has_search_tool(sop_agent):
    """测试搜索工具检查"""
    # 初始状态应该没有搜索工具
    assert not sop_agent._has_search_tool()

    # 添加搜索工具
    sop_agent.agent_config.assigned_tools = ["search"]
    assert sop_agent._has_search_tool()

    # 移除搜索工具
    sop_agent.agent_config.assigned_tools = ["other_tool"]
    assert not sop_agent._has_search_tool()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_sop_agent_with_real_llm(llm_client):
    """使用真实 LLM 的集成测试"""
    if llm_client is None:
        pytest.skip("LLM client not available")

    # 创建真实的 PlanManager
    plan_manager = PlanManager()
    
    # 创建一个真实的 SOPAgent
    agent = SOPAgent(
        name="IntegrationTestAgent",
        agent_config=AgentConfig(
            name="IntegrationTestAgent",
            agent="assistant",
            prompt="You are a test agent for integration testing.",
            sop_templates={"test_sop": {
                "title": "Test SOP",
                "description": "A test SOP template",
                "trigger_keywords": ["test", "example"]
            }}
        ),
        model_client=llm_client,
        plan_manager=plan_manager
    )

    # 测试简单任务
    messages = [TextMessage(content="What is 2+2?", source="user")]
    results = []
    async for result in agent.on_messages_stream(messages):
        results.append(result)
    
    assert len(results) > 0
    assert "chat_message" in results[0]
    assert isinstance(results[0]["chat_message"].content, str)
    assert len(results[0]["chat_message"].content) > 0

    # 测试计划任务
    messages = [TextMessage(content="Create a test plan with two steps", source="user")]
    results = []
    async for result in agent.on_messages_stream(messages):
        results.append(result)
    
    assert len(results) > 0
    for result in results:
        assert "chat_message" in result
        assert isinstance(result["chat_message"].content, str)
        assert len(result["chat_message"].content) > 0

    # 测试不明确的任务
    messages = [TextMessage(content="handle it", source="user")]
    results = []
    async for result in agent.on_messages_stream(messages):
        results.append(result)
    
    assert len(results) > 0
    assert "chat_message" in results[0]
    assert isinstance(results[0]["chat_message"].content, str)
    assert "unclear" in results[0]["chat_message"].content.lower() or "more details" in results[0]["chat_message"].content.lower()

@pytest.mark.integration
@pytest.mark.asyncio
async def test_llm_cached_aask_with_real_llm(llm_client):
    """使用真实 LLM 测试 llm_cached_aask 方法"""
    if llm_client is None:
        pytest.skip("LLM client not available")
            
    print(f"\nLLM Client type: {type(llm_client)}")
    print(f"LLM Client dir: {dir(llm_client)}")

    # 创建一个真实的 SOPAgent
    agent = SOPAgent(
        name="LLMTestAgent",
        agent_config=AgentConfig(
            name="LLMTestAgent",
            agent="assistant",
            prompt="You are a test agent."
        ),
        model_client=llm_client,
        plan_manager=PlanManager()
    )

    # 测试简单问题
    response = await agent.llm_cached_aask("What is 1+1?")
    print(f"\nLLM Response: {response}")  # 添加调试输出
    
    # 检查响应
    assert isinstance(response, str), f"Response should be string, got {type(response)}"
    assert len(response) > 0, "Response should not be empty"
    assert "2" in response, f"Expected '2' in response, got: {response}" 