from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from src.config.parser import AgentConfig, GlobalSettings # Reusing from parser

# --- Workflow Step and Task Models (derived from config.yaml) ---

class WorkflowTask(BaseModel):
    task_id: str
    name: str
    assignee: Optional[str] = None # Assignee can be at step level or task level
    is_atomic: Optional[bool] = True # Defaulting based on observation, can be adjusted
    description: str
    # Allow any other fields as per config.yaml flexibility
    class Config:
        extra = 'allow'

class WorkflowStep(BaseModel):
    id: str
    title: str
    assignee: Optional[str] = None # Assignee can be at step level
    description: str
    tasks: List[WorkflowTask] = []
    # Allow any other fields
    class Config:
        extra = 'allow'

class WorkflowDefinition(BaseModel):
    name: str
    version: str
    description: Optional[str] = None
    steps: List[WorkflowStep] = []
    # Allow any other fields
    class Config:
        extra = 'allow'

# --- Top-level WorkflowTemplate Model ---
# This model should match the overall structure of teams/safe-sop/config.yaml
class WorkflowTemplate(BaseModel):
    version: str # Top-level version, e.g., "1.0" in config
    team_name: str # e.g., "safe-sop"
    workflow: WorkflowDefinition # The nested workflow structure
    global_settings: Optional[GlobalSettings] = None # Reusing GlobalSettings from parser.py
    agents: List[AgentConfig] # Reusing AgentConfig from parser.py
    
    # Allow any other top-level fields if present in config.yaml
    class Config:
        extra = 'allow'

# Example usage (for testing this file directly, not part of the actual model)
if __name__ == "__main__":
    sample_config_data = {
        "version": "1.0",
        "team_name": "sample-team",
        "workflow": {
            "name": "SampleWorkflow",
            "version": "1.1",
            "description": "A sample workflow definition.",
            "steps": [
                {
                    "id": "step_01",
                    "title": "Initial Phase",
                    "assignee": "Manager",
                    "description": "First phase of the workflow.",
                    "tasks": [
                        {
                            "task_id": "1.1",
                            "name": "Log Event",
                            "assignee": "Analyst",
                            "is_atomic": True,
                            "description": "Log the incoming event."
                        },
                        {
                            "task_id": "1.2",
                            "name": "Preliminary Check",
                            "description": "Perform a quick check."
                        }
                    ]
                }
            ]
        },
        "global_settings": {
            "default_llm_config": {
                "model": "gpt-4",
                "temperature": 0.5
            }
        },
        "agents": [
            {
                "name": "Manager",
                "agent": "SOPAgent",
                "prompt": "You are the manager.",
            },
            {
                "name": "Analyst",
                "agent": "SOPAgent",
                "prompt": "You are the analyst.",
            }
        ]
    }

    try:
        template = WorkflowTemplate(**sample_config_data)
        print("WorkflowTemplate Pydantic model created successfully!")
        print(f"Team Name: {template.team_name}")
        print(f"First agent name: {template.agents[0].name if template.agents else 'No agents'}")
        print(f"First workflow step title: {template.workflow.steps[0].title if template.workflow.steps else 'No steps'}")
        if template.workflow.steps and template.workflow.steps[0].tasks:
            print(f"First task in first step: {template.workflow.steps[0].tasks[0].name}")

    except Exception as e:
        print(f"Error creating WorkflowTemplate model: {e}") 