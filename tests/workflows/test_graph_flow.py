import pytest
from autogen_agentchat.agents import AssistantAgent, MessageFilterAgent
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_agentchat.messages import TextMessage
from src.config.parser import load_llm_config_from_toml
from src.workflows.graphflow import build_sop_graphflow
from typing import Dict, Any, List, TypedDict, Literal
from autogen_agentchat.agents import MessageFilterConfig, PerSourceFilter

FixedField = Literal["raw", "name", "source", "reason", "output", "author"]
class DictMessage(TypedDict, total=False):
    raw: str
    name: str
    source: str
    reason: str
    output: str
    author: str

def parse_message(msg: TextMessage) -> DictMessage:
    """简单解析带冒号的键值对消息"""
    if not isinstance(msg, TextMessage):
        raise ValueError(f"消息类型错误,期望TextMessage,实际为{type(msg)}")
        
    if not isinstance(msg.content, str):
        raise ValueError(f"消息内容类型错误,期望str,实际为{type(msg.content)}")
        
    result = DictMessage(raw=msg.content, author=msg.source)
    for line in msg.content.strip().split('\n'):
        if ':' in line:
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()

            if value:
                result[key] = value
                
        
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
你是{agent_name}:
name: 你的名字
source: 如果是第一条消息填"user"；如果是其他agent发送的消息填发送者名字；否则填"无"
reason: 解释你判断来源的依据
output: """

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
    task_content = "一个测试流程" # 使用极其简单的任务指令
    task = TextMessage(content=task_content, source="user")
    parsed_agent_messages: List[DictMessage] = [] # 存储解析后的Agent消息

    async for event in flow.run_stream(task=task):
        if isinstance(event, TextMessage):
            if event.source == "user":
                print(f"DEBUG: user message content:\n{event.content}")
            else:
                parsed_message = parse_message(event)
                print(f"Msg: {parsed_message['source']} > {parsed_message['name']}")
                print(f"  author: {parsed_message['author']}")
                print(f"  reason: {parsed_message['reason']}")
                print(f"  output: {parsed_message.get('output')}")
                print(f"--------------------------")
                parsed_agent_messages.append(parsed_message)

    # 5. 解析和验证结构化消息及顺序
    assert len(parsed_agent_messages) == 3, \
        f"期望从智能体 (A, B, C) 收到3条消息，实际收到 {len(parsed_agent_messages)} 条"

    # 验证消息顺序
    actual_sources = [msg.get("author") for msg in parsed_agent_messages]
    expected_sources = ["agent_a", "agent_b", "agent_c"]
    assert actual_sources == expected_sources, \
        f"消息来源顺序错误。期望 {expected_sources}, 实际 {actual_sources}"

    # 验证消息内容
    assert parsed_agent_messages[0]["name"] == "agent_a" and parsed_agent_messages[0].get("source") == "user"
    assert parsed_agent_messages[1]["name"] == "agent_b" and parsed_agent_messages[1].get("source") == "agent_a"
    assert parsed_agent_messages[2]["name"] == "agent_c" and parsed_agent_messages[2].get("source") == "agent_b"


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
    
    base_worker_prompt_template = """
你是 {agent_name}
按以下格式回复
name: 你的名字
source: 参考上一条消息中的'name:'字段填发送者。如果是第一条消息则填"user"。
reason: 解释你判断来源的依据、你的任务和输出。
output: {output_desc}"""

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

    worker_a = AssistantAgent(
        name="worker_a",
        system_message=base_worker_prompt_template.format(
            agent_name="worker_a",
            output_desc=worker_generic_output_desc
        ),
        model_client=model_client
    )

    worker_a = MessageFilterAgent(
        name="worker_a",
        wrapped_agent=worker_a,
        filter=MessageFilterConfig(per_source=[
            PerSourceFilter(source="user", position="first", count=1), # 暂时移除 user 消息
            PerSourceFilter(source="coordinator", position="last", count=1)
        ])
    )

    worker_b = AssistantAgent(
        name="worker_b",
        system_message=base_worker_prompt_template.format(
            agent_name="worker_b",
            output_desc=worker_generic_output_desc
        ),
        model_client=model_client
    )

    worker_b = MessageFilterAgent(
        name="worker_b",
        wrapped_agent=worker_b,
        filter=MessageFilterConfig(per_source=[
            PerSourceFilter(source="user", position="first", count=1), # 暂时移除 user 消息
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
    builder.add_node(worker_a) # 直接使用 worker_a_core
    builder.add_node(worker_b) # 直接使用 worker_b_core
    builder.add_node(stop_agent)

    builder.set_entry_point(coordinator) # 取消注释，恢复显式入口点设置

    builder.add_edge(coordinator, worker_a, condition="TO_WORKER_A") # 边指向 worker_a_core
    builder.add_edge(coordinator, worker_b, condition="TO_WORKER_B") # 边指向 worker_b_core
    builder.add_edge(coordinator, stop_agent, condition="DONE")
    builder.add_edge(worker_a, coordinator) # 边来自 worker_a_core
    builder.add_edge(worker_b, coordinator) # 边来自 worker_b_core

    # flow = GraphFlow(participants=builder.get_participants(), graph=builder.build())
    # 确保参与者列表也更新
    flow = GraphFlow(
        participants=[coordinator, worker_a, worker_b, stop_agent], # 显式列出参与者
        graph=builder.build()
    )

    # raw_events: List[TextMessage] = [] # 旧的类型提示
    parsed_agent_messages: List[DictMessage] = [] # 存储解析后的Agent消息

    async for event in flow.run_stream(task="测试消息"):
        if isinstance(event, TextMessage):
            if event.source == "user":
                print(f"DEBUG: user message content:\n{event.content}")
            else:
                parsed_message = parse_message(event)
                print(f"Msg:  {parsed_message['source']} > {parsed_message['name']}")
                print(f"  author: {parsed_message['author']}")
                print(f"  reason: {parsed_message['reason']}")
                print(f"  output: {parsed_message['output']}")
                print("-" * 40)
                parsed_agent_messages.append(parsed_message)

    # 添加详细的断言来验证消息流和内容
    assert len(parsed_agent_messages) == 6, f"期望处理6条Agent消息，实际处理了 {len(parsed_agent_messages)} 条"

    # 消息 1: coordinator from user, output TO_WORKER_A
    msg1 = parsed_agent_messages[0]
    assert msg1["name"] == "coordinator", f"Msg1 名字错误: {msg1['name']}"
    assert msg1["source"] == "user", f"Msg1 来源错误: {msg1['source']}"
    assert msg1["output"] == "TO_WORKER_A", f"Msg1 输出错误: {msg1['output']}"

    # 消息 2: worker_a from coordinator
    msg2 = parsed_agent_messages[1]
    assert msg2["name"] == "worker_a", f"Msg2 名字错误: {msg2['name']}"
    assert msg2["source"] == "coordinator", f"Msg2 来源错误: {msg2['source']}"

    # 消息 3: coordinator from worker_a, output TO_WORKER_B
    msg3 = parsed_agent_messages[2]
    assert msg3["name"] == "coordinator", f"Msg3 名字错误: {msg3['name']}"
    assert msg3["source"] == "worker_a", f"Msg3 来源错误: {msg3['source']}"
    assert msg3["output"] == "TO_WORKER_B", f"Msg3 输出错误: {msg3['output']}"

    # 消息 4: worker_b from coordinator
    msg4 = parsed_agent_messages[3]
    assert msg4["name"] == "worker_b", f"Msg4 名字错误: {msg4['name']}"
    # 在没有 MessageFilterAgent 的情况下，worker_b 看到的直接上一条 Agent 消息是 coordinator 的，但其内容是 TO_WORKER_B
    # LLM 可能会将来源判断为 coordinator，这是可接受的
    assert msg4["source"] == "coordinator", f"Msg4 来源错误: {msg4['source']}" 

    # 消息 5: coordinator from worker_b, output DONE
    msg5 = parsed_agent_messages[4]
    assert msg5["name"] == "coordinator", f"Msg5 名字错误: {msg5['name']}"
    assert msg5["source"] == "worker_b", f"Msg5 来源错误: {msg5['source']}"
    assert msg5["output"] == "DONE", f"Msg5 输出错误: {msg5['output']}"

    # 消息 6: stop_agent from coordinator
    msg6 = parsed_agent_messages[5]
    assert msg6["name"] == "stop_agent", f"Msg6 名字错误: {msg6['name']}"

    print(f"\n=== test_nexus_flow (No MessageFilterAgent, coordinator activation='any', Parsed Events with Asserts) completed run_stream ===")