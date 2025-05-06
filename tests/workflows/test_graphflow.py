import pytest
from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_agentchat.messages import TextMessage
from src.config.parser import load_llm_config_from_toml
from src.workflows.graphflow import build_safe_graphflow
from typing import Dict, Any, List

# 完全通用的、精简的系统提示词模板，全局共享，包含 agent_name 占位符
simple_prompt = """\
# 按以下格式回复
名字: {agent_name}
来源: 如果是第一条消息填"user"；如果是其他agent发送的消息填发送者名字；否则填"无"
分析: 解释你判断来源的依据
输出: 你的处理结果"""

def parse_message(msg: TextMessage) -> Dict[str, str]:
    """简单解析带冒号的键值对消息"""
    if not isinstance(msg, TextMessage):
        raise ValueError(f"消息类型错误,期望TextMessage,实际为{type(msg)}")
        
    if not isinstance(msg.content, str):
        raise ValueError(f"消息内容类型错误,期望str,实际为{type(msg.content)}")
        
    result = {}
    for line in msg.content.strip().split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            if not value:  # 空值检查
                raise ValueError(f"键'{key}'的值不能为空")
            result[key] = value
            
    # 检查必需字段
    required = {"名字", "来源", "分析", "输出"}
    missing = required - set(result.keys())
    if missing:
        raise ValueError(f"缺少必需的字段:{missing}")
        
    return result

@pytest.fixture
def model_client():
    """创建LLM客户端"""
    return load_llm_config_from_toml()

@pytest.mark.asyncio
async def test_sequence_flow(model_client):
    agent_a = AssistantAgent(
        name="agent_a",
        system_message=simple_prompt.format(agent_name="agent_a"),
        model_client=model_client
    )
    
    agent_b = AssistantAgent(
        name="agent_b",
        system_message=simple_prompt.format(agent_name="agent_b"),
        model_client=model_client
    )
    
    agent_c = AssistantAgent(
        name="agent_c",
        system_message=simple_prompt.format(agent_name="agent_c"),
        model_client=model_client
    )
    
    # 2. 构建顺序流图
    builder = DiGraphBuilder()
    builder.add_node(agent_a)
    builder.add_node(agent_b)
    builder.add_node(agent_c)
    builder.add_edge(agent_a, agent_b) # A -> B
    builder.add_edge(agent_b, agent_c) # B -> C
    
    # 3. 创建GraphFlow
    flow = GraphFlow(
        participants=[agent_a, agent_b, agent_c],
        graph=builder.build()
    )
    
    # 4. 运行并收集消息
    raw_events = []
    task_content = "一个测试流程" # 使用极其简单的任务指令
    task = TextMessage(content=task_content, source="user")
    async for event in flow.run_stream(task=task):
        if isinstance(event, TextMessage):
            raw_events.append(event)
            print(f"\n--- Event --- Source: {event.source} ---")
            print(f"Content:\n{event.content}")
            print(f"--------------------------")

    # 5. 解析和验证结构化消息及顺序
    agent_text_messages: List[TextMessage] = [event for event in raw_events if isinstance(event, TextMessage) and event.source != "user"]

    assert len(agent_text_messages) == 3, \
        f"期望从智能体 (A, B, C) 收到3条消息，实际收到 {len(agent_text_messages)} 条"

    # 验证消息顺序
    actual_sources = [msg.source for msg in agent_text_messages]
    expected_sources = ["agent_a", "agent_b", "agent_c"]
    assert actual_sources == expected_sources, \
        f"消息来源顺序错误。期望 {expected_sources}, 实际 {actual_sources}"

    # 解析结构化消息
    parsed_messages = []
    for msg in agent_text_messages:
        try:
            content = parse_message(msg)
            parsed_messages.append(content)
        except ValueError as e:
            assert False, f"解析来自 {msg.source} 的消息失败: {e}\n原始消息:\n{msg.content}"

    # 验证消息内容
    assert parsed_messages[0]["名字"] == "agent_a" and parsed_messages[0]["来源"] == "user"
    assert parsed_messages[1]["名字"] == "agent_b" and parsed_messages[1]["来源"] == "agent_a"
    assert parsed_messages[2]["名字"] == "agent_c" and parsed_messages[2]["来源"] == "agent_b"

    print("\n=== test_sequence_flow 验证通过 ===")

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