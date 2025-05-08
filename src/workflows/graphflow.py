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

# 使用延迟导入避免循环依赖
if TYPE_CHECKING:
    from src.agents.nexus_agent import NexusAgent
    from src.agents.leaf_agent import LeafAgent

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
output: TERMINATE
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


# --- 修改后的 _create_agent_from_config_dict (原 _create_sop_agent_from_config_dict) ---
def _create_agent_from_config_dict(
    agent_config_data: Dict[str, Any],
    model_client: ChatCompletionClient,
    plan_manager_instance: Optional[PlanManager] = None,
    artifact_manager_instance: Optional[Any] = None
) -> AssistantAgent: # 返回更通用的 AssistantAgent，因为 StopAgent 可能是它
    """
    辅助函数：根据从配置文件加载的字典数据实例化正确的Agent类型。
    """
    # 在函数内部导入，避免循环导入
    from src.agents.nexus_agent import NexusAgent
    from src.agents.leaf_agent import LeafAgent
    
    if plan_manager_instance is None:
        logger.warning(f"PlanManager not provided for {agent_config_data.get('name', 'UnknownAgent')}. Using MagicMock.")
        plan_manager_instance = MagicMock(spec=PlanManager)
    
    # artifact_manager 也是可选的，如果没提供，则为 None

    try:
        # 确保agent_config_data中的所有字段都是AgentConfig模型期望的
        # Pydantic会自动忽略额外的字段，但最好是明确的
        # 我们需要从agent_config_data中获取name, prompt等核心字段
        # 以及 now the 'agent' field (string type identifier) to decide Agent type
        pydantic_agent_config = AgentConfig(**agent_config_data)
    except Exception as e:
        logger.error(f"Failed to create Pydantic AgentConfig for {agent_config_data.get('name')}: {e}.")
        # 提供一个最小化的回退配置
        pydantic_agent_config = AgentConfig(
            name=agent_config_data.get("name", "UnnamedAgent"),
            agent=agent_config_data.get("agent", "LeafAgent"), # 默认 agent 类型为 LeafAgent
            prompt=agent_config_data.get("prompt", "You are a helpful assistant."),
        )
        logger.warning(f"Used fallback AgentConfig for {pydantic_agent_config.name}")

    # Use pydantic_agent_config.agent (string identifier) to determine agent type
    agent_type_str = pydantic_agent_config.agent.lower() if pydantic_agent_config.agent else "leafagent" # Default to 'leafagent' string

    common_params = {
        "name": pydantic_agent_config.name,
        "agent_config": pydantic_agent_config, # 传递完整的Pydantic模型
        "model_client": model_client,
        "plan_manager": plan_manager_instance,
        "artifact_manager": artifact_manager_instance
    }

    if agent_type_str == "nexusagent": # Assuming 'NexusAgent' string in config
        logger.info(f"Creating NexusAgent: {pydantic_agent_config.name}")
        return NexusAgent(**common_params)
    elif agent_type_str == "leafagent": # Assuming 'LeafAgent' string in config
        logger.info(f"Creating LeafAgent: {pydantic_agent_config.name}")
        return LeafAgent(**common_params)
    # 如果未来有 OutputAgent/TerminalAgent 且它继承 BaseSOPAgent 并由此函数创建：
    # elif agent_type_str == "outputagent" or agent_type_str == "terminalagent":
    #     logger.info(f"Creating OutputAgent/TerminalAgent: {pydantic_agent_config.name}")
    #     return OutputAgent(**common_params) # 假设OutputAgent也用这些参数
    elif pydantic_agent_config.name == "StopAgent": # Keep specific name check for StopAgent if it's a basic AssistantAgent
        logger.info(f"Creating a basic AssistantAgent for StopAgent: {pydantic_agent_config.name}")
        # StopAgent可能不需要plan_manager和artifact_manager
        return AssistantAgent(
            name=pydantic_agent_config.name,
            system_message=pydantic_agent_config.prompt, # 使用config中的prompt作为system_message
            model_client=model_client
        )
    else:
        logger.warning(f"Unknown agent type string '{agent_type_str}' for {pydantic_agent_config.name} (derived from 'agent' field: '{pydantic_agent_config.agent}'). Defaulting to LeafAgent.")
        return LeafAgent(**common_params)


# --- 修改 build_dynamic_coordinated_graphflow 以使用新的创建函数和传递 artifact_manager ---
def build_dynamic_coordinated_graphflow(
    team_config: TeamConfig, # 直接接收TeamConfig Pydantic模型
    model_client: ChatCompletionClient,
    plan_manager_instance: PlanManager, # PlanManager现在是必需的
    artifact_manager_instance: Optional[Any] = None) -> GraphFlow:
    """
    构建动态协调的GraphFlow。
    - NexusAgent由框架内部创建。
    - LeafAgents从team_config.agents实例化。
    - StopAgent从team_config.agents或默认创建。
    """
    # 在函数内部导入 NexusAgent 以避免循环导入
    from src.agents.nexus_agent import NexusAgent
    from src.agents.leaf_agent import LeafAgent
    
    nexus_agent_name = team_config.properties.get("nexus_agent_name", "NexusCoordinator") if team_config.properties else "NexusCoordinator"
    
    # 为 Nexus Agent 创建 AgentConfig，添加必需的 agent 字段
    nexus_pydantic_config = AgentConfig(
        name=nexus_agent_name,
        agent="NexusAgent", # **指定 agent 类型标识**
        prompt="You are the Nexus Coordinator, responsible for managing the SOP flow. You will formulate a plan based on the user's request and the available workflow templates." # Adjusted prompt
    )
    if team_config.nexus_settings: 
        try:
            # 如果用户提供了 nexus_settings，确保它也包含 agent 字段或在这里合并
            user_nexus_settings = team_config.nexus_settings.copy()
            user_nexus_settings.setdefault("name", nexus_agent_name) # 确保 name 存在
            user_nexus_settings.setdefault("agent", "NexusAgent")    # **确保 agent 字段存在**
            # Ensure the prompt is also considered if provided, otherwise use the default
            if "prompt" not in user_nexus_settings or not user_nexus_settings["prompt"]:
                user_nexus_settings["prompt"] = nexus_pydantic_config.prompt # Use default if not in user settings
            nexus_pydantic_config = AgentConfig(**user_nexus_settings) 
            nexus_agent_name = nexus_pydantic_config.name 
        except Exception as e:
            logger.warning(f"Error applying nexus_settings from team_config: {e}. Using defaults for NexusAgent.")
            # 回退到之前创建的默认 nexus_pydantic_config (prompt was set above)

    nexus_agent = NexusAgent(
        name=nexus_pydantic_config.name,
        agent_config=nexus_pydantic_config, # This now contains the adjusted prompt
        model_client=model_client,
        plan_manager=plan_manager_instance,
        artifact_manager=artifact_manager_instance,
        team_config=team_config
    )
    # initial_top_plan_json_str = json.dumps(initial_top_plan) # REMOVED
    # The system message for NexusAgent might need to be simplified or its template changed
    # as predefined_top_plan_json is no longer available here.
    # For now, we rely on the prompt set in AgentConfig.
    # If a more complex system message is needed without initial_top_plan, the template
    # NEXUS_COORDINATOR_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK needs to be updated or
    # an alternative way to set the system message must be found.
    # nexus_agent.system_message = NEXUS_COORDINATOR_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(
    #     nexus_agent_name=nexus_agent.name
    #     # predefined_top_plan_json is removed
    # )
    # If NEXUS_COORDINATOR_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK only had nexus_agent_name and predefined_top_plan_json,
    # and predefined_top_plan_json is critical, NexusAgent's internal logic for planning needs to be robust
    # without it being pre-fed via system message in this specific way.
    # Assuming the prompt in AgentConfig is now the primary system message, or NexusAgent sets its own.
    # logger.info(f"Created NexusAgent: {nexus_agent.name}") # Removed as per user request

    # 2. 创建 LeafAgents
    leaf_agents: List[LeafAgent] = []
    stop_agent_config_from_list: Optional[AgentConfig] = None

    if not team_config.agents:
        logger.warning("team_config.agents is empty. No LeafAgents or configured StopAgent will be created.")
    else:
        for agent_conf_model in team_config.agents: # agent_conf_model is already AgentConfig Pydantic object
            # Identify StopAgent by name or by its 'agent' type string if specified
            is_stop_agent_by_name = agent_conf_model.name == "StopAgent"
            is_stop_agent_by_type = agent_conf_model.agent and agent_conf_model.agent.lower() in ["stopagent", "terminalagent"] # Example type strings
            
            if is_stop_agent_by_name or is_stop_agent_by_type:
                stop_agent_config_from_list = agent_conf_model
                logger.info(f"Found StopAgent configuration in team_config.agents: {agent_conf_model.name} (Identified by {'name' if is_stop_agent_by_name else 'agent type'})")
                continue # 不将其作为LeafAgent创建
            
            # All other agents are treated as LeafAgents by default here.
            # The previous warning about the 'role' field has been removed as per user instruction.

            # Create LeafAgent (or other specific agent types based on role if expanded)
            leaf_agent_instance = LeafAgent(
                name=agent_conf_model.name,
                agent_config=agent_conf_model, # 直接传递Pydantic模型
                model_client=model_client,
                plan_manager=plan_manager_instance,
                artifact_manager=artifact_manager_instance
            )
            leaf_agent_instance.system_message = LEAF_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(
                agent_name=leaf_agent_instance.name,
                nexus_agent_name=nexus_agent.name
            )
            leaf_agents.append(leaf_agent_instance)
            # logger.info(f"Created LeafAgent: {leaf_agent_instance.name}") # Removed as per user request

    # 3. 创建 StopAgent
    stop_agent_instance: Optional[AssistantAgent] = None
    if stop_agent_config_from_list:
        # 如果在team_config.agents中找到了StopAgent的配置
        logger.info(f"Creating StopAgent '{stop_agent_config_from_list.name}' from configuration.")
        stop_agent_instance = AssistantAgent( # StopAgent仍然是一个简单的AssistantAgent
            name=stop_agent_config_from_list.name,
            system_message=stop_agent_config_from_list.prompt or STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(nexus_agent_name=nexus_agent.name),
            model_client=model_client
        )
    else:
        logger.info("StopAgent config not found in team_config.agents. Creating a default AssistantAgent for StopAgent role.")
        stop_agent_instance = AssistantAgent(
            name="StopAgent", 
            system_message=STOP_AGENT_SYSTEM_PROMPT_TEMPLATE_FOR_FRAMEWORK.format(nexus_agent_name=nexus_agent.name),
            model_client=model_client 
        )
    logger.info(f"Using StopAgent: {stop_agent_instance.name}")

    # 4. 构建图
    builder = DiGraphBuilder()
    all_graph_participants: List[AssistantAgent] = [nexus_agent]
    
    # 添加 NexusAgent 节点，设置其激活条件为 "any"，表示任何输出都可以
    builder.add_node(nexus_agent, activation="any")

    for leaf in leaf_agents:
        builder.add_node(leaf)
        # 路由条件：当 NexusAgent 输出包含 "HANDOFF_TO_[leaf.name]" 时，转到对应的 LeafAgent
        builder.add_edge(nexus_agent, leaf, condition=f"HANDOFF_TO_{leaf.name}") 
        # LeafAgent 完成后返回到 NexusAgent
        builder.add_edge(leaf, nexus_agent, condition="TASK_COMPLETE") 
        all_graph_participants.append(leaf)
    
    # 添加 StopAgent 节点和边
    builder.add_node(stop_agent_instance)
    # 当 NexusAgent 输出 "ALL_TASKS_DONE" 时，转到 StopAgent
    builder.add_edge(nexus_agent, stop_agent_instance, condition="ALL_TASKS_DONE")
    all_graph_participants.append(stop_agent_instance)

    # 设置入口点
    builder.set_entry_point(nexus_agent)
    graph = builder.build()
    logger.success(f"Dynamic coordinated graph built with Nexus '{nexus_agent.name}' and {len(leaf_agents)} leaf agents.")
    
    # 确保所有参与者都被加入到GraphFlow的participants列表中
    return GraphFlow(participants=all_graph_participants, graph=graph) 