import pytest
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import GraphFlow
from src.config.parser import load_llm_config_from_toml
from src.workflows.graphflow import build_safe_graphflow

@pytest.fixture
def model_client():
    """创建LLM客户端"""
    return load_llm_config_from_toml()

def test_build_safe_graphflow_with_two_agents(model_client):
    """测试 build_safe_graphflow 对两个 agent 的构建"""
    agent1 = AssistantAgent(
        name="agent1",
        system_message="You are agent1.",
        model_client=model_client
    )
    agent2 = AssistantAgent(
        name="agent2",
        system_message="You are agent2.",
        model_client=model_client
    )
    flow = build_safe_graphflow([agent1, agent2])
    # 应返回 GraphFlow 对象
    assert isinstance(flow, GraphFlow)
    # 节点数量应为2（不包括 _StopAgent）
    assert len([n for n in flow._graph.nodes]) == 2
    # 参与者中不包含 _StopAgent
    participants = [p for p in flow._participants if not p.__class__.__name__ == "_StopAgent"]
    assert len(participants) == 2 