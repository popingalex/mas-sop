import pytest
from uuid import uuid4, UUID
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from src.tools.plan.manager import PlanManager, Plan, Step, Note, PlanStatus, StepStatus
from src.tools.errors import ErrorMessages
from src.agents.plan_managing_agent import PlanManagingAgent
import json

@pytest.fixture
def temp_log_dir(tmp_path):
    """创建临时日志目录"""
    log_dir = tmp_path / "test_logs"
    log_dir.mkdir()
    return str(log_dir)

@pytest.fixture
def mock_llm():
    """模拟 LLM 响应"""
    mock = AsyncMock()
    
    async def mock_create(prompt: str):
        if "分析以下用户请求" in prompt:
            return json.dumps({
                "intent": "create_plan",
                "parameters": {
                    "title": "Test Plan",
                    "reporter": "test_user"
                },
                "context": {},
                "suggestions": ["建议添加具体的完成时间"]
            })
        elif "验证以下操作的合理性" in prompt:
            return json.dumps({
                "is_valid": True,
                "reason": "操作参数完整且合理",
                "suggestions": []
            })
        elif "分析以下计划的结构" in prompt:
            return json.dumps({
                "is_valid": True,
                "reason": "计划结构合理",
                "suggestions": ["建议细化步骤描述"],
                "dependencies": []
            })
        return "{}"
    
    mock.create = mock_create
    return mock

@pytest.fixture
def plan_managing_agent(temp_log_dir, mock_llm):
    """创建带模拟 LLM 的 PlanManagingAgent 实例"""
    manager = PlanManager(log_dir=temp_log_dir)
    agent = PlanManagingAgent(
        name="test_plan_manager",
        plan_manager=manager
    )
    agent.llm = mock_llm
    return agent

@pytest.mark.asyncio
async def test_agent_plan_lifecycle(plan_managing_agent):
    """测试代理管理计划的完整生命周期"""
    # 1. 创建计划
    title = "Test Plan"
    reporter = "test_user"
    create_result = await plan_managing_agent.create_plan(
        title=title,
        reporter=reporter
    )
    assert create_result["status"] == "success"
    assert create_result["data"]["title"] == title
    assert create_result["data"]["reporter"] == reporter
    assert create_result["data"]["status"] == "not_started"
    plan_id = str(create_result["data"]["id"])
    
    # 2. 查询计划
    get_result = await plan_managing_agent.get_plan(plan_id)
    assert get_result["status"] == "success"
    assert get_result["data"]["title"] == title
    assert get_result["data"]["reporter"] == reporter
    
    # 3. 更新状态
    update_result = await plan_managing_agent.update_plan_status(
        plan_id_str=plan_id,
        status="in_progress"
    )
    assert update_result["status"] == "success"
    assert update_result["data"]["status"] == "in_progress"
    
    # 4. 删除计划
    delete_result = await plan_managing_agent.delete_plan(plan_id)
    assert delete_result["status"] == "success"
    
    # 5. 验证删除
    get_result = await plan_managing_agent.get_plan(plan_id)
    assert get_result["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id) == get_result["message"]

@pytest.mark.asyncio
async def test_agent_plan_steps_management(plan_managing_agent):
    """测试代理管理计划步骤的完整流程"""
    # 1. 创建带步骤的计划
    steps_data = [
        {"title": "Step 1", "assignee": "agent1", "content": "Step 1 content"}
    ]
    create_result = await plan_managing_agent.create_plan(
        title="Test Plan with Steps",
        reporter="test_user",
        steps_data=steps_data
    )
    assert create_result["status"] == "success"
    assert len(create_result["data"]["steps"]) == 1
    plan_id = str(create_result["data"]["id"])
    
    # 2. 添加新步骤
    add_step_result = await plan_managing_agent.add_step(
        plan_id_str=plan_id,
        title="Step 2",
        assignee="agent2",
        content="Step 2 content"
    )
    assert add_step_result["status"] == "success"
    assert len(add_step_result["data"]["steps"]) == 2
    assert add_step_result["data"]["steps"][1]["title"] == "Step 2"
    assert add_step_result["data"]["steps"][1]["assignee"] == "agent2"
    
    # 3. 更新步骤
    update_data = {
        "title": "Updated Step 1",
        "content": "Updated content",
        "status": "in_progress"
    }
    update_result = await plan_managing_agent.update_step(
        plan_id_str=plan_id,
        step_index=0,
        update_data=update_data
    )
    assert update_result["status"] == "success"
    assert update_result["data"]["title"] == "Updated Step 1"
    assert update_result["data"]["status"] == "in_progress"
    
    # 4. 添加笔记
    note_result = await plan_managing_agent.add_note_to_step(
        plan_id_str=plan_id,
        step_index=0,
        content="Test note",
        author="test_user"
    )
    assert note_result["status"] == "success"
    assert len(note_result["data"]["notes"]) == 1
    assert note_result["data"]["notes"][0]["content"] == "Test note"
    assert note_result["data"]["notes"][0]["author"] == "test_user"

    # 5. 验证计划状态自动更新
    plan_result = await plan_managing_agent.get_plan(plan_id)
    assert plan_result["status"] == "success"
    assert plan_result["data"]["status"] == "in_progress"

@pytest.mark.asyncio
async def test_agent_natural_language_request(plan_managing_agent):
    """测试代理处理自然语言请求"""
    # 测试创建计划的自然语言请求
    request = "请创建一个标题为'测试计划'的新计划"
    result = await plan_managing_agent.handle_request(request)
    
    assert result["status"] == "success"
    assert "suggestions" in result
    assert isinstance(result["suggestions"], list)

@pytest.mark.asyncio
async def test_agent_plan_analysis(plan_managing_agent):
    """测试代理的计划分析能力"""
    # 创建带复杂步骤的计划
    steps_data = [
        {
            "title": "步骤1",
            "assignee": "agent1",
            "content": "详细内容1"
        },
        {
            "title": "步骤2",
            "assignee": "agent2",
            "content": "详细内容2"
        }
    ]
    
    result = await plan_managing_agent.create_plan(
        title="测试计划",
        reporter="test_user",
        steps_data=steps_data
    )
    
    assert result["status"] == "success"
    assert "suggestions" in result
    assert isinstance(result["suggestions"], list)

@pytest.mark.asyncio
async def test_agent_validation(plan_managing_agent, mock_llm):
    """测试代理的验证功能"""
    # 模拟验证失败的情况
    async def mock_validate(prompt: str):
        return json.dumps({
            "is_valid": False,
            "reason": "缺少必要参数",
            "suggestions": ["请提供步骤的负责人"]
        })
    
    mock_llm.create = mock_validate
    
    result = await plan_managing_agent.handle_request(
        "创建一个没有负责人的计划步骤"
    )
    
    assert result["status"] == "error"
    assert "suggestions" in result
    assert "缺少必要参数" in result["message"]

@pytest.mark.asyncio
async def test_agent_error_handling(plan_managing_agent):
    """测试代理的错误处理"""
    # 测试无效的操作意图
    result = await plan_managing_agent._analyze_request("执行一个不存在的操作")
    assert "intent" in result
    
    # 测试参数验证
    validation = await plan_managing_agent._validate_operation(
        "create_plan",
        {"title": "", "reporter": ""}  # 空标题
    )
    assert isinstance(validation, dict)

@pytest.mark.asyncio
async def test_agent_plan_with_parent_step(plan_managing_agent):
    """测试代理管理带父步骤的计划"""
    # 1. 创建父计划
    parent_result = await plan_managing_agent.create_plan(
        title="Parent Plan",
        reporter="test_user",
        steps_data=[{"title": "Parent Step", "assignee": "agent1"}]
    )
    assert parent_result["status"] == "success"
    parent_id = str(parent_result["data"]["id"])
    parent_step_id = "0"  # 第一个步骤的ID
    
    # 2. 创建子计划
    parent_step_ref = f"{parent_id}/{parent_step_id}"
    child_result = await plan_managing_agent.create_plan(
        title="Child Plan",
        reporter="test_user",
        parent_step_id=parent_step_ref
    )
    assert child_result["status"] == "success"
    assert child_result["data"]["parent_step_id"] == parent_step_ref

@pytest.mark.asyncio
async def test_agent_concurrent_operations(plan_managing_agent):
    """测试代理的并发操作"""
    # 1. 创建基础计划
    create_result = await plan_managing_agent.create_plan(
        title="Concurrent Test Plan",
        reporter="test_user",
        steps_data=[
            {"title": "Step 1", "assignee": "agent1"},
            {"title": "Step 2", "assignee": "agent2"}
        ]
    )
    assert create_result["status"] == "success"
    plan_id = str(create_result["data"]["id"])
    
    # 2. 并发更新不同步骤
    import asyncio
    update_tasks = [
        plan_managing_agent.update_step(
            plan_id_str=plan_id,
            step_index=0,
            update_data={"status": "in_progress"}
        ),
        plan_managing_agent.update_step(
            plan_id_str=plan_id,
            step_index=1,
            update_data={"status": "completed"}
        )
    ]
    results = await asyncio.gather(*update_tasks)
    
    # 验证两个更新都成功
    assert all(r["status"] == "success" for r in results)
    
    # 3. 验证最终状态
    plan_result = await plan_managing_agent.get_plan(plan_id)
    assert plan_result["status"] == "success"
    steps = plan_result["data"]["steps"]
    assert steps[0]["status"] == "in_progress"
    assert steps[1]["status"] == "completed"
    # 计划状态应该是 in_progress，因为有一个步骤还在进行中
    assert plan_result["data"]["status"] == "in_progress" 