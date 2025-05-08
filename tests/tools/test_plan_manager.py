import pytest
from uuid import uuid4, UUID
from datetime import datetime
from src.tools.plan.manager import PlanManager
from src.types.plan import Plan, Step, Task, PlanStatus, StepStatus, TaskStatus
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
    title = "Test Plan Lifecycle"
    description = "Testing create, get, update status, delete"
    create_result = plan_manager.create_plan(
        title=title,
        description=description
    )
    assert create_result["status"] == "success"
    assert create_result["data"]["title"] == title
    assert create_result["data"]["description"] == description
    assert create_result["data"]["status"] == "not_started"
    plan_id = create_result["data"]["id"]
    
    # 2. 查询计划
    get_result = plan_manager.get_plan(plan_id)
    assert get_result["status"] == "success"
    assert get_result["data"]["title"] == title
    assert get_result["data"]["description"] == description
    
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
    get_result_after_delete = plan_manager.get_plan(plan_id)
    assert get_result_after_delete["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id) == get_result_after_delete["message"]

def test_plan_steps_and_tasks_management(plan_manager):
    """测试步骤和任务的管理：创建带步骤和任务的计划、添加步骤、更新步骤、添加任务、更新任务"""
    # 1. 创建带步骤和任务的计划
    initial_task = Task(id="t1.1", name="Initial Task", description="First task of first step")
    initial_step = Step(index=0, id="step_0", description="First Step", assignee="agent1", tasks=[initial_task])
    
    create_result = plan_manager.create_plan(
        title="Test Plan with Steps and Tasks",
        description="A plan to test step and task management",
        steps=[initial_step]
    )
    assert create_result["status"] == "success"
    plan_data = create_result["data"]
    plan_id = plan_data["id"]
    assert len(plan_data["steps"]) == 1
    assert plan_data["steps"][0]["description"] == "First Step"
    assert plan_data["steps"][0]["index"] == 0
    assert plan_data["steps"][0]["id"] == "step_0"
    assert len(plan_data["steps"][0]["tasks"]) == 1
    assert plan_data["steps"][0]["tasks"][0]["name"] == "Initial Task"
    assert plan_data["steps"][0]["tasks"][0]["task_id"] == "t1.1"
    
    # 2. 添加新步骤
    step_to_add = Step(index=99, description="Second Step", assignee="agent2")
    add_step_result = plan_manager.add_step(
        plan_id_str=plan_id,
        step_data=step_to_add
    )
    assert add_step_result["status"] == "success"
    plan_data = add_step_result["data"]
    assert len(plan_data["steps"]) == 2
    assert plan_data["steps"][1]["description"] == "Second Step"
    assert plan_data["steps"][1]["assignee"] == "agent2"
    assert plan_data["steps"][1]["index"] == 1
    assert plan_data["steps"][1]["id"] == "step_1"
    assert not plan_data["steps"][1]["tasks"]
    
    # 3. 更新步骤
    update_step_data = {
        "description": "First Step Updated",
        "status": "in_progress",
        "assignee": "agent1_updated"
    }
    update_step_result = plan_manager.update_step(
        plan_id_str=plan_id,
        step_id_or_index=0,
        update_data=update_step_data
    )
    assert update_step_result["status"] == "success"
    updated_step_data = update_step_result["data"]
    assert updated_step_data["description"] == "First Step Updated"
    assert updated_step_data["status"] == "in_progress"
    assert updated_step_data["assignee"] == "agent1_updated"
    
    # Check plan status update
    plan_get_result = plan_manager.get_plan(plan_id)
    assert plan_get_result["data"]["status"] == "in_progress"

    # 4. 向步骤添加任务
    task_to_add = Task(id="t1.2", name="Second Task", description="Another task for step 1")
    add_task_result = plan_manager.add_task_to_step(
        plan_id_str=plan_id,
        step_id_or_index="step_0",
        task_data=task_to_add
    )
    assert add_task_result["status"] == "success"
    step1_data_after_add = add_task_result["data"]
    assert len(step1_data_after_add["tasks"]) == 2
    assert step1_data_after_add["tasks"][1]["name"] == "Second Task"
    assert step1_data_after_add["tasks"][1]["task_id"] == "t1.2"

    # 5. 更新任务状态
    update_task_data = {"status": "completed"}
    update_task_result = plan_manager.update_task_in_step(
        plan_id_str=plan_id,
        step_id_or_index="step_0",
        task_id="t1.1",
        update_data=update_task_data
    )
    assert update_task_result["status"] == "success"
    assert update_task_result["data"]["status"] == "completed"

    # Check if step status recalculated
    step1_get_result = plan_manager.get_plan(plan_id)["data"]["steps"][0]
    assert step1_get_result["status"] == "in_progress"
    assert plan_manager.get_plan(plan_id)["data"]["status"] == "in_progress"

    # 6. 更新第二个任务状态也为 completed
    update_task_data_2 = {"status": "completed"}
    update_task_result_2 = plan_manager.update_task_in_step(
        plan_id_str=plan_id,
        step_id_or_index="step_0",
        task_id="t1.2",
        update_data=update_task_data_2
    )
    assert update_task_result_2["status"] == "success"
    assert update_task_result_2["data"]["status"] == "completed"
    
    # Check if step status recalculated to completed
    step1_get_result_final = plan_manager.get_plan(plan_id)["data"]["steps"][0]
    assert step1_get_result_final["status"] == "completed"
    assert plan_manager.get_plan(plan_id)["data"]["status"] == "in_progress"

    # 7. 获取下一个待处理步骤
    next_step_result = plan_manager.get_next_pending_step(plan_id)
    assert next_step_result["status"] == "success"
    assert next_step_result["data"] is not None
    assert next_step_result["data"]["index"] == 1
    assert next_step_result["data"]["status"] == "not_started"

def test_plan_error_cases(plan_manager):
    """测试计划操作的错误情况"""
    # 1. 创建重复ID的计划
    plan_id = str(uuid4())
    first_result = plan_manager.create_plan(
        title="Plan Error 1", description="Desc 1", plan_id_str=plan_id
    )
    assert first_result["status"] == "success"
    
    duplicate_result = plan_manager.create_plan(
        title="Plan Error 2", description="Desc 2", plan_id_str=plan_id
    )
    assert duplicate_result["status"] == "error"
    assert ErrorMessages.PLAN_EXISTS.format(plan_id=plan_id) == duplicate_result["message"]
    
    # 2. 获取不存在的计划
    nonexistent_id = str(uuid4())
    nonexistent_result = plan_manager.get_plan(nonexistent_id)
    assert nonexistent_result["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str=nonexistent_id) == nonexistent_result["message"]
    
    # 3. 更新不存在的步骤
    invalid_step_result_idx = plan_manager.update_step(
        plan_id_str=plan_id,
        step_id_or_index=999,
        update_data={"description": "Invalid"}
    )
    assert invalid_step_result_idx["status"] == "error"

    # 4. 更新不存在的步骤
    invalid_step_result_id = plan_manager.update_step(
        plan_id_str=plan_id,
        step_id_or_index="nonexistent_step_id",
        update_data={"description": "Invalid"}
    )
    assert invalid_step_result_id["status"] == "error"

    # 5. 添加任务到不存在的步骤
    task_err = Task(id="t_err", name="Err Task", description="Err Desc")
    add_task_err_result = plan_manager.add_task_to_step(
        plan_id_str=plan_id,
        step_id_or_index="nonexistent_step_id",
        task_data=task_err
    )
    assert add_task_err_result["status"] == "error"

    # 6. 更新不存在的任务
    update_task_err_result = plan_manager.update_task_in_step(
        plan_id_str=plan_id,
        step_id_or_index="step_0",
        task_id="nonexistent_task_id",
        update_data={"status": "completed"}
    )
    assert update_task_err_result["status"] == "error"

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
        "add_task_to_step",
        "update_task_in_step",
        "get_next_pending_step"
    }
    assert set(tools) == expected_tools 