from typing import Literal, Sequence, AsyncGenerator
from pydantic import BaseModel, Field

from autogen_core.models import ChatCompletionClient, SystemMessage, UserMessage, LLMMessage, CreateResult
from autogen_core import CancellationToken
from autogen_agentchat.tools import AgentTool
from autogen_agentchat.agents import BaseChatAgent
from autogen_agentchat.messages import BaseChatMessage, StructuredMessage, BaseAgentEvent
from autogen_agentchat.base import Response

JudgeType = Literal["SIMPLE", "PLAN"]

class JudgeDecision(BaseModel):
    """
    Represents the decision made by the judge regarding the task type.
    """
    type: JudgeType = Field(..., description="The classified type of the task, either PLAN or SIMPLE.")
    reason: str = Field(..., description="A brief explanation for the classification decision.")

JUDGE_PROMPT = """You are a highly efficient task analyzer.
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

JUDGE_DESCRIPTION = "Analyzes a task to determine if it's simple (SIMPLE) or complex (PLAN)."

class JudgeAgent(BaseChatAgent):
    def __init__(self, model_client: ChatCompletionClient):
        super().__init__(name="JudgeAgent", description=JUDGE_DESCRIPTION)
        self._model_client = model_client
        self._system_messages = [SystemMessage(content=JUDGE_PROMPT)]

    @property
    def produced_message_types(self) -> Sequence[type[BaseChatMessage]]:
        return [StructuredMessage[JudgeDecision]]

    async def on_reset(self, cancellation_token: CancellationToken) -> None:
        pass

    async def on_messages_stream(
        self, messages: Sequence[BaseChatMessage], cancellation_token: CancellationToken
    ) -> AsyncGenerator[BaseAgentEvent | BaseChatMessage | Response, None]:
        task_content = messages[-1].to_text()

        llm_messages_to_send: list[LLMMessage] = [
            self._system_messages[0],
            UserMessage(content=task_content, source=self.name)
        ]
        
        model_response: CreateResult = await self._model_client.create(
            messages=llm_messages_to_send,
            json_output=True,
            cancellation_token=cancellation_token
        )

        structured_msg = StructuredMessage(
            source=self.name,
            content=JudgeDecision.model_validate_json(model_response.content),
            models_usage=model_response.usage
        )
        yield Response(chat_message=structured_msg, inner_messages=[structured_msg])
            

    async def on_messages(self, messages: Sequence[BaseChatMessage], cancellation_token: CancellationToken) -> Response:
        async for message in self.on_messages_stream(messages, cancellation_token):
            if isinstance(message, Response):
                return message
        raise AssertionError("The stream should have returned the final result.")

def judge_agent_tool(model_client: ChatCompletionClient) -> AgentTool:
    return AgentTool(agent=JudgeAgent(model_client=model_client))