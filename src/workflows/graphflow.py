from typing import List
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent, MessageFilterAgent, MessageFilterConfig, PerSourceFilter
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow

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
            name=f"filtered_{other.name}",
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
    all_agents = [center] + [agent._wrapped_agent for agent in filtered_others]  # 使用原始agent而不是filtered agent
    return GraphFlow(participants=all_agents, graph=graph) 