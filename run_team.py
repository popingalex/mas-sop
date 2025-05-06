import asyncio
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger # Keep basic logger for script setup
import toml
from autogen_agentchat.messages import TextMessage
from autogen_core import CancellationToken

# --- Moved Client Import Here ---
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import ChatCompletionClient # Keep for type hints if needed

# --- Project Imports ---
# Assuming the script is run from the project root
try:
    # This allows running from root with 'python run_team.py ...'
    from src.config.parser import load_team_config, TeamConfig, AgentConfig, load_llm_config_from_toml
    from src.agents.sop_agent import SOPAgent  # 修正为sop_agent
    from src.tools.plan.manager import PlanManager # Assuming PlanManager path
    from src.tools.artifact_manager import ArtifactManager # Assuming ArtifactManager path
    from src.workflows.graphflow import build_safe_graphflow
    # TODO: Import logging setup utility if available
    # from src.utils.logging import setup_logging
except ImportError as e:
    logger.error(f"Import Error: {e}. Make sure you are running from the project root directory.")
    logger.error("Attempting to add src to sys.path for execution...")
    # Add src to path if running script directly for dev purposes
    project_root = Path(__file__).parent.resolve()
    src_path = project_root / "src"
    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))
        logger.info(f"Added {src_path} to sys.path")
        # Retry imports WITHOUT client
        from src.config.parser import load_team_config, TeamConfig, AgentConfig, load_llm_config_from_toml
        from src.agents.sop_agent import SOPAgent  # 修正为sop_agent
        from src.tools.plan.manager import PlanManager
        from src.tools.artifact_manager import ArtifactManager
        from src.workflows.graphflow import build_safe_graphflow
        # from src.utils.logging import setup_logging

# --- Console Import ---
from autogen_agentchat.ui import Console # Import Console

def instantiate_agents(team_config, plan_manager, artifact_manager, model_client):
    agents = []
    for agent_config in team_config.agents:
        agent = SOPAgent(
            name=agent_config.name,
            agent_config=agent_config,
            model_client=model_client,
            plan_manager=plan_manager,
            artifact_manager=artifact_manager
        )
        agents.append(agent)
    return agents

async def main():
    # --- 1. Parse Arguments ---
    parser = argparse.ArgumentParser(description='Run a team workflow')
    parser.add_argument('team_name', help='Name of the team to run')
    parser.add_argument('initial_message', help='Initial message to start the workflow')
    args = parser.parse_args()

    # --- 2. Load Team Configuration ---
    try:
        team_config = load_team_config(args.team_name)
        logger.info(f"Loaded configuration for team: {args.team_name}")
    except Exception as e:
        logger.error(f"Failed to load team configuration: {e}")
        return

    # --- 3. Initialize Managers ---
    plan_manager = PlanManager()
    artifact_manager = ArtifactManager()
    model_client = load_llm_config_from_toml()  # 统一用配置加载

    # 实例化所有Agent
    agents = instantiate_agents(team_config, plan_manager, artifact_manager, model_client)

    # 构建GraphFlow
    flow = build_safe_graphflow(team_config=team_config._replace(agents=agents))

    # --- 4. Create Initial Message ---
    initial_message = TextMessage(
        content=args.initial_message,
        source="user"
    )

    # --- 5. Start Workflow ---
    try:
        # Create cancellation token
        cancellation_token = CancellationToken()
        
        # 启动GraphFlow团队协作
        await Console(flow.run_stream(task=initial_message, cancellation_token=cancellation_token))
        logger.success("Workflow completed successfully.")

    except Exception as e:
        logger.exception("Error during workflow execution.")
        return

if __name__ == "__main__":
    asyncio.run(main()) 