import pytest
from src.tools.plan.manager import PlanManager
from src.tools.plan.agent import PlanManagingAgent
from src.config.parser import load_llm_config_from_toml
from src.types.plan_types import Plan, Step, Task # Updated path

@pytest.fixture
def plan_manager(tmp_path):
    log_dir = tmp_path / "test_logs"
    log_dir.mkdir()
    return PlanManager(log_dir=str(log_dir))

@pytest.fixture
def plan_agent(plan_manager):
    model_client = load_llm_config_from_toml()
    if model_client is None:
        pytest.skip("LLM Client could not be loaded, skipping agent tests.")
    return PlanManagingAgent(
        plan_manager=plan_manager,
        model_client=model_client,
        system_message="你是一个计划管理专员，负责通过工具函数管理计划和步骤，包括步骤中的任务。"
    )

@pytest.mark.asyncio
async def test_plan_agent_llm_plan_crud(plan_agent, plan_manager):
    """Test basic plan CRUD via LLM agent"""
    plan_title = "LLM计划CRUD测试"
    plan_desc = "测试LLM创建、查询、删除计划"
    await plan_agent.run(task=f"请帮我创建一个计划，标题是 '{plan_title}'，描述是 '{plan_desc}'。请以JSON格式返回。")
    
    # Verify creation
    plans_resp = plan_manager.list_plans()
    assert plans_resp["status"] == "success"
    plan = next((p for p in plans_resp["data"] if p["title"] == plan_title), None)
    assert plan is not None, f"Plan '{plan_title}' not found after creation attempt."
    plan_id = plan["id"]
    
    await plan_agent.run(task=f"请查询ID为'{plan_id}'的计划详情。请以JSON格式返回。")
    # Add assertion for query result if needed
    
    await plan_agent.run(task=f"请删除ID为'{plan_id}'的计划。请以JSON格式返回。")
    
    # Verify deletion
    plans_after_resp = plan_manager.list_plans()
    assert plans_after_resp["status"] == "success"
    assert not any(p["id"] == plan_id for p in plans_after_resp["data"]), f"Plan '{plan_id}' was not deleted."

@pytest.mark.asyncio
async def test_plan_agent_llm_step_task_crud(plan_agent, plan_manager):
    """Test step and task CRUD via LLM agent"""
    plan_title = "Step和Task测试计划"
    plan_desc = "测试LLM管理步骤和任务"
    await plan_agent.run(task=f"创建一个计划，标题为'{plan_title}'，描述为'{plan_desc}'。")
    plan = next((p for p in plan_manager.list_plans()["data"] if p["title"] == plan_title), None)
    assert plan is not None
    plan_id = plan["id"]

    # Add a step with a task
    step1_desc = "步骤1：包含一个任务"
    step1_assignee = "agent1"
    task1_id = "t1"
    task1_name = "任务1.1"
    task1_desc = "步骤1的第一个任务"
    # LLM might struggle with complex JSON in prompt, keep it simple or use structured tool input if possible
    await plan_agent.run(task=f"请在ID为'{plan_id}'的计划中添加一个新步骤，描述为'{step1_desc}'，负责人是'{step1_assignee}'。在这个步骤里添加一个任务，任务ID是'{task1_id}'，名称是'{task1_name}'，描述是'{task1_desc}'。")
    
    # Verify step and task addition
    plan = plan_manager.get_plan(plan_id)["data"]
    assert len(plan["steps"]) > 0, "Step was not added."
    step1 = plan["steps"][0]
    assert step1["description"] == step1_desc
    assert step1["assignee"] == step1_assignee
    assert len(step1["tasks"]) > 0, "Task was not added to step."
    assert step1["tasks"][0]["task_id"] == task1_id
    assert step1["tasks"][0]["name"] == task1_name
    step1_id = step1["id"] # Get the assigned step ID

    # Update the step
    step1_new_desc = "步骤1-已更新描述"
    step1_new_status = "in_progress"
    await plan_agent.run(task=f"请将ID为'{plan_id}'的计划中ID为'{step1_id}'的步骤的描述改为'{step1_new_desc}'，状态改为'{step1_new_status}'。")
    
    # Verify step update
    plan = plan_manager.get_plan(plan_id)["data"]
    step1_updated = plan["steps"][0]
    assert step1_updated["description"] == step1_new_desc
    assert step1_updated["status"] == step1_new_status

    # Update the task
    task1_new_status = "completed"
    await plan_agent.run(task=f"请将ID为'{plan_id}'的计划中步骤ID为'{step1_id}'内任务ID为'{task1_id}'的状态改为'{task1_new_status}'。")
    
    # Verify task update and status propagation
    plan = plan_manager.get_plan(plan_id)["data"]
    task1_updated = plan["steps"][0]["tasks"][0]
    assert task1_updated["status"] == task1_new_status
    # Since it's the only task and it's completed, the step should also be completed
    assert plan["steps"][0]["status"] == "completed", "Step status did not update after task completion."
    # Plan status should also become completed if it was the only step
    assert plan["status"] == "completed", "Plan status did not update after step completion."
    
    # Cleanup
    await plan_agent.run(task=f"请删除ID为'{plan_id}'的计划。")
    assert not any(p["id"] == plan_id for p in plan_manager.list_plans()["data"]), "Cleanup failed: Plan not deleted." 