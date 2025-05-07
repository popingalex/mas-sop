import pytest
from autogen_agentchat.agents import AssistantAgent, MessageFilterAgent
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_agentchat.messages import TextMessage
from src.config.parser import load_llm_config_from_toml
from src.workflows.graphflow import build_safe_graphflow
from typing import Dict, Any, List
from autogen_agentchat.agents import MessageFilterConfig, PerSourceFilter


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
    # 通用的基础提示词模板
    sequence_prompt = """\
# 按以下格式回复
名字: {agent_name}
来源: 如果是第一条消息填"user"；如果是其他agent发送的消息填发送者名字；否则填"无"
分析: 解释你判断来源的依据
输出: 空着就行"""

    agent_a = AssistantAgent(
        name="agent_a",
        system_message=sequence_prompt.format(agent_name="agent_a"),
        model_client=model_client
    )
    
    agent_b = AssistantAgent(
        name="agent_b",
        system_message=sequence_prompt.format(agent_name="agent_b"),
        model_client=model_client
    )
    
    agent_c = AssistantAgent(
        name="agent_c",
        system_message=sequence_prompt.format(agent_name="agent_c"),
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

@pytest.mark.asyncio
async def test_nexus_flow(model_client):
    # """
    # 统一测试Nexus Flow。
    # 在这个版本中，我们恢复使用 MessageFilterAgent，并为其配置更完善的过滤器。
    # Worker agents 的提示词是简洁和通用的，不包含硬编码的调试标记。
    # Coordinator 的条件输出不带括号。
    # 流程顺序: user -> coordinator -> worker_a -> coordinator -> worker_b -> coordinator -> stop_agent
    # """
    
    base_worker_prompt_template = """# 按以下格式回复
名字: {agent_name}
来源: 如果是第一条消息填"user"；如果是其他agent发送的消息填发送者名字；否则填"无"
分析: 解释你判断来源的依据和你的任务。
输出: {output_desc}"""

    coordinator_output_desc = ("""
如果没有消息来源，回复 TO_WORKER_A
如果消息来自worker_a，回复 TO_WORKER_B
如果消息来自worker_b，回复 DONE
""")
    coordinator = AssistantAgent(
        name="coordinator",
        system_message=base_worker_prompt_template.format(
            agent_name="coordinator",
            output_desc=coordinator_output_desc
        ),
        model_client=model_client
    )

    worker_generic_output_desc = "任务处理中，我会将结果回复给 coordinator。"

    worker_a_core = AssistantAgent(
        name="worker_a",
        system_message=base_worker_prompt_template.format(
            agent_name="worker_a",
            output_desc=worker_generic_output_desc
        ),
        model_client=model_client
    )

    worker_b_core = AssistantAgent(
        name="worker_b",
        system_message=base_worker_prompt_template.format(
            agent_name="worker_b",
            output_desc=worker_generic_output_desc
        ),
        model_client=model_client
    )
    
    # 恢复使用 MessageFilterAgent 并配置过滤器
    filtered_worker_a = MessageFilterAgent(
        name="worker_a", # MessageFilterAgent 的 name 通常应与其 wrapped_agent 的 name 一致
        wrapped_agent=worker_a_core,
        filter=MessageFilterConfig(per_source=[
            PerSourceFilter(source="user", position="first", count=1),
            PerSourceFilter(source="coordinator", position="last", count=1)
        ])
    )

    filtered_worker_b = MessageFilterAgent(
        name="worker_b",
        wrapped_agent=worker_b_core,
        filter=MessageFilterConfig(per_source=[
            PerSourceFilter(source="user", position="first", count=1), 
            PerSourceFilter(source="coordinator", position="last", count=1)
        ])
    )

    stop_agent_output_desc = "确认任务已完成，流程结束。"
    stop_agent = AssistantAgent(
        name="stop_agent",
        system_message=base_worker_prompt_template.format(
            agent_name="stop_agent",
            output_desc=stop_agent_output_desc
        ),
        model_client=model_client
    )

    builder = DiGraphBuilder()
    builder.add_node(coordinator, activation="any")
    builder.add_node(filtered_worker_a) # 使用 filtered_worker_a
    builder.add_node(filtered_worker_b) # 使用 filtered_worker_b
    builder.add_node(stop_agent)

    builder.set_entry_point(coordinator)

    builder.add_edge(coordinator, filtered_worker_a, condition="TO_WORKER_A") # 边指向 filtered_worker_a
    builder.add_edge(coordinator, filtered_worker_b, condition="TO_WORKER_B") # 边指向 filtered_worker_b
    builder.add_edge(coordinator, stop_agent, condition="DONE")
    builder.add_edge(filtered_worker_a, coordinator) # 边来自 filtered_worker_a
    builder.add_edge(filtered_worker_b, coordinator) # 边来自 filtered_worker_b

    flow = GraphFlow(participants=builder.get_participants(), graph=builder.build())

    raw_events: List[TextMessage] = []
    task_message_content = "测试消息"
    task = TextMessage(content=task_message_content, source="user")

    print(f"\n=== Starting test_nexus_flow (Corrected: With MessageFilterAgent, Clean Prompts) ===")
    print(f"Initial task for coordinator: {task.content}")

    async for event in flow.run_stream(task=task):
        if isinstance(event, TextMessage):
            raw_events.append(event)
            print(f"\n--- Event --- Source: {event.source} ---")
            print(f"Content:\n{event.content}")
            print(f"--------------------------")
        elif hasattr(event, 'type') and event.type == 'speaker_change':
            print(f"\n--- Speaker Change --- "
                  f"Next Speaker: {getattr(event, 'next_speaker_name', 'N/A')} --- "
                  f"Reason: {getattr(event, 'reason', 'N/A')} --- "
                  f"Current Speaker: {getattr(event, 'current_speaker_name', 'N/A')}")
            if hasattr(event, 'message') and getattr(event, 'message'):
                 print(f"Speaker Change Triggering Message Content (last from {getattr(event, 'current_speaker_name', 'N/A')}):\\n{getattr(event, 'message').content if hasattr(getattr(event, 'message'), 'content') else 'N/A'}")
            print(f"--------------------------")

    print("\n--- Collected Raw Events for test_nexus_flow (Corrected) ---")
    for i, event_msg in enumerate(raw_events):
        print(f"Event {i+1} - Source: {event_msg.source}")
        print(f"Content: {event_msg.content}")
        print("---")

    assert len(raw_events) >= 2, "Expected at least user and coordinator messages."
    if len(raw_events) > 1:
        assert raw_events[1].source == "coordinator"
        assert "TO_WORKER_A" in raw_events[1].content
    if len(raw_events) > 2:
        assert raw_events[2].source == "worker_a" # filtered_worker_a 的 name 是 worker_a
        print(f"DEBUG: worker_a (filtered) full response content:\n{raw_events[2].content}")

    print("\n=== test_nexus_flow (Corrected: With MessageFilterAgent, Clean Prompts) completed run_stream ===") 