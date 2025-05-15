import asyncio
import argparse
import os
from datetime import datetime

from autogen_agentchat.messages import TextMessage, ToolCallRequestEvent, ToolCallSummaryMessage, ToolCallExecutionEvent
from autogen_core import CancellationToken
# from src.workflows.graphflow import GraphFlow # GraphFlow is imported by build_sop_graphflow
from src.config.parser import load_team_config, TeamConfig, load_llm_config_from_toml
# from src.tools.plan.manager import PlanManager # Will be created in build_sop_graphflow
# from src.tools.artifact_manager import ArtifactManager # Will be created in build_sop_graphflow
from src.workflows.graphflow import build_sop_graphflow, GraphFlow # Ensure GraphFlow is imported if build_sop_graphflow returns it
from src.workflows.swarmflow import run_swarm as swarmflow_run_swarm
from loguru import logger  # 新增
from autogen_core.models._types import FunctionExecutionResult

from src.llm.utils import maybe_structured

# --- 新增：GraphFlow流程 ---
def run_graphflow(team_config, model_client, log_dir, initial_message_content):
    flow: GraphFlow = build_sop_graphflow(
        team_config=team_config,
        model_client=model_client,
        log_dir=log_dir
    )
    cancellation_token = CancellationToken()
    return flow.run_stream(task=initial_message_content, cancellation_token=cancellation_token)

# --- 公用输出解析 ---
def parse_and_print_output(event_stream):
    from autogen_agentchat.base import TaskResult
    async def _parse():
        async for event in event_stream:
            if isinstance(event, (ToolCallRequestEvent, ToolCallSummaryMessage)):
                continue
            print(f"\n==== New Event {type(event)} ====")
            # 工具调用结果单独处理
            if isinstance(event, ToolCallExecutionEvent):
                execution_result = event.content[-1]
                print(f"[FunctionExecutionResult] name: {execution_result.name}")
                if execution_result.name.startswith("transfer_to"):
                    continue
                else:
                    resp = maybe_structured(execution_result.content)
                    if resp and isinstance(resp, dict):
                        status = resp.get("status")
                        message = resp.get("message")
                        print(f"  status: {status}")
                        print(f"  message: {message}")
                continue
            if isinstance(event, TaskResult):
                total_prompt_tokens = 0
                total_completion_tokens = 0
                for msg in event.messages:
                    usage = getattr(msg, 'models_usage', None)
                    if usage is None:
                        continue
                    total_prompt_tokens += getattr(usage, 'prompt_tokens', 0)
                    total_completion_tokens += getattr(usage, 'completion_tokens', 0)
                print(f"[TaskResult] total_messages={len(event.messages)}, total_prompt_tokens={total_prompt_tokens}, total_completion_tokens={total_completion_tokens}")
                continue
            if hasattr(event, 'source'):
                print(f"Source: {event.source}")
            if hasattr(event, 'role'):
                print(f"Role: {event.role}")
            if hasattr(event, 'content'):
                print(f"Content:\n{event.content}")
            if hasattr(event, 'metadata'):
                print(f"Metadata: {event.metadata}")
    return _parse

async def main():
    parser = argparse.ArgumentParser(description='Run a team workflow dynamically.')
    parser.add_argument('team_config_path', help='Path to the team configuration YAML file or directory name under ./teams.')
    parser.add_argument('initial_message', nargs='?', default=None, help='Initial message to start the workflow (optional).')
    parser.add_argument('--flow', choices=['graphflow', 'swarm'], default='graphflow', help='Choose workflow type.')
    args = parser.parse_args()

    team_config: TeamConfig = load_team_config(args.team_config_path)
    initial_message_content = args.initial_message or team_config.task

    # 自动生成日志目录 logs/{队伍名}_{时间戳}
    log_dir = os.path.join("logs", f"{team_config.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(log_dir, exist_ok=True)
    logger.add(os.path.join(log_dir, "run.log"), encoding="utf-8", enqueue=True, backtrace=True, diagnose=True)  # 新增日志文件输出

    # plan_manager = PlanManager(log_dir=log_dir) # Removed
    # artifact_manager = ArtifactManager() # Removed
    model_client = load_llm_config_from_toml()

    if args.flow == 'graphflow':
        event_stream = run_graphflow(team_config, model_client, log_dir, initial_message_content)
    else:
        event_stream = swarmflow_run_swarm(team_config, model_client, log_dir, initial_message_content)

    parse_fn = parse_and_print_output(event_stream)
    try:
        await parse_fn()
    except Exception as e:
        import traceback
        print("\n[ERROR] Exception during flow.run_stream:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 