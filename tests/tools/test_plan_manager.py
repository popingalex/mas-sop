import pytest
from src.tools.plan.manager import PlanManager
from src.types.plan import Step, Task, Plan
from src.tools.errors import ErrorMessages
from src.tools.storage import DumbStorage

@pytest.fixture
def plan_manager():
    class DummyTurnManager:
        turn = 0
    return PlanManager(turn_manager=DummyTurnManager(), storage=DumbStorage())

def test_plan_tools(plan_manager):
    # 测试create_plan - 基本场景
    step1 = Step(id="s1", name="Step1", description="step1 desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc1", assignee="A")
    ])
    create_main = plan_manager.create_plan(title="主计划", description="主计划描述", steps=[step1])
    assert create_main["status"] == "success"
    plan_id = create_main["data"]["id"]

    # 测试create_plan - 无步骤场景
    create_empty = plan_manager.create_plan(title="空计划", description="无步骤的计划", steps=None)
    assert create_empty["status"] == "success"
    assert len(create_empty["data"]["steps"]) == 0

    # 测试create_sub_plan - 基本场景
    parent_task = {"plan_id": plan_id, "step_id": "s1", "task_id": "t1"}
    create_sub = plan_manager.create_sub_plan(title="子计划", description="子计划描述", steps=[], parent_task=parent_task)
    assert create_sub["status"] == "success"

    # 测试create_sub_plan - 缺少parent_task
    create_sub_no_parent = plan_manager.create_sub_plan(title="子计划2", description="子计划描述", steps=[])
    assert create_sub_no_parent["status"] == "error"

    # 测试list_plans - 基本场景
    plans_result = plan_manager.list_plans()
    assert plans_result["status"] == "success"
    plans = plans_result["data"]
    main_plan = next(p for p in plans if p["id"] == "P1")
    assert main_plan["steps"][0]["tasks"][0]["sub_plans"][0]["id"] == "P1.1"
    empty_plan = next(p for p in plans if p["id"] == "P0")
    assert len(empty_plan["steps"]) == 0

    # 测试get_task - 基本场景
    get_task_result = plan_manager.get_task(plan_id="P1", step_id="s1", task_id="t1")
    assert get_task_result["status"] == "success"
    data = get_task_result["data"]
    assert data["task"]["id"] == "t1"
    assert data["plan_info"]["name"] == "主计划"
    assert data["step_info"]["name"] == "Step1"

    # 测试update_task - 基本场景
    update_result = plan_manager.update_task(plan_id="P1", step_id="s1", task_id="t1",
                                             update_data={"status": "completed", "sub_plan_id": "P1.2"}, author="A")
    assert update_result["status"] == "success"
    get_task_result2 = plan_manager.get_task(plan_id="P1", step_id="s1", task_id="t1")
    assert len(get_task_result2["data"]["task"]["sub_plans"]) == 2
    assert any(sp["id"] == "P1.2" for sp in get_task_result2["data"]["task"]["sub_plans"])

    # 测试update_task - 无author场景
    update_no_author = plan_manager.update_task(plan_id="P1", step_id="s1", task_id="t1",
                                             update_data={"status": "completed"}, author=None)
    assert update_no_author["status"] == "error"

    # 测试add_step - 基本场景
    new_step = Step(id="s2", name="New Step", description="New step desc", assignee="B", tasks=[])
    add_step_result = plan_manager.add_step(plan_id_str="P1", step_data=new_step)
    assert add_step_result["status"] == "success"
    assert len(add_step_result["data"]["steps"]) == 2

    # 测试add_step - 指定插入位置
    insert_step = Step(id="s3", name="Insert Step", description="Insert step desc", assignee="C", tasks=[])
    insert_result = plan_manager.add_step(plan_id_str="P1", step_data=insert_step, insert_after_index=0)
    assert insert_result["status"] == "success"
    assert len(insert_result["data"]["steps"]) == 3
    assert insert_result["data"]["steps"][1]["name"] == "Insert Step"

    # 测试delete_plan
    delete_result = plan_manager.delete_plan("P0")
    assert delete_result["status"] == "success"
    list_after_delete = plan_manager.list_plans()
    assert all(p["id"] != "P0" for p in list_after_delete["data"])

    # 测试add_task_to_step - 基本场景
    task = Task(id="t2", name="Task2", description="desc2", assignee="B")
    add_task_result = plan_manager.add_task_to_step(plan_id_str="P1", step_id_or_index="s1", task_data=task)
    assert add_task_result["status"] == "success"
    assert len(add_task_result["data"]["tasks"]) == 2

    # 测试add_task_to_step - 使用索引
    task2 = Task(id="t3", name="Task3", description="desc3", assignee="C")
    add_task_by_index = plan_manager.add_task_to_step(plan_id_str="P1", step_id_or_index=0, task_data=task2)
    assert add_task_by_index["status"] == "success"

def test_list_plans_pending(plan_manager):
    # 测试list_plans - pending场景
    step1 = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="d", assignee="A")
    ])
    create_main = plan_manager.create_plan(title="主计划", description="主计划描述", steps=[step1])
    plan = plan_manager._plans["P2"]
    plan.pending = [0, 0]
    plans_result = plan_manager.list_plans()
    assert plans_result["status"] == "success"
    plans = plans_result["data"]
    main_plan = next(p for p in plans if p["id"] == "P2")
    assert main_plan["pending"] == [0, 0]

    # 测试list_plans - 空计划列表
    plan_manager._plans.clear()
    empty_result = plan_manager.list_plans()
    assert empty_result["status"] == "success"
    assert len(empty_result["data"]) == 0

def test_plan_tools_error_cases(plan_manager):
    # 测试create_plan - 重复ID
    plan_id = "P3"
    step1 = Step(id="s1", name="Step1", description="step1 desc", assignee="A", tasks=[])
    first_result = plan_manager.create_plan(title="Plan Error 1", description="Desc 1", steps=[step1])
    assert first_result["status"] == "success"
    duplicate_result = plan_manager.create_plan(title="Plan Error 2", description="Desc 2")
    assert duplicate_result["status"] == "error"
    assert ErrorMessages.PLAN_EXISTS.format(plan_id=plan_id) == duplicate_result["message"]

    # 测试get_task - 计划不存在
    nonexistent_id = "P999"
    nonexistent_result = plan_manager.get_task(plan_id=nonexistent_id, step_id="s1", task_id="t1")
    assert nonexistent_result["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str=nonexistent_id) == nonexistent_result["message"]

    # 测试get_task - 步骤不存在
    step_not_found = plan_manager.get_task(plan_id="P3", step_id="not_exist", task_id="t1")
    assert step_not_found["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="步骤", id_str="not_exist") == step_not_found["message"]

    # 测试get_task - 任务不存在（在已存在的步骤中）
    task_not_found = plan_manager.get_task(plan_id="P3", step_id="s1", task_id="not_exist")
    assert task_not_found["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="任务", id_str="not_exist") == task_not_found["message"]

    # 测试update_task - 任务不存在
    update_task_err_result = plan_manager.update_task(plan_id="P3", step_id="s1", task_id="not_exist",
                                                     update_data={"status": "completed"}, author="A")
    assert update_task_err_result["status"] == "error"

def test_plan_operations_error_cases(plan_manager):
    """测试计划操作的错误情况"""
    # 测试delete_plan - 不存在的计划
    delete_nonexistent = plan_manager.delete_plan("nonexistent")
    assert delete_nonexistent["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str="nonexistent") == delete_nonexistent["message"]

    # 测试add_step - 计划不存在
    step = Step(id="s1", name="Step", description="desc")
    add_step_nonexistent = plan_manager.add_step(plan_id_str="nonexistent", step_data=step)
    assert add_step_nonexistent["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str="nonexistent") == add_step_nonexistent["message"]

    # 测试add_step - 索引越界
    plan = plan_manager.create_plan(title="Test Plan", description="desc")
    assert plan["status"] == "success"
    add_step_invalid_index = plan_manager.add_step(plan_id_str="test_plan", step_data=step, insert_after_index=999)
    assert add_step_invalid_index["status"] == "error"
    assert ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(index=999, plan_id="test_plan", total=0) == add_step_invalid_index["message"]

def test_task_operations_error_cases(plan_manager):
    """测试任务操作的错误情况"""
    # 创建测试计划和步骤
    step = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[])
    plan = plan_manager.create_plan(title="Test Plan", description="desc")
    assert plan["status"] == "success"

    # 测试add_task_to_step - 计划不存在
    task = Task(id="t1", name="Task1", description="desc", assignee="A")
    add_task_nonexistent_plan = plan_manager.add_task_to_step("nonexistent", "s1", task)
    assert add_task_nonexistent_plan["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str="nonexistent") == add_task_nonexistent_plan["message"]

    # 测试add_task_to_step - 步骤不存在
    add_task_nonexistent_step = plan_manager.add_task_to_step("test_plan", "nonexistent", task)
    assert add_task_nonexistent_step["status"] == "error"
    assert ErrorMessages.STEP_NOT_FOUND_BY_ID.format(step_id="nonexistent", plan_id="test_plan") == add_task_nonexistent_step["message"]

    # 测试add_task_to_step - 索引越界
    add_task_invalid_index = plan_manager.add_task_to_step("test_plan", 999, task)
    assert add_task_invalid_index["status"] == "error"
    assert ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(index=999, plan_id="test_plan", total=1) == add_task_invalid_index["message"]

    # 测试add_task_to_step - 无效的步骤索引类型
    add_task_invalid_type = plan_manager.add_task_to_step("test_plan", 1.5, task)
    assert add_task_invalid_type["status"] == "error"
    assert "step_id_or_index 必须是字符串ID或整数索引。" == add_task_invalid_type["message"]

def test_plan_status_calculation(plan_manager):
    """测试计划状态计算"""
    # 创建测试计划
    step1 = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started"),
        Task(id="t2", name="Task2", description="desc", assignee="A", status="not_started")
    ])
    step2 = Step(id="s2", name="Step2", description="desc", assignee="B", tasks=[
        Task(id="t3", name="Task3", description="desc", assignee="B", status="not_started")
    ])
    plan = plan_manager.create_plan(title="Status Test", description="desc", steps=[step1, step2])
    assert plan["status"] == "success"

    # 测试部分任务完成
    plan_manager.update_task("status_test", "s1", "t1", {"status": "completed"}, "A")
    # 手动更新步骤状态，因为 update_task 不会自动更新
    step1.status = "in_progress"
    get_plan = plan_manager.get_plan("status_test")
    assert get_plan["data"]["status"] == "in_progress"

    # 测试任务出错
    plan_manager.update_task("status_test", "s1", "t2", {"status": "error"}, "A")
    step1.status = "error"
    get_plan = plan_manager.get_plan("status_test")
    assert get_plan["data"]["status"] == "error"

    # 测试所有任务完成
    plan_manager.update_task("status_test", "s1", "t2", {"status": "completed"}, "A")
    plan_manager.update_task("status_test", "s2", "t3", {"status": "completed"}, "B")
    step1.status = "completed"
    step2.status = "completed"
    get_plan = plan_manager.get_plan("status_test")
    assert get_plan["data"]["status"] == "completed"

def test_get_pending(plan_manager):
    """测试获取待处理任务"""
    # 创建测试计划
    step = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started")
    ])
    plan = plan_manager.create_plan(title="Pending Test", description="desc", steps=[step])
    assert plan["status"] == "success"

    # 测试有待处理任务
    pending = plan_manager.get_pending("pending_test")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "pending"
    assert pending["data"]["task"]["id"] == "t1"

    # 测试完成所有任务
    plan_manager.update_task("pending_test", "s1", "t1", {"status": "completed"}, "A")
    pending = plan_manager.get_pending("pending_test")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "completed"

    # 测试子计划
    sub_step = Step(id="sub_s1", name="SubStep1", description="desc", assignee="B", tasks=[
        Task(id="sub_t1", name="SubTask1", description="desc", assignee="B", status="not_started")
    ])
    sub_plan = plan_manager.create_sub_plan(
        title="Sub Plan",
        description="desc",
        steps=[sub_step],
        parent_task={"plan_id": "pending_test", "step_id": "s1", "task_id": "t1"}
    )
    assert sub_plan["status"] == "success"

    # 测试子计划待处理任务
    pending = plan_manager.get_pending("pending_test.1")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "pending"
    assert pending["data"]["task"]["id"] == "sub_t1"

def test_get_pending_with_subplans(plan_manager):
    """测试带有子计划的待处理任务"""
    # 创建主计划
    step = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started", subplan_id="sub1")
    ])
    plan = plan_manager.create_plan(title="Main Plan", description="desc", steps=[step])
    assert plan["status"] == "success"

    # 创建子计划
    sub_step = Step(id="sub_s1", name="SubStep1", description="desc", assignee="B", tasks=[
        Task(id="sub_t1", name="SubTask1", description="desc", assignee="B", status="not_started")
    ])
    sub_plan = plan_manager.create_plan(title="Sub Plan", description="desc", steps=[sub_step])
    assert sub_plan["status"] == "success"

    # 测试有未完成的子计划任务
    pending = plan_manager.get_pending("main")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "pending"
    assert pending["data"]["task"]["id"] == "t1"

    # 完成子计划任务
    plan_manager.update_task("sub1", "sub_s1", "sub_t1", {"status": "completed"}, "B")
    sub_step.status = "completed"

    # 完成主计划任务
    plan_manager.update_task("main", "s1", "t1", {"status": "completed"}, "A")
    step.status = "completed"

    # 测试所有任务完成
    pending = plan_manager.get_pending("main")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "completed"

def test_update_task_error_cases(plan_manager):
    """测试更新任务的错误情况"""
    # 创建测试计划
    step = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started")
    ])
    plan = plan_manager.create_plan(title="Test Plan", description="desc")
    assert plan["status"] == "success"

    # 测试无效的计划ID
    update_invalid_plan = plan_manager.update_task("invalid", "s1", "t1", {"status": "completed"}, "A")
    assert update_invalid_plan["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="计划", id_str="invalid") == update_invalid_plan["message"]

    # 测试无效的步骤ID
    update_invalid_step = plan_manager.update_task("test", "invalid", "t1", {"status": "completed"}, "A")
    assert update_invalid_step["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="步骤", id_str="invalid") == update_invalid_step["message"]

    # 测试无效的任务ID
    update_invalid_task = plan_manager.update_task("test", "s1", "invalid", {"status": "completed"}, "A")
    assert update_invalid_task["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="任务", id_str="invalid") == update_invalid_task["message"]

    # 测试无效的作者
    update_no_author = plan_manager.update_task("test", "s1", "t1", {"status": "completed"}, None)
    assert update_no_author["status"] == "error"
    assert "update_task 必须传入 author" == update_no_author["message"]

def test_storage_operations(plan_manager):
    """测试存储操作的错误处理"""
    # 测试加载计划时的错误
    invalid_data = {"id": "invalid", "title": "Invalid Plan"}  # 缺少必要字段
    plan_manager.storage.save("plans", invalid_data, "invalid")
    plan_manager._load_plans()  # 应该能处理无效数据而不崩溃

    # 测试保存计划时的错误
    plan = Plan(id="test", title="Test", description="desc", steps=[])
    plan_manager.storage.save = lambda *args: exec('raise Exception("Storage error")')  # 模拟存储错误
    with pytest.raises(RuntimeError, match="计划持久化失败"):
        plan_manager._save_plan(plan)

def test_storage_operations_error_cases(plan_manager):
    """测试存储操作的错误情况"""
    # 测试加载计划时的错误
    # 1. 缺少ID的数据
    invalid_data1 = {"title": "Invalid Plan"}  # 缺少ID
    plan_manager.storage.save("plans", invalid_data1, "invalid1")

    # 2. 验证失败的数据
    invalid_data2 = {"id": "invalid2", "title": "Invalid Plan"}  # 缺少必要字段
    plan_manager.storage.save("plans", invalid_data2, "invalid2")

    # 3. 完全无效的数据
    invalid_data3 = "not a dict"
    plan_manager.storage.save("plans", invalid_data3, "invalid3")

    # 重新加载计划，应该能处理所有错误
    plan_manager._load_plans()

    # 测试保存计划时的错误
    plan = Plan(id="test", title="Test", description="desc", steps=[])
    
    # 模拟存储错误
    def raise_error(*args):
        raise Exception("Storage error")
    
    original_save = plan_manager.storage.save
    plan_manager.storage.save = raise_error
    
    with pytest.raises(RuntimeError, match="计划持久化失败"):
        plan_manager._save_plan(plan)
    
    # 恢复原始save方法
    plan_manager.storage.save = original_save 

def test_plan_completion_cases(plan_manager):
    """测试计划完成状态的各种情况"""
    # 创建主计划
    step1 = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started", subplan_id="sub1"),
        Task(id="t2", name="Task2", description="desc", assignee="A", status="not_started")
    ])
    step2 = Step(id="s2", name="Step2", description="desc", assignee="B", tasks=[
        Task(id="t3", name="Task3", description="desc", assignee="B", status="not_started")
    ])
    plan = plan_manager.create_plan(title="Main Plan", description="desc", steps=[step1, step2])
    assert plan["status"] == "success"

    # 创建子计划
    sub_step = Step(id="sub_s1", name="SubStep1", description="desc", assignee="B", tasks=[
        Task(id="sub_t1", name="SubTask1", description="desc", assignee="B", status="not_started")
    ])
    sub_plan = plan_manager.create_plan(title="Sub Plan", description="desc", steps=[sub_step])
    assert sub_plan["status"] == "success"

    # 测试子计划未完成时主计划不能完成
    plan_manager.update_task("main", "s1", "t2", {"status": "completed"}, "A")
    plan_manager.update_task("main", "s2", "t3", {"status": "completed"}, "B")
    step1.status = "in_progress"  # 因为t1还有未完成的子计划
    step2.status = "completed"
    get_plan = plan_manager.get_plan("main")
    assert get_plan["data"]["status"] == "in_progress"

    # 测试子计划完成后主计划可以完成
    plan_manager.update_task("sub1", "sub_s1", "sub_t1", {"status": "completed"}, "B")
    sub_step.status = "completed"
    plan_manager.update_task("main", "s1", "t1", {"status": "completed"}, "A")
    step1.status = "completed"
    get_plan = plan_manager.get_plan("main")
    assert get_plan["data"]["status"] == "completed"

def test_get_pending_edge_cases(plan_manager):
    """测试获取待处理任务的边缘情况"""
    # 创建主计划
    step1 = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started", subplan_id="sub1"),
        Task(id="t2", name="Task2", description="desc", assignee="A", status="not_started")
    ])
    plan = plan_manager.create_plan(title="Main Plan", description="desc", steps=[step1])
    assert plan["status"] == "success"

    # 创建子计划
    sub_step = Step(id="sub_s1", name="SubStep1", description="desc", assignee="B", tasks=[
        Task(id="sub_t1", name="SubTask1", description="desc", assignee="B", status="not_started")
    ])
    sub_plan = plan_manager.create_plan(title="Sub Plan", description="desc", steps=[sub_step])
    assert sub_plan["status"] == "success"

    # 测试子计划任务完成但主计划任务未完成
    plan_manager.update_task("sub1", "sub_s1", "sub_t1", {"status": "completed"}, "B")
    sub_step.status = "completed"
    pending = plan_manager.get_pending("main")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "pending"
    assert pending["data"]["task"]["id"] == "t1"

    # 测试主计划任务完成但有其他未完成任务
    plan_manager.update_task("main", "s1", "t1", {"status": "completed"}, "A")
    pending = plan_manager.get_pending("main")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "pending"
    assert pending["data"]["task"]["id"] == "t2"

def test_storage_load_error_cases(plan_manager):
    """测试加载存储时的错误情况"""
    # 测试加载不存在的计划
    plan_manager.storage.save("plans", None, "nonexistent")
    plan_manager._load_plans()

    # 测试加载格式错误的计划
    invalid_json = "{"  # 无效的JSON
    plan_manager.storage.save("plans", invalid_json, "invalid_json")
    plan_manager._load_plans()

    # 测试加载类型错误的计划
    invalid_type = 123  # 不是字典或字符串
    plan_manager.storage.save("plans", invalid_type, "invalid_type")
    plan_manager._load_plans()

    # 测试加载缺少必要字段的计划
    missing_fields = {"id": "test"}  # 缺少title和description
    plan_manager.storage.save("plans", missing_fields, "missing_fields")
    plan_manager._load_plans() 

def test_get_pending_with_subplan_id(plan_manager):
    """测试带有 subplan_id 的待处理任务"""
    # 创建主计划
    step = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started", subplan_id="sub1")
    ])
    plan = plan_manager.create_plan(title="Main Plan", description="desc", steps=[step])
    assert plan["status"] == "success"

    # 创建子计划
    sub_step = Step(id="sub_s1", name="SubStep1", description="desc", assignee="B", tasks=[
        Task(id="sub_t1", name="SubTask1", description="desc", assignee="B", status="not_started")
    ])
    sub_plan = plan_manager.create_plan(title="Sub Plan", description="desc", steps=[sub_step])
    assert sub_plan["status"] == "success"

    # 测试有未完成的子计划任务
    pending = plan_manager.get_pending("main")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "pending"
    assert pending["data"]["task"]["id"] == "t1"

    # 测试子计划不存在的情况
    plan_manager.delete_plan("sub1")
    pending = plan_manager.get_pending("main")
    assert pending["status"] == "success"
    assert pending["data"]["status"] == "pending"
    assert pending["data"]["task"]["id"] == "t1"

def test_get_pending_invalid_plan_id(plan_manager):
    """测试获取待处理任务时的无效计划ID"""
    # 测试无效的计划ID
    pending = plan_manager.get_pending("invalid")
    assert pending["status"] == "error"
    assert pending["message"] == "未找到计划: invalid"

def test_step_without_tasks(plan_manager):
    """测试没有任务的步骤状态计算"""
    # 创建没有任务的步骤
    step = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[])
    plan = plan_manager.create_plan(title="Test Plan", description="desc")
    assert plan["status"] == "success"

    # 测试步骤状态
    plan_manager._recalculate_step_status(step)
    assert step.status == "not_started"

    # 手动设置步骤状态为已完成
    step.status = "completed"
    plan_manager._recalculate_step_status(step)
    assert step.status == "completed"

def test_step_status_transitions(plan_manager):
    """测试步骤状态转换"""
    # 创建带有任务的步骤
    step = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started"),
        Task(id="t2", name="Task2", description="desc", assignee="A", status="not_started")
    ])
    plan = plan_manager.create_plan(title="Test Plan", description="desc")
    assert plan["status"] == "success"

    # 测试所有任务未开始
    plan_manager._recalculate_step_status(step)
    assert step.status == "not_started"

    # 测试部分任务完成
    step.tasks[0].status = "completed"
    plan_manager._recalculate_step_status(step)
    assert step.status == "in_progress"

    # 测试任务出错
    step.tasks[1].status = "error"
    plan_manager._recalculate_step_status(step)
    assert step.status == "error"

    # 测试所有任务完成
    step.tasks[1].status = "completed"
    plan_manager._recalculate_step_status(step)
    assert step.status == "completed"

    # 测试从未开始到进行中的转换
    step.status = "not_started"
    step.tasks[0].status = "not_started"
    step.tasks[1].status = "completed"
    plan_manager._recalculate_step_status(step)
    assert step.status == "in_progress" 

def test_load_plans_error_cases(plan_manager):
    """测试加载计划时的错误处理"""
    # 测试加载无效的JSON数据
    plan_manager.storage.save("plans", "{", "invalid_json")
    plan_manager._load_plans()

    # 测试加载无效的数据类型
    plan_manager.storage.save("plans", 123, "invalid_type")
    plan_manager._load_plans()

    # 测试加载空数据
    plan_manager.storage.save("plans", None, "empty")
    plan_manager._load_plans()

    # 测试加载无效的计划数据
    invalid_plan = {
        "id": "test",
        "title": "Test Plan",
        "description": "desc",
        "steps": [{"invalid": "data"}]  # 无效的步骤数据
    }
    plan_manager.storage.save("plans", invalid_plan, "invalid_plan")
    plan_manager._load_plans()

    # 测试加载时发生异常
    def raise_error(*args):
        raise Exception("Load error")
    
    original_load = plan_manager.storage.load
    plan_manager.storage.load = raise_error
    plan_manager._load_plans()
    plan_manager.storage.load = original_load

def test_save_plan_error_cases(plan_manager):
    """测试保存计划时的错误处理"""
    # 创建测试计划
    step = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[])
    plan = Plan(id="test", title="Test Plan", description="desc", steps=[step])

    # 模拟存储错误
    def raise_error(*args):
        raise Exception("Storage error")
    
    original_save = plan_manager.storage.save
    plan_manager.storage.save = raise_error
    
    with pytest.raises(RuntimeError, match="计划持久化失败"):
        plan_manager._save_plan(plan)
    
    # 恢复原始save方法
    plan_manager.storage.save = original_save

def test_plan_completion_with_subplans(plan_manager):
    """测试带有子计划的计划完成状态"""
    # 创建主计划
    step1 = Step(id="s1", name="Step1", description="desc", assignee="A", tasks=[
        Task(id="t1", name="Task1", description="desc", assignee="A", status="not_started", subplan_id="sub1"),
        Task(id="t2", name="Task2", description="desc", assignee="A", status="not_started")
    ])
    plan = plan_manager.create_plan(title="Main Plan", description="desc", steps=[step1])
    assert plan["status"] == "success"

    # 创建子计划
    sub_step = Step(id="sub_s1", name="SubStep1", description="desc", assignee="B", tasks=[
        Task(id="sub_t1", name="SubTask1", description="desc", assignee="B", status="not_started")
    ])
    sub_plan = plan_manager.create_plan(title="Sub Plan", description="desc", steps=[sub_step])
    assert sub_plan["status"] == "success"

    # 测试子计划不存在时主计划不能完成
    plan_manager.delete_plan("sub1")
    assert not plan_manager._is_plan_completed(plan_manager._plans["main"])

    # 重新创建子计划
    sub_plan = plan_manager.create_plan(title="Sub Plan", description="desc", steps=[sub_step])
    assert sub_plan["status"] == "success"

    # 测试子计划未完成时主计划不能完成
    assert not plan_manager._is_plan_completed(plan_manager._plans["main"])

    # 完成子计划任务
    plan_manager.update_task("sub1", "sub_s1", "sub_t1", {"status": "completed"}, "B")
    sub_step.status = "completed"

    # 完成主计划任务
    plan_manager.update_task("main", "s1", "t1", {"status": "completed"}, "A")
    plan_manager.update_task("main", "s1", "t2", {"status": "completed"}, "A")
    step1.status = "completed"
    get_plan = plan_manager.get_plan("main")
    assert get_plan["data"]["status"] == "completed"

    # 测试所有任务完成
    assert plan_manager._is_plan_completed(plan_manager._plans["main"]) 