import pytest
from uuid import uuid4, UUID
from datetime import datetime
from src.tools.plan.manager import PlanManager, Plan, Step, Note, PlanStatus, StepStatus
from src.tools.errors import ErrorMessages

@pytest.fixture
def temp_log_dir(tmp_path):
    """创建临时日志目录"""
    log_dir = tmp_path / "test_logs"
    log_dir.mkdir()
    return str(log_dir)

@pytest.fixture
def plan_manager(temp_log_dir):
    """创建PlanManager实例"""
    return PlanManager(log_dir=temp_log_dir)

def test_plan_lifecycle(plan_manager):
    """测试计划的完整生命周期：创建、查询、更新状态、删除"""
    # 1. 创建计划
    title = "Test Plan"
    reporter = "test_user"
    create_result = plan_manager.create_plan(
        title=title,
        reporter=reporter
    )
    assert create_result["status"] == "success"
    assert create_result["data"]["title"] == title
    assert create_result["data"]["reporter"] == reporter
    assert create_result["data"]["status"] == "not_started"
    plan_id = str(create_result["data"]["id"])
    
    # 2. 查询计划
    get_result = plan_manager.get_plan(plan_id)
    assert get_result["status"] == "success"
    assert get_result["data"]["title"] == title
    assert get_result["data"]["reporter"] == reporter
    
    # 3. 更新状态
    update_result = plan_manager.update_plan_status(
        plan_id_str=plan_id,
        status="in_progress"
    )
    assert update_result["status"] == "success"
    assert update_result["data"]["status"] == "in_progress"
    
    # 4. 删除计划
    delete_result = plan_manager.delete_plan(plan_id)
    assert delete_result["status"] == "success"
    
    # 5. 验证删除
    get_result = plan_manager.get_plan(plan_id)
    assert get_result["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id) == get_result["message"]

def test_plan_steps_management(plan_manager):
    """测试计划步骤的管理：创建计划带步骤、添加步骤、更新步骤、添加笔记"""
    # 1. 创建带步骤的计划
    steps_data = [
        {"title": "Step 1", "assignee": "agent1", "content": "Step 1 content"}
    ]
    create_result = plan_manager.create_plan(
        title="Test Plan with Steps",
        reporter="test_user",
        steps_data=steps_data
    )
    assert create_result["status"] == "success"
    assert len(create_result["data"]["steps"]) == 1
    plan_id = str(create_result["data"]["id"])
    
    # 2. 添加新步骤
    add_step_result = plan_manager.add_step(
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
    update_result = plan_manager.update_step(
        plan_id_str=plan_id,
        step_index=0,
        update_data=update_data
    )
    assert update_result["status"] == "success"
    assert update_result["data"]["title"] == "Updated Step 1"
    assert update_result["data"]["status"] == "in_progress"
    
    # 4. 添加笔记
    note_result = plan_manager.add_note_to_step(
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
    plan_result = plan_manager.get_plan(plan_id)
    assert plan_result["status"] == "success"
    assert plan_result["data"]["status"] == "in_progress"

def test_plan_error_cases(plan_manager):
    """测试计划操作的错误情况"""
    # 1. 创建重复ID的计划
    plan_id = str(uuid4())
    first_result = plan_manager.create_plan(
        title="Plan 1",
        reporter="user1",
        plan_id_str=plan_id
    )
    assert first_result["status"] == "success"
    
    duplicate_result = plan_manager.create_plan(
        title="Plan 2",
        reporter="user2",
        plan_id_str=plan_id
    )
    assert duplicate_result["status"] == "error"
    assert ErrorMessages.PLAN_EXISTS.format(plan_id=plan_id) == duplicate_result["message"]
    
    # 2. 获取不存在的计划
    nonexistent_id = str(uuid4())
    nonexistent_result = plan_manager.get_plan(nonexistent_id)
    assert nonexistent_result["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str=nonexistent_id) == nonexistent_result["message"]
    
    # 3. 更新不存在的步骤
    invalid_step_result = plan_manager.update_step(
        plan_id_str=plan_id,
        step_index=999,
        update_data={"title": "Invalid"}
    )
    assert invalid_step_result["status"] == "error"
    assert ErrorMessages.PLAN_NO_STEPS.format(plan_id=plan_id) == invalid_step_result["message"]
    
    # 4. 使用无效的计划状态
    invalid_status = "invalid_status"
    valid_statuses = ("not_started", "in_progress", "completed", "error")
    invalid_status_result = plan_manager.update_plan_status(
        plan_id_str=plan_id,
        status=invalid_status
    )
    assert invalid_status_result["status"] == "error"
    assert ErrorMessages.PLAN_INVALID_STATUS.format(
        status=invalid_status,
        valid_statuses=valid_statuses
    ) == invalid_status_result["message"]

def test_plan_with_parent_step(plan_manager):
    """测试带父步骤ID的计划管理"""
    # 1. 创建父计划
    parent_result = plan_manager.create_plan(
        title="Parent Plan",
        reporter="test_user",
        steps_data=[{"title": "Parent Step", "assignee": "agent1"}]
    )
    assert parent_result["status"] == "success"
    parent_id = str(parent_result["data"]["id"])
    parent_step_id = "0"  # 第一个步骤的ID
    
    # 2. 创建子计划
    parent_step_ref = f"{parent_id}/{parent_step_id}"
    child_result = plan_manager.create_plan(
        title="Child Plan",
        reporter="test_user",
        parent_step_id=parent_step_ref
    )
    assert child_result["status"] == "success"
    assert child_result["data"]["parent_step_id"] == parent_step_ref

def test_tool_list(plan_manager):
    """测试工具列表完整性"""
    tools = plan_manager.tool_list()
    expected_tools = {
        "create_plan",
        "get_plan",
        "list_plans",
        "delete_plan",
        "update_plan_status",
        "add_step",
        "update_step",
        "add_note_to_step"
    }
    assert set(tools) == expected_tools 