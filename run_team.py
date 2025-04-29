import asyncio
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime
from loguru import logger # Keep basic logger for script setup
import toml

# --- Moved Client Import Here ---
from autogen_ext.models.openai import OpenAIChatCompletionClient
from autogen_core.models import ChatCompletionClient # Keep for type hints if needed

# --- Project Imports ---
# Assuming the script is run from the project root
try:
    # This allows running from root with 'python run_team.py ...'
    from src.config.parser import load_config, TeamConfig, AgentConfig
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
        from src.config.parser import load_config, TeamConfig, AgentConfig
        from src.agents.base_agent import SOPAgent
        from src.tools.plan.manager import PlanManager
        from src.tools.artifact_manager import ArtifactManager
        # from src.utils.logging import setup_logging

# --- Console Import ---
from autogen_agentchat.ui import Console # Import Console

async def main(team_name: str, initial_task: str):
    """Main execution function."""
    
    # --- Load Global LLM Config (Define variables in main scope) ---
    global_llm_config = {}
    llm_model = None
    llm_api_key = None
    llm_base_url = None
    
    try:
        global_config_path = Path("config.toml")
        if global_config_path.exists():
            global_llm_config = toml.load(global_config_path)
            logger.info(f"Loaded global LLM configuration from {global_config_path}")
            
            # Assign values to variables in main scope
            config_section = global_llm_config.get("llm", {}).get("ds", {})
            required_keys = ['model', 'api_key', 'base_url']
            if not all(key in config_section for key in required_keys):
                 logger.error(f"Missing one or more required keys ({required_keys}) in 'llm.ds' section of config.toml")
                 return
            llm_model = config_section['model']
            llm_api_key = config_section['api_key']
            llm_base_url = config_section['base_url']
            logger.info(f"Using LLM: {llm_model} at {llm_base_url}")
        else:
            logger.error(f"{global_config_path} not found. Cannot proceed without LLM configuration.")
            return
    except Exception as e:
        logger.exception(f"Failed to load or parse {global_config_path}")
        return
    
    # --- Ensure LLM config was loaded successfully ---
    if not all([llm_model, llm_api_key, llm_base_url]):
         logger.error("LLM configuration could not be loaded properly. Exiting.")
         return

    # --- 1. Setup Logging and Directories ---
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_root_dir = Path("logs")
    run_log_dir = log_root_dir / f"{team_name}_{timestamp}"
    
    try:
        log_root_dir.mkdir(exist_ok=True)
        run_log_dir.mkdir(exist_ok=True)
        logger.info(f"Created run directory: {run_log_dir}")
    except OSError as e:
        logger.error(f"Failed to create log directories: {e}")
        return

    # --- REMOVED Loguru file logging setup ---
    # log_file_path = run_log_dir / "run.log"
    # logger.add(log_file_path, rotation="10 MB", level="DEBUG") 
    # logger.info(f"Logging to file: {log_file_path}")
    logger.info(f"Starting run for team '{team_name}' with task: '{initial_task}'")
    logger.info(f"Run artifacts and potential logs (if any) will be in: {run_log_dir}") # Adjusted message

    # --- 2. Load Team Configuration ---
    config_path = Path(f"teams/{team_name}/config.yaml")
    if not config_path.exists():
        logger.error(f"Configuration file not found for team '{team_name}' at {config_path}")
        return
        
    try:
        config: TeamConfig = load_config(str(config_path))
        logger.success(f"Successfully loaded configuration for team '{config.team_name}' v{config.version}")
    except Exception as e:
        logger.exception(f"Failed to load or validate configuration from {config_path}")
        return

    # --- 3. Initialize Managers ---
    try:
        # Pass the specific run directory for artifact storage
        artifact_manager = ArtifactManager(base_dir=run_log_dir) 
        # Pass the same run directory for PlanManager persistence
        plan_manager = PlanManager(log_dir=run_log_dir) 
        logger.info("Initialized PlanManager and ArtifactManager.")
        logger.debug(f"Artifacts will be saved in: {run_log_dir}")
        logger.debug(f"Plan state will be saved in: {run_log_dir / 'plans.json'}")
    except Exception as e:
        logger.exception("Failed to initialize managers.")
        return
        
    # --- 4. Initialize Agents ---
    agents = {}
    model_clients = {} # Cache clients based on config
    
    try:
        for agent_conf in config.agents:
            logger.info(f"Initializing agent: {agent_conf.name} (Type: {agent_conf.agent})")

            if agent_conf.agent == "SOPAgent":
                 # Now llm_model and llm_base_url are accessible here
                 client_key = f"{llm_model}_{llm_base_url}" 

                 if client_key not in model_clients:
                     logger.info(f"Creating new ChatCompletionClient for {client_key}")
                     try:
                         # Instantiate the actual client using config.toml values AND model_info
                         model_client = OpenAIChatCompletionClient(
                             model=llm_model,
                             api_key=llm_api_key,
                             base_url=llm_base_url,
                             model_info={ # Explicitly provide model info for non-OpenAI models
                                 "model": llm_model, 
                                 "vision": False,        # Adjust based on actual DeepSeek capabilities
                                 "function_calling": True, # Adjust based on actual DeepSeek capabilities
                                 "json_output": False,    # Adjust based on actual DeepSeek capabilities
                                 "family": "deepseek",    # Custom family name
                                 "max_tokens": 8192,      # Example: Replace with actual context length
                             }
                             # Can add temperature etc. here if needed/available
                             # temperature=config_section.get('temperature', 0.7)
                         )
                         model_clients[client_key] = model_client
                     except Exception as client_e:
                          logger.exception(f"Failed to create ChatCompletionClient for {client_key}")
                          logger.error(f"Skipping agent {agent_conf.name} due to client creation error.")
                          continue # Skip this agent
                 else:
                     logger.debug(f"Reusing existing ChatCompletionClient for {client_key}")
                     model_client = model_clients[client_key]


                 external_tools = [] # Placeholder for external tools

                 agent = SOPAgent(
                     name=agent_conf.name,
                     agent_config=agent_conf,
                     model_client=model_client, # Pass the actual client instance
                     plan_manager=plan_manager,
                     artifact_manager=artifact_manager,
                     tools=external_tools,
                 )
                 agents[agent_conf.name] = agent
            else:
                 logger.warning(f"Unsupported agent type '{agent_conf.agent}' for agent '{agent_conf.name}'. Skipping.")

        if not agents:
             logger.error("No agents were successfully initialized. Exiting.")
             return

    except Exception as e:
        logger.exception("Failed during agent initialization.")
        return

    # --- 5. Setup Workflow & Initial Task ---
    # How to start? Find an entry point agent (e.g., UserProxy or Strategist, or just the first one?)
    entry_agent_name = config.agents[0].name # Assume first agent is entry point for now
    if entry_agent_name not in agents:
         logger.error(f"Configured entry agent '{entry_agent_name}' was not initialized. Exiting.")
         return
         
    entry_agent = agents[entry_agent_name]
    logger.info(f"Using agent '{entry_agent_name}' as entry point.")

    # Represent the initial task as a message using 'source'
    initial_message = {"source": "user", "content": initial_task} # Changed 'role' to 'source'

    # --- 6. Run the Workflow ---
    logger.info("Starting workflow execution...")
    # console = Console() # Instantiate console (might use later)
    current_agent = entry_agent
    message_history = [initial_message] 

    max_turns = 10 
    turn_count = 0

    try:
        while turn_count < max_turns:
            turn_count += 1
            logger.info(f"--- Turn {turn_count} --- Agent: {current_agent.name} --- ")
            
            # Prepare messages 
            from autogen_agentchat.messages import TextMessage 
            # Import Response from the correct module
            from autogen_agentchat.base import Response 
            try:
                agent_input_messages = [TextMessage(**msg) for msg in message_history]
            except Exception as msg_e:
                 logger.exception(f"Error converting message history to TextMessage objects: {msg_e}")
                 logger.error(f"Current message history item causing error (potentially): {msg if message_history else 'Empty'}")
                 break # Stop workflow if messages can't be created

            # Let the current agent process the messages
            response_stream = current_agent.on_messages_stream(
                messages=agent_input_messages, 
                cancellation_token=None 
            )
            
            final_response_obj = None
            print(f"--- Agent: {current_agent.name} Output Stream --- ") # Simple separator
            async for response_item in response_stream:
                 # Instead of logger.debug, use simple print for stream items for now
                 # We can integrate Console properly later if needed
                 if not isinstance(response_item, Response): # Don't print the final Response object itself
                     print(f"  [{type(response_item).__name__}] {str(getattr(response_item, 'content', 'N/A'))[:150]}...")
                 
                 # Capture the final Response object
                 if isinstance(response_item, Response): 
                     final_response_obj = response_item
            print(f"--- End Output Stream --- ")

            # --- Process final response --- 
            if not final_response_obj or not final_response_obj.chat_message:
                 logger.warning(f"Agent '{current_agent.name}' did not produce a final response message this turn. Stopping workflow.")
                 break 
            
            # Add the agent's response to history, ensuring 'source' is present
            agent_response_message = final_response_obj.chat_message
            # Ensure content is string before adding to history dict
            response_content_str = str(getattr(agent_response_message, 'content', ''))
            response_dict = {
                "source": agent_response_message.source, # Use source directly
                "content": response_content_str 
            }
            message_history.append(response_dict)
            
            logger.info(f"Agent '{current_agent.name}' Final Response: {str(response_dict['content'])[:200]}...")

            # --- Workflow Logic: Decide next agent or terminate ---
            # Simple termination condition for now: response contains TERMINATE
            if "TERMINATE" in str(response_dict['content']).upper():
                logger.success("Workflow terminated based on agent response.")
                break
                
            # How to decide the next agent? 
            # Option 1: Fixed sequence (not flexible)
            # Option 2: Based on PlanManager state (Ideal for SOP)
            # Option 3: LLM decides (like GroupChat)
            
            # Let's try Option 2: Check PlanManager for the next step
            try:
                next_step = await plan_manager.get_next_executable_step(assignee=None) # Check if *any* step is ready
                if next_step and next_step.get("assignee"):
                    next_agent_name = next_step["assignee"]
                    if next_agent_name in agents:
                        current_agent = agents[next_agent_name]
                        logger.info(f"Next step found in plan. Assigning turn to: {current_agent.name}")
                    else:
                        logger.error(f"Plan assigns next step to unknown agent '{next_agent_name}'. Stopping.")
                        break
                else:
                    # No next step ready in plan, maybe default to previous agent or a coordinator?
                    logger.info("No next executable step found in plan. Stopping workflow.")
                    break # Stop if no clear next step from plan

            except Exception as plan_e:
                 logger.exception(f"Error checking plan manager for next step: {plan_e}. Stopping.")
                 break

        if turn_count >= max_turns:
            logger.warning(f"Workflow reached maximum turn limit ({max_turns}). Stopping.")

    except Exception as e:
        logger.exception("An error occurred during workflow execution.")
        
    finally:
        logger.info("Workflow execution finished.")
        # TODO: Save PlanManager state?

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run an AutoGen SOP Agent Team.")
    parser.add_argument("team_name", help="The name of the team configuration to run (e.g., 'safe-sop').")
    parser.add_argument("-t", "--task", default="Analyze the recent security incident report and generate a summary.", help="The initial task description.")
    
    args = parser.parse_args()
    
    asyncio.run(main(args.team_name, args.task)) 