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

# 通用的基础提示词模板
base_prompt = """\
# 按以下格式回复
名字: {agent_name}
来源: 如果是第一条消息填"user"；如果是其他agent发送的消息填发送者名字；否则填"无"
分析: 解释你判断来源的依据
输出: {output_desc}"""

@pytest.fixture
def model_client():
    """创建LLM客户端"""
    return load_llm_config_from_toml()

@pytest.mark.asyncio
async def test_sequence_flow(model_client):
    sequence_prompt = base_prompt.format(
        output_desc="空着就行"
    )

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
async def test_nexus_flow(model_client, need_stop_agent: bool = True):
    worker_prompt = base_prompt.format(
        output_desc="空着就行"
    )

    # 定义worker信息
    worker_info = {
        "worker_a": "擅长分析和规划，适合处理需要思考的任务",
        "worker_b": "擅长执行和实现，适合处理具体的操作任务"
    }
    
    coordinator = AssistantAgent(
        name="coordinator",
        system_message=base_prompt.format(
            agent_name="coordinator",
            output_desc=f"""你的处理结果。作为coordinator，你需要：
1. 可选的worker有: {', '.join(worker_info.keys())}
2. 每个worker的特点是:
{chr(10).join(f'   - {name}: {desc}' for name, desc in worker_info.items())}
3. 根据任务内容选择合适的worker
4. 在输出中说明选择了哪个worker及选择原因
5. 如果已完成3轮循环，包含"DONE"；否则包含"CONTINUE"。"""
        ),
        model_client=model_client
    )
    
    worker_a = AssistantAgent(
        name="worker_a",
        system_message=worker_prompt.format(agent_name="worker_a"),
        model_client=model_client
    )
    
    worker_b = AssistantAgent(
        name="worker_b",
        system_message=worker_prompt.format(agent_name="worker_b"),
        model_client=model_client
    )
    
    participants = [coordinator, worker_a, worker_b]
    
    # 根据需要添加stop_agent
    if need_stop_agent:
        stop_agent = AssistantAgent(
            name="stop_agent",
            system_message=base_prompt.format(
                agent_name="stop_agent",
                output_desc="确认任务已完成，流程结束。"
            ),
            model_client=model_client
        )
        participants.append(stop_agent)
    
    # 构建线性流图
    builder = DiGraphBuilder()
    builder.add_node(coordinator)  # coordinator 作为起始节点
    builder.add_node(worker_a)
    builder.add_node(worker_b)
    
    # 设置起始节点
    builder.set_entry_point(coordinator)
    
    # 添加基本边
    builder.add_edge(coordinator, worker_a, condition="CONTINUE")  # 继续循环时发给 worker_a
    builder.add_edge(coordinator, worker_b, condition="CONTINUE")  # 继续循环时发给 worker_b
    builder.add_edge(worker_a, coordinator)  # worker_a 返回给 coordinator
    builder.add_edge(worker_b, coordinator)  # worker_b 返回给 coordinator
    
    # 根据需要添加stop_agent节点和边
    if need_stop_agent:
        builder.add_node(stop_agent)
        builder.add_edge(coordinator, stop_agent, condition="DONE")  # 结束时发给 stop_agent
    
    flow = GraphFlow(
        participants=participants,
        graph=builder.build()
    )
    
    # 运行并收集消息
    raw_events = []
    task = TextMessage(content="执行3轮循环后结束", source="user")
    async for event in flow.run_stream(task=task):
        if isinstance(event, TextMessage):
            raw_events.append(event)
            print(f"\n--- Event --- Source: {event.source} ---")
            print(f"Content:\n{event.content}")
            print(f"--------------------------")
    
    # 解析和验证消息
    agent_messages: List[TextMessage] = [event for event in raw_events if isinstance(event, TextMessage) and event.source != "user"]
    
    # 验证消息顺序
    actual_sources = [msg.source for msg in agent_messages]
    print(f"\n实际消息顺序: {actual_sources}")
    
    # 解析结构化消息
    parsed_messages = []
    for msg in agent_messages:
        try:
            content = parse_message(msg)
            parsed_messages.append(content)
        except ValueError as e:
            assert False, f"解析来自 {msg.source} 的消息失败: {e}\n原始消息:\n{msg.content}"
    
    # 验证消息内容
    # 1. coordinator 第一条消息来源应该是 user
    assert parsed_messages[0]["名字"] == "coordinator" and parsed_messages[0]["来源"] == "user", \
        "coordinator 第一条消息来源错误"
        
    # 2. worker_a/worker_b 的消息来源都应该是 coordinator
    worker_messages = [msg for msg in parsed_messages if msg["名字"].startswith("worker")]
    for msg in worker_messages:
        assert msg["来源"] == "coordinator", \
            f"worker 消息来源错误: {msg}"
            
    # 3. coordinator 后续消息来源都应该是 worker_a 或 worker_b
    coordinator_messages = [msg for msg in parsed_messages if msg["名字"] == "coordinator"][1:]  # 跳过第一条
    for msg in coordinator_messages:
        assert msg["来源"].startswith("worker"), \
            f"coordinator 消息来源错误: {msg}"
            
    # 4. 如果有stop_agent,其消息来源应该是 coordinator
    if need_stop_agent:
        stop_messages = [msg for msg in parsed_messages if msg["名字"] == "stop_agent"]
        assert len(stop_messages) == 1, "应该只有一条 stop_agent 消息"
        assert stop_messages[0]["来源"] == "coordinator", \
            f"stop_agent 消息来源错误: {stop_messages[0]}"
        
    print("\n=== test_nexus_flow 验证通过 ===")

@pytest.mark.asyncio
async def test_nexus_flow_with_filter_agent(model_client):
    """用MessageFilterAgent控制流程，不用condition。"""
    worker_info = {
        "worker_a": "擅长分析和规划，适合处理需要思考的任务",
        "worker_b": "擅长执行和实现，适合处理具体的操作任务"
    }
    coordinator = AssistantAgent(
        name="coordinator",
        system_message=base_prompt.format(
            agent_name="coordinator",
            output_desc=f"""你的处理结果。作为coordinator，你需要：\n1. 可选的worker有: {', '.join(worker_info.keys())}\n2. 每个worker的特点是:\n{chr(10).join(f'   - {name}: {desc}' for name, desc in worker_info.items())}\n3. 根据任务内容选择合适的worker\n4. 在输出中说明选择了哪个worker及选择原因\n5. 输出格式最后一行必须是: 目标worker: worker_a 或 worker_b；如需终止流程，输出'DONE'。"""
        ),
        model_client=model_client
    )
    worker_a = AssistantAgent(
        name="worker_a",
        system_message=base_prompt.format(agent_name="worker_a", output_desc="空着就行"),
        model_client=model_client
    )
    worker_b = AssistantAgent(
        name="worker_b",
        system_message=base_prompt.format(agent_name="worker_b", output_desc="空着就行"),
        model_client=model_client
    )
    from autogen_agentchat.agents import MessageFilterConfig, PerSourceFilter, MessageFilterAgent
    filtered_worker_a = MessageFilterAgent(
        name="worker_a",
        wrapped_agent=worker_a,
        filter=MessageFilterConfig(per_source=[PerSourceFilter(source="coordinator", position="last", count=1)])
    )
    filtered_worker_b = MessageFilterAgent(
        name="worker_b",
        wrapped_agent=worker_b,
        filter=MessageFilterConfig(per_source=[PerSourceFilter(source="coordinator", position="last", count=1)])
    )
    stop_agent = AssistantAgent(
        name="stop_agent",
        system_message="流程终止。",
        model_client=model_client
    )
    participants = [coordinator, filtered_worker_a, filtered_worker_b, stop_agent]
    builder = DiGraphBuilder()
    builder.add_node(coordinator)
    builder.add_node(filtered_worker_a)
    builder.add_node(filtered_worker_b)
    builder.add_node(stop_agent)
    builder.add_edge(coordinator, filtered_worker_a, condition="CONTINUE")
    builder.add_edge(coordinator, filtered_worker_b, condition="CONTINUE")
    builder.add_edge(filtered_worker_a, coordinator)
    builder.add_edge(filtered_worker_b, coordinator)
    builder.add_edge(coordinator, stop_agent, condition="DONE")
    builder.set_entry_point(coordinator)
    flow = GraphFlow(participants=participants, graph=builder.build())
    raw_events = []
    # 让coordinator输出末尾为DONE，确保能走到stop_agent
    task = TextMessage(content="测试filter agent流程，终止流程请输出DONE", source="user")
    try:
        async for event in flow.run_stream(task=task):
            if isinstance(event, TextMessage):
                raw_events.append(event)
                print(f"\n--- Event --- Source: {event.source} ---")
                print(f"Content:\n{event.content}")
                print(f"--------------------------")
    except RuntimeError as e:
        if "No available speakers found" not in str(e):
            raise
    # 验证最后一条消息是stop_agent
    assert raw_events[-1].source == "stop_agent"
    print("\n=== test_nexus_flow_with_filter_agent 验证通过 ===")

@pytest.mark.asyncio
async def test_nexus_flow_with_condition_output(model_client):
    """用不同condition严格控制流程分支，先a后b再done，并用MessageFilterAgent限制上下文。"""
    worker_info = {
        "worker_a": "擅长分析和规划，适合处理需要思考的任务",
        "worker_b": "擅长执行和实现，适合处理具体的操作任务"
    }
    coordinator = AssistantAgent(
        name="coordinator",
        system_message=(
            base_prompt.format(
                agent_name="coordinator",
                output_desc=(
                    "你是流程协调者。你的决策规则如下：\n"
                    "1. 如果收到user的消息，必须把任务分配给worker_a，输出末尾加'CONTINUE_A'。\n"
                    "2. 如果收到worker_a的消息，必须把任务分配给worker_b，输出末尾加'CONTINUE_B'。\n"
                    "3. 如果收到worker_b的消息，必须终止流程，输出末尾加'DONE'。\n"
                    "4. 你的输出末尾只能是CONTINUE_A、CONTINUE_B或DONE，严格遵守。"
                )
            )
        ),
        model_client=model_client
    )
    worker_a_core = AssistantAgent(
        name="worker_a",
        system_message=base_prompt.format(
            agent_name="worker_a",
            output_desc="你只能回复coordinator，不能分配任务或终止流程，且回复内容不能包含CONTINUE_A、CONTINUE_B、DONE等关键词。"
        ),
        model_client=model_client
    )
    worker_b_core = AssistantAgent(
        name="worker_b",
        system_message=base_prompt.format(
            agent_name="worker_b",
            output_desc="你只能回复coordinator，不能分配任务或终止流程，且回复内容不能包含CONTINUE_A、CONTINUE_B、DONE等关键词。"
        ),
        model_client=model_client
    )
    filtered_worker_a = MessageFilterAgent(
        name="worker_a",
        wrapped_agent=worker_a_core,
        filter=MessageFilterConfig(per_source=[PerSourceFilter(source="coordinator", position="last", count=1)])
    )
    filtered_worker_b = MessageFilterAgent(
        name="worker_b",
        wrapped_agent=worker_b_core,
        filter=MessageFilterConfig(per_source=[PerSourceFilter(source="coordinator", position="last", count=1)])
    )
    stop_agent = AssistantAgent(
        name="stop_agent",
        system_message=base_prompt.format(
            agent_name="stop_agent",
            output_desc="确认任务已完成，流程结束。"
        ),
        model_client=model_client
    )
    participants = [coordinator, filtered_worker_a, filtered_worker_b, stop_agent]
    builder = DiGraphBuilder()
    builder.add_node(coordinator)
    builder.add_node(filtered_worker_a)
    builder.add_node(filtered_worker_b)
    builder.add_node(stop_agent)
    builder.set_entry_point(coordinator)
    builder.add_edge(coordinator, filtered_worker_a, condition="CONTINUE_A")
    builder.add_edge(coordinator, filtered_worker_b, condition="CONTINUE_B")
    builder.add_edge(coordinator, stop_agent, condition="DONE")
    builder.add_edge(filtered_worker_a, coordinator)
    builder.add_edge(filtered_worker_b, coordinator)
    flow = GraphFlow(participants=participants, graph=builder.build())
    raw_events = []
    # 明确要求流程必须严格走完三步
    task = TextMessage(content="请严格按规则：先分配给worker_a（CONTINUE_A），收到worker_a回复后分配给worker_b（CONTINUE_B），收到worker_b回复后终止（DONE）。所有agent必须严格遵守分工和流程！", source="user")
    try:
        async for event in flow.run_stream(task=task):
            print(f"[DEBUG] event type: {type(event).__name__}, source: {getattr(event, 'source', None)}")
            if hasattr(event, 'content'):
                print(f"[DEBUG] content: {getattr(event, 'content', '')[:100]}")
            if isinstance(event, TextMessage):
                raw_events.append(event)
                print(f"\n--- Event --- Source: {event.source} ---")
                print(f"Content:\n{event.content}")
                print(f"--------------------------")
    except RuntimeError as e:
        if "No available speakers found" not in str(e):
            raise
    # 辅助打印所有event的source序列和content摘要
    print("[DEBUG] all event sources:", [e.source for e in raw_events])
    print("[DEBUG] all event contents:")
    for e in raw_events:
        print(f"  {e.source}: {e.content[:80]}")
    # 验证最后一条消息是stop_agent
    assert raw_events[-1].source == "stop_agent"
    print("\n=== test_nexus_flow_with_condition_output 验证通过 ===")

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