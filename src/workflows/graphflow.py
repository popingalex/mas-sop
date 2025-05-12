from typing import List, Dict, Any, Optional, TYPE_CHECKING
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent, MessageFilterAgent, MessageFilterConfig, PerSourceFilter
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_core.models import ChatCompletionClient # 假设这是您的模型客户端基类型
import json
from unittest.mock import MagicMock # 用于模拟PlanManager
from string import Template

# 假设SOPAgent, AgentConfig, PlanManager可以从您的项目中正确导入
# 您需要确保这些导入路径是正确的
from src.config.parser import AgentConfig, TeamConfig # Pydantic模型
from src.tools.plan.manager import PlanManager # 您的PlanManager类
from src.tools.artifact_manager import ArtifactManager # Added import
from src.tools.storage import FileStorage # Added import
from loguru import logger # 可选，用于日志记录
from src.agents.sop_agent import SOPAgent, TurnManager
from src.agents.sop_manager import SOPManager
from src.agents.sop_terminator import SOPTerminator


# --- 系统提示词模板 ---

SOP_MANAGER_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK = """
You are a SOPManager Agent. Your primary role is to manage a multi-step plan and coordinate other agents.

INITIAL TASK HANDLING:
When you receive an initial task description from the user (source: 'user'), your first responsibility is to formulate a structured top-level plan.
For the initial interaction, you MUST use the following predefined JSON plan and embed it into your 'reason' field: {predefined_top_plan_json}
Then, based on this plan, identify the first pending task and its assignee.
Your output MUST be "HANDOFF_TO_[AssigneeNameFromPlan]".

SUBSEQUENT TASK HANDLING:
When you receive a message from a worker agent with "output: TASK_COMPLETE":
1. Update the status of their completed task to "completed" in your current plan (maintain in 'reason').
2. Find the next pending task.
3. If found, output "HANDOFF_TO_[AssigneeNameOfNextTask]".
4. If no more tasks are "pending" (all are "completed"), output "ALL_TASKS_DONE".

Always include the FULL and CURRENT plan (as a valid JSON list of dictionaries) in your 'reason' field. Each task object in the plan should have "id", "task_id", "assignee", "status", "description".

Respond STRICTLY in format:
name: SOPManager
source: [sender_name or 'user']
reason: Current Plan: [JSON plan string]. [Notes].
output: [HANDOFF_TO_AssigneeName | ALL_TASKS_DONE]
"""

STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK = """
You are StopAgent. Confirm plan completion when told by SOPManager.
Respond STRICTLY in format:
name: StopAgent
source: SOPManager
reason: ALL_TASKS_DONE received.
output: TERMINATE
"""

def build_sop_graphflow(
    team_config: TeamConfig, # 直接接收TeamConfig Pydantic模型
    model_client: ChatCompletionClient,
    log_dir: str # Changed from plan_manager_instance and artifact_manager_instance
) -> GraphFlow:
    """
    构建SOP多智能体团队的标准GraphFlow流程：
    - SOPManager为唯一流程协调者
    - 所有执行节点均为SOPAgent
    - StopAgent为终止节点
    - 支持条件路由、任务分派、流程终止
    """
    # Instantiate Storage and Managers here
    storage = FileStorage(base_dir=log_dir)
    turn_manager = TurnManager()  # 先创建
    plan_manager = PlanManager(turn_manager, storage=storage)  # 必须传 turn_manager
    artifact_manager = ArtifactManager(turn_manager, storage=storage)  # 也必须传 turn_manager

    sop_manager_pydantic_config = AgentConfig(
        name="SOPManager",
        agent="SOPManager",
        prompt="You are the SOPManager, responsible for managing the SOP flow. You will formulate a plan based on the user's request and the available workflow templates."
    )
    if team_config.nexus_settings: 
        try:
            user_sop_manager_settings = team_config.nexus_settings.copy()
            user_sop_manager_settings.setdefault("name", "SOPManager")
            user_sop_manager_settings.setdefault("agent", "SOPManager")
            if "prompt" not in user_sop_manager_settings or not user_sop_manager_settings["prompt"]:
                user_sop_manager_settings["prompt"] = sop_manager_pydantic_config.prompt
            sop_manager_pydantic_config = AgentConfig(**user_sop_manager_settings) 
        except Exception as e:
            logger.warning(f"Error applying sop_manager_settings from team_config: {e}. Using defaults for SOPManager.")

    sop_manager_agent = SOPManager(
        name="SOPManager",
        agent_config=sop_manager_pydantic_config,
        model_client=model_client,
        plan_manager=plan_manager, # Use newly created instance
        artifact_manager=artifact_manager, # Use newly created instance
        team_config=team_config,
        turn_manager=turn_manager
    )

    sop_agents: List[SOPAgent] = []

    if not team_config.agents:
        logger.warning("team_config.agents is empty. No SOPAgents或StopAgent将被创建。")
    else:
        for agent_conf_model in team_config.agents:
            sop_agent_instance = SOPAgent(
                name=agent_conf_model.name,
                agent_config=agent_conf_model,
                model_client=model_client,
                plan_manager=plan_manager,
                artifact_manager=artifact_manager,
                turn_manager=turn_manager,
                prompt=agent_conf_model.prompt
            )
            sop_agents.append(sop_agent_instance)

    stop_agent_instance = SOPTerminator(
        name="SOPTerminator",
        system_message=STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(nexus_agent_name="SOPManager"),
        model_client=model_client
    )

    builder = DiGraphBuilder()
    all_graph_participants: List[AssistantAgent] = [sop_manager_agent]
    builder.add_node(sop_manager_agent, activation="any")
    for sop in sop_agents:
        builder.add_node(sop)
        builder.add_edge(sop_manager_agent, sop, condition=f"HANDOFF_TO_{sop.name}")
        builder.add_edge(sop, sop_manager_agent)
        # all_graph_participants.append(sop)
    builder.add_node(stop_agent_instance)
    builder.add_edge(sop_manager_agent, stop_agent_instance, condition="ALL_TASKS_DONE")
    # all_graph_participants.append(stop_agent_instance)
    builder.set_entry_point(sop_manager_agent)
    graph = builder.build()
    logger.success(f"SOP graph built with SOPManager '{sop_manager_agent.name}' and {len(sop_agents)} SOP agents.")
    return GraphFlow(participants=builder.get_participants(), graph=graph) 