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
    from src.config.parser import load_team_config, TeamConfig, AgentConfig
    from src.agents.base_agent import SOPAgent # Assuming SOPAgent is the primary type for now
    from src.tools.plan.manager import PlanManager # Assuming PlanManager path
    from src.tools.artifact_manager import ArtifactManager # Assuming ArtifactManager path
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
        from src.config.parser import load_team_config, TeamConfig, AgentConfig
        from src.agents.base_agent import SOPAgent
        from src.tools.plan.manager import PlanManager
        from src.tools.artifact_manager import ArtifactManager
        # from src.utils.logging import setup_logging

# --- Console Import ---
from autogen_agentchat.ui import Console # Import Console

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

    # --- 4. Create Entry Agent ---
    entry_agent = None
    for agent_config in team_config.agents:
        if agent_config.is_entry_point:
            entry_agent = SOPAgent(
                name=agent_config.name,
                agent_config=agent_config,
                model_client=None,  # TODO: Initialize model client
                plan_manager=plan_manager,
                artifact_manager=artifact_manager
            )
            break

    if not entry_agent:
        logger.error("No entry point agent found in team configuration")
        return
        
    # --- 5. Create Initial Message ---
    initial_message = TextMessage(
        content=args.initial_message,
        source="user"
    )

    # --- 6. Start Workflow ---
    try:
        # Create cancellation token
        cancellation_token = CancellationToken()
        
        # Process the initial message
        async for response in entry_agent.on_messages_stream(
            messages=[initial_message],
            cancellation_token=cancellation_token
        ):
            if hasattr(response, 'chat_message'):
                logger.info(f"Response from {response.chat_message.source}: {response.chat_message.content}")
        
        logger.success("Workflow completed successfully.")

    except Exception as e:
        logger.exception("Error during workflow execution.")
        return

if __name__ == "__main__":
    asyncio.run(main()) 