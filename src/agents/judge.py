from typing import Literal
from pydantic import BaseModel

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from autogen_agentchat.tools import AgentTool

JudgeType = Literal["PLAN", "SIMPLE"]

class JudgeDecision(BaseModel):
    type: JudgeType
    reason: str

JUDGE_PROMPT = """\
You are a highly efficient task analyzer.
Your sole purpose is to analyze the given task description and classify its type.
The possible types are:
- PLAN: Requires a multi-step plan or a structured approach due to its complexity.
- SIMPLE: Can be handled directly in one or two steps without a formal plan.

If the task description implies multiple distinct steps, dependencies, or a need for coordination, lean towards 'PLAN'.

Respond STRICTLY in JSON format with the following structure. Do NOT add any text before or after the JSON block:
{
    "type": "PLAN|SIMPLE",
    "reason": "Brief explanation of your decision."
}

Example 1:
User Task: "Organize a surprise birthday party for Sarah next month. This includes sending invitations, ordering a cake, and arranging entertainment."
Your JSON Response:
{
    "type": "PLAN",
    "reason": "The task involves multiple coordinated steps (invitations, cake, entertainment) and a timeline, clearly indicating the need for a plan."
}

Example 2:
User Task: "What is the capital of France?"
Your JSON Response:
{
    "type": "SIMPLE",
    "reason": "The task is a direct question requiring factual information retrieval, suitable for a simple, direct answer."
}
"""

def judge_agent(model_client: ChatCompletionClient) -> AssistantAgent: 
    return AssistantAgent(name="Judger", 
                          system_message=JUDGE_PROMPT, 
                          model_client=model_client)

def judge_agent_tool(model_client: ChatCompletionClient) -> AgentTool:
    return AgentTool(judge_agent(model_client=model_client))