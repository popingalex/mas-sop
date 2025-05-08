import asyncio
import argparse

from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken
from src.workflows.graphflow import GraphFlow
from src.config.parser import load_team_config, TeamConfig, load_llm_config_from_toml # TeamConfig is now used directly
from src.tools.plan.manager import PlanManager
from src.tools.artifact_manager import ArtifactManager
from src.workflows.graphflow import build_dynamic_coordinated_graphflow

from autogen_agentchat.ui import Console

async def main():
    parser = argparse.ArgumentParser(description='Run a team workflow dynamically.')
    parser.add_argument('team_config_path', help='Path to the team configuration YAML file or directory name under ./teams.')
    parser.add_argument('initial_message', nargs='?', default=None, help='Initial message to start the workflow (optional).')
    args = parser.parse_args()

    team_config: TeamConfig = load_team_config(args.team_config_path) # Explicitly type hint
    initial_message_content = args.initial_message or team_config.task

    plan_manager = PlanManager()
    artifact_manager = ArtifactManager()
    model_client = load_llm_config_from_toml()

    flow: GraphFlow = build_dynamic_coordinated_graphflow(
        team_config=team_config,
        model_client=model_client,
        plan_manager_instance=plan_manager, 
        artifact_manager_instance=artifact_manager
    )

    cancellation_token = CancellationToken()
    await Console(flow.run_stream(task=initial_message_content, cancellation_token=cancellation_token))

if __name__ == "__main__":
    asyncio.run(main()) 