from typing import List, Dict, Any, Optional, TYPE_CHECKING
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent, MessageFilterAgent, MessageFilterConfig, PerSourceFilter
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_core.models import ChatCompletionClient # 假设这是您的模型客户端基类型
import json
from unittest.mock import MagicMock # 用于模拟PlanManager

# 假设SOPAgent, AgentConfig, PlanManager可以从您的项目中正确导入
# 您需要确保这些导入路径是正确的
from src.config.parser import AgentConfig, TeamConfig # Pydantic模型
from src.tools.plan.manager import PlanManager # 您的PlanManager类
from loguru import logger # 可选，用于日志记录
from src.agents.sop_agent import SOPAgent
from src.agents.sop_manager import SOPManager


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

SOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK = """
You are {agent_name}. You are a specialized agent.
You perform tasks assigned by SOPManager.
Report completion with "output: TASK_COMPLETE".

Respond STRICTLY in format:
name: {agent_name}
source: SOPManager
reason: Completed: [task description].
output: TASK_COMPLETE
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
    plan_manager_instance: PlanManager, # PlanManager现在是必需的
    artifact_manager_instance: Optional[Any] = None
) -> GraphFlow:
    """
    构建SOP多智能体团队的标准GraphFlow流程：
    - SOPManager为唯一流程协调者
    - 所有执行节点均为SOPAgent
    - StopAgent为终止节点
    - 支持条件路由、任务分派、流程终止
    """
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
        plan_manager=plan_manager_instance,
        artifact_manager=artifact_manager_instance,
        team_config=team_config
    )

    sop_agents: List[SOPAgent] = []
    stop_agent_config_from_list: Optional[AgentConfig] = None

    if not team_config.agents:
        logger.warning("team_config.agents is empty. No SOPAgents or configured StopAgent will be created.")
    else:
        for agent_conf_model in team_config.agents:
            is_stop_agent_by_name = agent_conf_model.name == "StopAgent"
            is_stop_agent_by_type = agent_conf_model.agent and agent_conf_model.agent.lower() in ["stopagent", "terminalagent"]
            if is_stop_agent_by_name or is_stop_agent_by_type:
                stop_agent_config_from_list = agent_conf_model
                logger.info(f"Found StopAgent configuration in team_config.agents: {agent_conf_model.name} (Identified by {'name' if is_stop_agent_by_name else 'agent type'})")
                continue
            sop_agent_instance = SOPAgent(
                name=agent_conf_model.name,
                agent_config=agent_conf_model,
                model_client=model_client,
                plan_manager=plan_manager_instance,
                artifact_manager=artifact_manager_instance
            )
            sop_agent_instance.system_message = f"""
你是{sop_agent_instance.name}，SOP多智能体团队成员。每当你收到SOPManager分配的任务时：
1. 先仔细阅读分配消息，找到并记住PLAN_ID（或plan_id/uuid）和SOP_TASK_ID（任务唯一标识）。
2. 操作前，先用一两句话简要说明你对任务的理解（reason/think），以及你将进行的操作。
3. 查询当前计划（plans.json或PlanManager）中SOP_TASK_ID对应的任务，确认其状态。
4. 工具调用时，务必用PLAN_ID和SOP_TASK_ID作为参数，避免用任务名或描述。
5. 只需调用 update_task_in_step 工具，将该任务状态更新为 completed，不需要真的处理任务，也不需要输出任何特定格式的文本。

【English Reminder】
You are a SOP agent. When you receive a task assignment from SOPManager:
- Always extract PLAN_ID (plan_id/uuid) and SOP_TASK_ID from the assignment message.
- Before any operation, briefly explain your understanding and intended action (reason/think).
- Always query the current plan for the task by SOP_TASK_ID before updating.
- When calling the tool, always use PLAN_ID and SOP_TASK_ID as parameters, never use task name or description.
- Only call the update_task_in_step tool to set the task status to completed. Do not actually process the task or output any formatted text.
"""
            sop_agents.append(sop_agent_instance)

    stop_agent_instance: Optional[AssistantAgent] = None
    if stop_agent_config_from_list:
        logger.info(f"Creating StopAgent '{stop_agent_config_from_list.name}' from configuration.")
        stop_agent_instance = AssistantAgent(
            name=stop_agent_config_from_list.name,
            system_message=stop_agent_config_from_list.prompt or STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(nexus_agent_name="SOPManager"),
            model_client=model_client
        )
    else:
        logger.info("StopAgent config not found in team_config.agents. Creating a default AssistantAgent for StopAgent role.")
        stop_agent_instance = AssistantAgent(
            name="StopAgent", 
            system_message=STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(nexus_agent_name="SOPManager"),
            model_client=model_client 
        )
    logger.info(f"Using StopAgent: {stop_agent_instance.name}")

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