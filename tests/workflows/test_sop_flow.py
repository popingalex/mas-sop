import pytest
from autogen_agentchat.agents import AssistantAgent # MessageFilterAgent (add if needed)
from autogen_agentchat.teams import DiGraphBuilder, GraphFlow
from autogen_agentchat.messages import TextMessage
from src.config.parser import load_llm_config_from_toml, AgentConfig # Ensure AgentConfig is imported
from src.workflows.graphflow import build_sop_graphflow # Import the new function
from typing import Dict, Any, List, TypedDict, Literal
# from autogen_agentchat.agents import MessageFilterConfig, PerSourceFilter # Add if using MessageFilterAgent
import json # For plan parsing in assertions
from unittest.mock import MagicMock, AsyncMock # For mocking PlanManager
from src.agents.sop_agent import SOPAgent # Assuming SOPAgent is importable
from src.config.parser import AgentConfig # Assuming AgentConfig is importable
from src.tools.plan.manager import PlanManager
from src.types.plan_types import Plan, Step # Updated path
from loguru import logger
from src.workflows.loader import load_workflow_template, extract_plan_from_workflow_template # Import the loader and extract_plan_from_workflow_template
from src.workflows.models import WorkflowTemplate # Import the Pydantic model returned by loader
import io # For StringIO
from unittest.mock import patch # Import patch
import asyncio # For mocking async methods of PlanManager

FixedField = Literal["raw", "name", "source", "reason", "output", "author"]
class DictMessage(TypedDict, total=False):
    raw: str
    name: str
    source: str
    reason: str
    output: str
    author: str # Actual sender from TextMessage.source

def parse_message(msg: TextMessage) -> DictMessage:
    """简单解析带冒号的键值对消息"""
    if not isinstance(msg, TextMessage):
        raise ValueError(f"消息类型错误,期望TextMessage,实际为{type(msg)}")
        
    if not isinstance(msg.content, str):
        raise ValueError(f"消息内容类型错误,期望str,实际为{type(msg.content)}")
        
    result = DictMessage(raw=msg.content, author=msg.source)
    # First line might be a role declaration like "You are Strategist." or "Strategist:"
    # We should parse key-value pairs after that.
    lines_to_parse = msg.content.strip().split('\\n')
    
    # Heuristic: if the first line doesn't contain ':', it might be a preamble.
    # Or, more robustly, look for lines that DO contain ':'
    start_parsing_index = 0
    # if lines_to_parse and ':' not in lines_to_parse[0]:
    #     start_parsing_index = 1 # Skip preamble if it doesn't look like a key-value

    for line in lines_to_parse[start_parsing_index:]:
        if ':' in line:
            key, value = line.split(':', 1)
            key_cleaned = key.strip().lower() # Use lower for consistency if needed
            value_cleaned = value.strip()
            if not value_cleaned and key_cleaned != "output": # Allow empty output for some agents if needed by design
                 # Re-evaluating this: empty values can be problematic for LLMs.
                 # For 'reason', if LLM generates empty, it's an issue.
                 # For 'output', specific keywords are expected.
                 pass # Let's be more lenient here for now, assertions will catch functional errors.
            
            # Map to fixed fields if possible, otherwise store as is
            if key_cleaned in FixedField.__args__: # Check if key is one of the TypedDict keys
                 result[key_cleaned] = value_cleaned
            # else:
            # result[key_cleaned] = value_cleaned # Store other fields too if necessary

    # Ensure essential fields are present if expected from prompt
    # This basic parser might need adjustment based on LLM output variance.
    if "name" not in result and result.get("author"): # Try to infer 'name' from author if not parsed
        result["name"] = result["author"]

    return result

@pytest.fixture
def model_client():
    """创建LLM客户端"""
    return load_llm_config_from_toml()

@pytest.mark.asyncio
@pytest.mark.parametrize("team_name_to_test", ["safe-sop"]) # Add team name parameter
async def test_sop_flow_execution_with_real_components(team_name_to_test: str, model_client, caplog):
    """Tests the SOP flow by loading a team's config and running the dynamic graph with real components."""
    caplog.set_level("INFO")
    # Dynamically construct the config file path based on the team name parameter
    config_file_to_load = f"teams/{team_name_to_test}/config.yaml"

    # 1. Load configuration using src.workflows.loader.load_workflow_template
    try:
        workflow_template_obj = load_workflow_template(config_file_to_load)
        # Correctly access workflow name and template version for logging here as well if needed for consistency
        logger.info(f"Successfully loaded workflow template '{workflow_template_obj.workflow.name}' (Team: {workflow_template_obj.team_name}, Config Version: {workflow_template_obj.version}) from: {config_file_to_load}")
    except Exception as e:
        # Removed reference to TEST_CONFIG_YAML_CONTENT
        logger.error(f"TEST FAILED: load_workflow_template call failed for '{config_file_to_load}'. Error: {e}", exc_info=True)
        pytest.fail(f"load_workflow_template failed for '{config_file_to_load}': {e}")

    # 2. Extract agent configurations (List[Dict[str, Any]])
    if not hasattr(workflow_template_obj, 'agents') or not workflow_template_obj.agents:
        pytest.fail("Loaded WorkflowTemplate does not have an 'agents' attribute or it's empty.")
    
    agent_configs_from_loader: List[AgentConfig] = workflow_template_obj.agents
    agent_configs_as_dicts: List[Dict[str, Any]] = []
    for ac_model in agent_configs_from_loader:
        if isinstance(ac_model, AgentConfig): # Ensure it's the Pydantic model
            agent_configs_as_dicts.append(ac_model.model_dump(exclude_none=True))
        else:
            pytest.fail(f"Loaded agent config is not of type AgentConfig: {type(ac_model)}")

    logger.info(f"Extracted {len(agent_configs_as_dicts)} agent configurations.")

    # 2. Provide an empty list for initial_top_plan.
    #    This assumes the Nexus agent (e.g., "Strategist"), guided by its system prompt
    #    (which receives this empty plan via predefined_top_plan_json),
    #    is responsible for formulating the actual top-level plan upon receiving the initial user task.
    empty_initial_plan: List[Dict[str, Any]] = []
    logger.info(f"Providing an empty initial_top_plan to build_sop_graphflow.")

    # Use a real PlanManager instance, but mock its create_plan method for controlled testing
    real_plan_manager = PlanManager() # Instantiate a real PlanManager

    # Define what the mocked create_plan method should return (a dictionary)
    # SOPAgent._process_plan can handle a dictionary representation of a Plan.
    mock_sub_plan_dict_for_leaf = {
        "id": "leaf_mock_sub_plan_001", # Ensure required fields are present
        "title": "Mocked Internal Sub-Plan for Leaf",
        "description": "Detailed steps for leaf agent internal task, generated by mocked PlanManager.",
        "steps": [
            {"index": 1, "description": "Leaf internal sub-step 1: gather details.", "status": "pending"},
            {"index": 2, "description": "Leaf internal sub-step 2: analyze findings.", "status": "pending"},
        ]
    }

    async def mock_create_plan_for_leaf_async(task_description: str, *args, **kwargs) -> dict:
        logger.info(f"TEST: Real PlanManager's create_plan (mocked) called for task: '{task_description[:40]}...'. Returning mock sub-plan dict.")
        return mock_sub_plan_dict_for_leaf
    
    # Replace the real PlanManager's create_plan with our async mock method
    real_plan_manager.create_plan = AsyncMock(side_effect=mock_create_plan_for_leaf_async)

    # 4. Call the actual build_sop_graphflow function from src/workflows/graphflow.py
    try:
        flow = build_sop_graphflow(
            agent_configs=agent_configs_as_dicts,
            initial_top_plan=empty_initial_plan, # Pass an empty list for the plan
            model_client=model_client, # Actual LLM client
            plan_manager_for_agents=real_plan_manager, # Real PlanManager
            nexus_agent_name="Strategist" # Ensure this matches the name in config.yaml
        )
        logger.info(f"SOP graph built by build_sop_graphflow with SOPManager: Strategist")
    except Exception as e:
        logger.error(f"TEST FAILED: build_sop_graphflow call failed. Error: {e}", exc_info=True)
        pytest.fail(f"build_sop_graphflow failed: {e}")

    # 5. Run the flow with an initial event and print logs
    initial_event_description = "Urgent: Major fire at city center, multiple buildings affected, request immediate SOP execution."
    
    processed_messages_count = 0
    print(f"\n=== Test: Starting flow_run_stream for: {initial_event_description} ===")

    try:
        async for event in flow.run_stream(task=initial_event_description):
            if isinstance(event, TextMessage):
                processed_messages_count += 1
                print(f"\n<<< Message {processed_messages_count} >>>")
                print(f"    Source Agent: {event.source}")
                print(f"    Raw Content:\n-------\{event.content.strip()}\n-------")
                try:
                    parsed = parse_message(event) # Optional: for more structured logging if needed
                    print(f"    Parsed [Name]:   {parsed.get('name')}")
                    print(f"    Parsed [Source]: {parsed.get('source')}")
                    # print(f"    Parsed [Reason]: {str(parsed.get('reason', ''))[:200]}...")
                    print(f"    Parsed [Output]: {parsed.get('output')}")
                except ValueError as e_parse:
                    logger.warning(f"Could not parse message from {event.source}: {e_parse}. Raw content above.")
    except Exception as e_run:
        logger.exception(f"TEST FAILED: Error during flow.run_stream with task '{initial_event_description}'. Error details follow.")
        pytest.fail(f"Error during sop_graph_flow.run_stream: {e_run}")
                    
    print(f"\n=== Test: flow_run_stream completed. Processed {processed_messages_count} TextMessage events. ===\n")

    # 6. Basic Assertion: Ensure some messages were processed.
    assert processed_messages_count > 0, "No TextMessage events were processed by the flow, check logs."

    # Further detailed assertions on the content of parsed_agent_messages can be added here if needed,
    # similar to the previous complex test, but for now, focus is on running and observing logs.
    logger.info(f"Test 'test_sop_flow_execution_with_real_components' for team '{team_name_to_test}' completed. Review printed messages for flow verification.")

@pytest.mark.asyncio
async def test_safe_sop_full_flow():
    """完整SOP流程集成测试：加载配置，提取plan，构建GraphFlow并运行，断言每个agent都响应。"""
    # 1. 加载配置
    workflow_template = load_workflow_template("teams/safe-sop/config.yaml")
    plan_obj = extract_plan_from_workflow_template(workflow_template)
    plan = plan_obj.model_dump(exclude_none=True)  # 转为dict，兼容GraphFlow
    agent_configs = [agent.model_dump(exclude_none=True) for agent in workflow_template.agents]
    model_client = load_llm_config_from_toml()

    # 2. 构建GraphFlow
    flow = build_sop_graphflow(
        agent_configs=agent_configs,
        initial_top_plan=plan,
        model_client=model_client,
        plan_manager_for_agents=None,
        nexus_agent_name="Strategist"
    )

    # 3. 运行流程
    initial_event = "重大火灾，城市中心多栋建筑受影响，请立即执行SOP。"
    processed = []
    # 直接await async for，避免asyncio.run
    async for event in flow.run_stream(task=initial_event):
        if hasattr(event, "source") and hasattr(event, "content"):
            print(f"[{event.source}] {event.content}")
            processed.append((event.source, event.content))

    # 4. 断言
    assert any("Strategist" in src for src, _ in processed), "Nexus未响应"
    assert any("Awareness" in src for src, _ in processed), "Awareness未响应"
    assert any("Executor" in src for src, _ in processed), "Executor未响应"
    assert len(processed) > 3, "流程未完整走通"