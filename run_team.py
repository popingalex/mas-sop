import asyncio
import argparse
import os
from datetime import datetime

from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken
from src.workflows.graphflow import GraphFlow
from src.config.parser import load_team_config, TeamConfig, load_llm_config_from_toml # TeamConfig is now used directly
from src.tools.plan.manager import PlanManager
from src.tools.artifact_manager import ArtifactManager
from src.workflows.graphflow import build_sop_graphflow

from autogen_agentchat.ui import Console

async def main():
    parser = argparse.ArgumentParser(description='Run a team workflow dynamically.')
    parser.add_argument('team_config_path', help='Path to the team configuration YAML file or directory name under ./teams.')
    parser.add_argument('initial_message', nargs='?', default=None, help='Initial message to start the workflow (optional).')
    args = parser.parse_args()

    team_config: TeamConfig = load_team_config(args.team_config_path) # Explicitly type hint
    initial_message_content = args.initial_message or team_config.task

    # 自动生成日志目录 logs/{队伍名}_{时间戳}
    log_dir = os.path.join("logs", f"{team_config.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}")
    os.makedirs(log_dir, exist_ok=True)

    plan_manager = PlanManager(log_dir=log_dir)
    artifact_manager = ArtifactManager()
    model_client = load_llm_config_from_toml()

    flow: GraphFlow = build_sop_graphflow(
        team_config=team_config,
        model_client=model_client,
        plan_manager_instance=plan_manager, 
        artifact_manager_instance=artifact_manager
    )

    cancellation_token = CancellationToken()
    # await Console(flow.run_stream(task=initial_message_content, cancellation_token=cancellation_token))
    try:
        async for event in flow.run_stream(task=initial_message_content, cancellation_token=cancellation_token):
            print("\n==== New Event ====")
            print(f"Type: {type(event)}")
            if hasattr(event, 'source'):
                print(f"Source: {event.source}")
            if hasattr(event, 'role'):
                print(f"Role: {event.role}")
            if hasattr(event, 'content'):
                print(f"Content:\n{event.content}")
            if hasattr(event, 'metadata'):
                print(f"Metadata: {event.metadata}")
            print(f"Raw event: {event}")
    except Exception as e:
        import traceback
        print("\n[ERROR] Exception during flow.run_stream:")
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main()) 