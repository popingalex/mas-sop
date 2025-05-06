import pytest
from src.tools.plan.manager import PlanManager
from src.tools.plan.agent import PlanManagingAgent
from src.config.parser import load_llm_config_from_toml

@pytest.fixture
def plan_manager(tmp_path):
    log_dir = tmp_path / "test_logs"
    log_dir.mkdir()
    return PlanManager(log_dir=str(log_dir))

@pytest.fixture
def plan_agent(plan_manager):
    model_client = load_llm_config_from_toml()
    return PlanManagingAgent(
        plan_manager=plan_manager,
        model_client=model_client,
        system_message="你是一个计划管理专员，负责通过工具函数管理计划和步骤。"
    )

@pytest.mark.asyncio
async def test_plan_agent_llm_plan_crud(plan_agent, plan_manager):
    await plan_agent.run(task="请帮我创建一个标题为'LLM计划CRUD'的计划，报告人是llm_user。请以JSON格式返回。")
    plans = plan_manager.list_plans()["data"]
    plan = next((p for p in plans if p["title"] == "LLM计划CRUD"), None)
    assert plan is not None
    plan_id = str(plan["id"])
    await plan_agent.run(task=f"请查询ID为'{plan_id}'的计划详情。请以JSON格式返回。")
    await plan_agent.run(task=f"请删除ID为'{plan_id}'的计划。请以JSON格式返回。")
    plans_after = plan_manager.list_plans()["data"]
    assert not any(p["id"] == plan["id"] for p in plans_after)

@pytest.mark.asyncio
async def test_plan_agent_llm_step_crud(plan_agent, plan_manager):
    await plan_agent.run(task="创建一个标题为'Step测试计划'的计划，报告人是step_user。请以JSON格式返回。")
    plan = next((p for p in plan_manager.list_plans()["data"] if p["title"] == "Step测试计划"), None)
    assert plan is not None
    plan_id = str(plan["id"])
    await plan_agent.run(task=f"请在ID为'{plan_id}'的计划中添加一个标题为'步骤1'，负责人是agent1的步骤。请以JSON格式返回。")
    plan = plan_manager.get_plan(plan_id)["data"]
    assert any(s["title"] == "步骤1" and s["assignee"] == "agent1" for s in plan["steps"])
    await plan_agent.run(task=f"请将ID为'{plan_id}'的计划的第0个步骤的标题改为'步骤1-已更新'，状态改为in_progress。请以JSON格式返回。")
    plan = plan_manager.get_plan(plan_id)["data"]
    assert plan["steps"][0]["title"] == "步骤1-已更新"
    assert plan["steps"][0]["status"] == "in_progress"
    await plan_agent.run(task=f"请查询ID为'{plan_id}'的计划的所有步骤。请以JSON格式返回。")
    await plan_agent.run(task=f"请删除ID为'{plan_id}'的计划。请以JSON格式返回。")
    assert not any(p["id"] == plan["id"] for p in plan_manager.list_plans()["data"]) 