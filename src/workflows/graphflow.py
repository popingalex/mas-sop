from typing import List, Dict, Any, Optional
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent, MessageFilterAgent, MessageFilterConfig, PerSourceFilter
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_core.models import ChatCompletionClient # 假设这是您的模型客户端基类型
import json
from unittest.mock import MagicMock # 用于模拟PlanManager

# 假设SOPAgent, AgentConfig, PlanManager可以从您的项目中正确导入
# 您需要确保这些导入路径是正确的
from src.agents.sop_agent import SOPAgent
from src.config.parser import AgentConfig # Pydantic模型
from src.tools.plan.manager import PlanManager # 您的PlanManager类
from loguru import logger # 可选，用于日志记录

# --- 系统提示词模板 ---

NEXUS_COORDINATOR_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK = """
You are a Nexus Coordinator Agent, named {nexus_agent_name}. Your primary role is to manage a multi-step plan and coordinate other agents.

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
name: {nexus_agent_name}
source: [sender_name or 'user']
reason: Current Plan: [JSON plan string]. [Notes].
output: [HANDOFF_TO_AssigneeName | ALL_TASKS_DONE]
"""

LEAF_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK = """
You are {agent_name}. You are a specialized agent.
You perform tasks assigned by {nexus_agent_name}.
Report completion with "output: TASK_COMPLETE".

Respond STRICTLY in format:
name: {agent_name}
source: {nexus_agent_name}
reason: Completed: [task description].
output: TASK_COMPLETE
"""

STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK = """
You are StopAgent. Confirm plan completion when told by {nexus_agent_name}.
Respond STRICTLY in format:
name: StopAgent
source: {nexus_agent_name}
reason: ALL_TASKS_DONE received.
output: Process complete.
"""

# --- 现有的 build_safe_graphflow 函数保持不变 ---
def build_safe_graphflow(agents: List[AssistantAgent | UserProxyAgent]) -> GraphFlow:
    """构建SAFE星型GraphFlow结构，第一个agent作为中心节点（Strategist）。
    
    执行流程：
    1. Strategist 分配任务给其他节点
    2. 其他节点执行任务并返回结果
    3. Strategist 评估结果，决定下一步操作
    
    注意：
    - GraphFlow内置了StopAgent机制，当流程需要结束时会自动触发
    - 其他节点作为叶子节点，确保图的有效性
    """
    if not agents:
        raise ValueError("agents list cannot be empty")
        
    builder = DiGraphBuilder()
    
    # 1. 第一个agent作为中心节点
    center = agents[0]
    others = agents[1:]
    
    # 2. 为其他节点添加消息过滤
    filtered_others = []
    for i, other in enumerate(others):
        # 只接收来自中心节点的最后一条消息
        filtered_other = MessageFilterAgent(
            name=f"filtered_{other.name}", # 使用唯一的名称
            wrapped_agent=other,
            filter=MessageFilterConfig(
                per_source=[PerSourceFilter(source=center.name, position="last", count=1)]
            )
        )
        filtered_others.append(filtered_other)
    
    # 3. 添加所有节点
    builder.add_node(center)
    for agent in filtered_others:
        builder.add_node(agent)
    
    # 4. 设置起始节点
    builder.set_entry_point(center)
    
    # 5. 添加单向边（中心->其他），确保其他节点是叶子节点
    for other in filtered_others:
        builder.add_edge(center, other)  # 中心 -> 其他：分配任务
    
    # 6. 构建graph并返回GraphFlow
    graph = builder.build()
    all_participants = [center] + [fo._wrapped_agent for fo in filtered_others]
    return GraphFlow(participants=all_participants, graph=graph)


# --- 新增的动态协调图构建逻辑 ---

def _create_sop_agent_from_config_dict(
    agent_config_data: Dict[str, Any],
    model_client: ChatCompletionClient,
    plan_manager_instance: Optional[PlanManager] = None
) -> SOPAgent:
    """
    辅助函数：根据从配置文件加载的字典数据实例化SOPAgent。
    SOPAgent需要一个PlanManager实例。
    """
    if plan_manager_instance is None:
        logger.warning(f"PlanManager not provided for {agent_config_data.get('name', 'UnknownAgent')}. Using MagicMock. Replace with actual PlanManager.")
        plan_manager_instance = MagicMock(spec=PlanManager)

    try:
        pydantic_agent_config = AgentConfig(**agent_config_data)
    except Exception as e:
        logger.error(f"Failed to create Pydantic AgentConfig for {agent_config_data.get('name')}: {e}. Ensure dict matches AgentConfig schema.")
        pydantic_agent_config = AgentConfig(
            name=agent_config_data.get("name", "UnnamedSOPAgent"),
            agent=agent_config_data.get("agent", "SOPAgent"),
            prompt=agent_config_data.get("prompt", ""),
        )
        logger.warning(f"Used fallback AgentConfig for {pydantic_agent_config.name}")

    agent = SOPAgent(
        name=pydantic_agent_config.name,
        agent_config=pydantic_agent_config,
        model_client=model_client,
        plan_manager=plan_manager_instance
    )
    return agent


def build_dynamic_coordinated_graphflow(
    agent_configs: List[Dict[str, Any]],
    initial_top_plan: List[Dict[str, Any]],
    model_client: ChatCompletionClient,
    plan_manager_for_agents: Optional[PlanManager] = None,
    nexus_agent_name: str = "Strategist"
) -> GraphFlow:
    """
    构建动态协调的GraphFlow。
    - 从agent_configs中识别Nexus Agent。
    - 为Nexus Agent注入特殊的协调者系统提示词（包含initial_top_plan）。
    - 为Leaf Agents和StopAgent配置它们的系统提示词。
    - 实例化所有SOPAgent并构建图。
    """
    
    nexus_config_dict = next((c for c in agent_configs if c.get("name") == nexus_agent_name), None)
    if not nexus_config_dict:
        raise ValueError(f"Nexus agent '{nexus_agent_name}' not found in agent_configs.")

    leaf_config_dicts: List[Dict[str, Any]] = []
    stop_config_dict: Optional[Dict[str, Any]] = None
    
    for cfg in agent_configs:
        if cfg.get("name") == nexus_agent_name:
            continue
        if cfg.get("name") == "StopAgent":
            stop_config_dict = cfg
        else:
            leaf_config_dicts.append(cfg)

    initial_top_plan_json_str = json.dumps(initial_top_plan)
    nexus_system_prompt = NEXUS_COORDINATOR_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(
        nexus_agent_name=nexus_agent_name,
        predefined_top_plan_json=initial_top_plan_json_str
    )
    print('DEBUG: Nexus system prompt =', nexus_system_prompt)
    
    nexus_agent = _create_sop_agent_from_config_dict(
        nexus_config_dict, model_client, plan_manager_for_agents
    )
    nexus_agent.system_message = nexus_system_prompt

    leaf_agents: List[SOPAgent] = []
    for leaf_cfg_dict in leaf_config_dicts:
        leaf_name = leaf_cfg_dict.get("name", "UnnamedLeaf")
        leaf_system_prompt = LEAF_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(
            agent_name=leaf_name,
            nexus_agent_name=nexus_agent_name
        )
        leaf_sop_agent = _create_sop_agent_from_config_dict(
            leaf_cfg_dict, model_client, plan_manager_for_agents
        )
        leaf_sop_agent.system_message = leaf_system_prompt
        leaf_agents.append(leaf_sop_agent)

    stop_agent_instance: Optional[AssistantAgent] = None
    if stop_config_dict:
        stop_system_prompt = STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(
            nexus_agent_name=nexus_agent_name
        )
        stop_agent_instance = _create_sop_agent_from_config_dict(
             stop_config_dict, model_client, plan_manager_for_agents
        )
        stop_agent_instance.system_message = stop_system_prompt
    else:
        logger.info("StopAgent config not found. Creating a default AssistantAgent for StopAgent role.")
        stop_agent_instance = AssistantAgent(
            name="StopAgent", 
            system_message=STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(nexus_agent_name=nexus_agent_name),
            model_client=model_client 
        )

    builder = DiGraphBuilder()
    builder.add_node(nexus_agent, activation="any")
    
    all_graph_participants: List[AssistantAgent] = [nexus_agent]

    for leaf in leaf_agents:
        builder.add_node(leaf)
        builder.add_edge(nexus_agent, leaf, condition=f"HANDOFF_TO_{leaf.name}")
        builder.add_edge(leaf, nexus_agent)
        all_graph_participants.append(leaf)
    
    if stop_agent_instance:
        builder.add_node(stop_agent_instance)
        builder.add_edge(nexus_agent, stop_agent_instance, condition="ALL_TASKS_DONE")
        all_graph_participants.append(stop_agent_instance)
    else:
        logger.warning("No StopAgent instance created. ALL_TASKS_DONE from Nexus will not be routed.")

    builder.set_entry_point(nexus_agent)
    graph = builder.build()
    logger.success(f"Dynamic coordinated graph built with Nexus '{nexus_agent_name}' and {len(leaf_agents)} leaf agents.")
    return GraphFlow(participants=all_graph_participants, graph=graph) 