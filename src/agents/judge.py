from typing import Literal, Optional, Any, Union
from pydantic import BaseModel, Field
import json
from loguru import logger

from autogen_agentchat.agents import AssistantAgent
from autogen_core.models import ChatCompletionClient
from autogen_agentchat.tools import AgentTool
from autogen_core import CancellationToken
from autogen_agentchat.messages import TextMessage, ChatMessage

class JudgeDecision(BaseModel):
    """任务判断结果模型"""
    type: Literal["PLAN", "SIMPLE", "SEARCH", "UNCLEAR"] = Field(default="PLAN", description="任务类型")
    reason: str = Field(..., description="判断原因")

    class Config:
        use_enum_values = True

JUDGE_PROMPT = """\
You are a highly efficient task analyzer.
Your sole purpose is to analyze the given task description and classify its type.
The possible types are:
- PLAN: Requires a multi-step plan or a structured approach due to its complexity.
- SIMPLE: Can be handled directly in one or two steps without a formal plan.
- SEARCH: Requires gathering more information or searching for details.
- UNCLEAR: The task description is ambiguous or lacks critical details.

If the task description implies multiple distinct steps, dependencies, or a need for coordination, lean towards 'PLAN'.

Respond STRICTLY in JSON format with the following structure. Do NOT add any text before or after the JSON block:
{
    "type": "PLAN|SIMPLE|SEARCH|UNCLEAR",
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
}"""

def judge_agent(model_client: ChatCompletionClient) -> AssistantAgent: 
    return AssistantAgent(name="Judger", 
                          system_message=JUDGE_PROMPT, 
                          model_client=model_client)

class JudgeAgentTool:
    def __init__(self, agent: AssistantAgent):
        self.agent = agent
        self.name = "Judger"
    
    async def run(self, input: Any, **kwargs) -> Any:
        """运行工具。
        
        Args:
            input: 输入参数
            **kwargs: 其他参数
            
        Returns:
            Any: 工具执行结果
        """
        try:
            # 创建消息列表
            messages = [
                ChatMessage(role="system", content=JUDGE_PROMPT),
                ChatMessage(role="user", content=str(input))  # 确保输入是字符串
            ]
            
            # 调用 model_client 的 create 方法
            response = await self.agent.model_client.create(messages=messages)
            
            # 提取响应内容
            if isinstance(response, str):
                content = response
            elif hasattr(response, 'choices') and response.choices and hasattr(response.choices[0], 'message'):
                content = response.choices[0].message.content
            else:
                content = str(response)
                
            # 尝试解析 JSON
            try:
                json_obj = json.loads(content)
                # 验证必要字段
                if not isinstance(json_obj, dict):
                    raise ValueError("Response is not a JSON object")
                if "type" not in json_obj or "reason" not in json_obj:
                    raise ValueError("Missing required fields 'type' or 'reason'")
                if json_obj["type"] not in ["PLAN", "SIMPLE", "SEARCH", "UNCLEAR"]:
                    raise ValueError(f"Invalid type value: {json_obj['type']}")
                
                # 创建并验证 JudgeDecision 对象
                decision = JudgeDecision(**json_obj)
                return TextMessage(content=json.dumps(decision.dict()), source=self.name, role="assistant")
                
            except json.JSONDecodeError as e:
                logger.error(f"Failed to parse JSON response: {e}")
                default_response = JudgeDecision(type="PLAN", reason="Failed to parse LLM response JSON, defaulting to PLAN type.")
                return TextMessage(content=json.dumps(default_response.dict()), source=self.name, role="assistant")
                
            except Exception as e:
                logger.error(f"Error processing judge response: {e}")
                default_response = JudgeDecision(type="PLAN", reason=f"Error processing response: {str(e)}. Defaulting to PLAN type.")
                return TextMessage(content=json.dumps(default_response.dict()), source=self.name, role="assistant")
                
        except Exception as e:
            logger.error(f"Error in JudgeAgentTool.run: {e}")
            default_response = JudgeDecision(type="PLAN", reason=f"Tool execution error: {str(e)}. Defaulting to PLAN type.")
            return TextMessage(content=json.dumps(default_response.dict()), source=self.name, role="assistant")

def judge_agent_tool(model_client: ChatCompletionClient) -> JudgeAgentTool:
    """创建一个 JudgeAgentTool 实例。
    
    Args:
        model_client: LLM 客户端
        
    Returns:
        JudgeAgentTool: 工具实例
    """
    judge_agent = AssistantAgent(
        name="JudgeAgent",
        model_client=model_client,
        system_message=JUDGE_PROMPT
    )
    return JudgeAgentTool(judge_agent)