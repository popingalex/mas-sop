from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage
import logging

class SOPTerminator(AssistantAgent):
    DEFAULT_SYSTEM_PROMPT = """
你是StopAgent。当SOPManager通知所有任务完成时，你需要确认流程终止。
请严格按照如下格式回复：
name: StopAgent
source: SOPManager
reason: ALL_TASKS_DONE received.
output: TERMINATE
"""
    def __init__(self, *args, system_message=None, **kwargs):
        if system_message is None:
            system_message = self.DEFAULT_SYSTEM_PROMPT
        super().__init__(*args, system_message=system_message, **kwargs)

    async def on_messages_stream(self, messages: list[BaseChatMessage], cancellation_token=None, **kwargs):
        for msg in messages:
            text_content = msg.to_text()
            if text_content and (text_content.strip() == "ALL_TASKS_DONE" or text_content.strip() == "TERMINATE"):
                logging.info(f"{self.name}: 收到终止信号，内容: {text_content}")
                yield TextMessage(
                    content=f"{self.name}: 已收到终止信号，流程结束。",
                    source=self.name,
                    role="assistant"
                )
                return
        logging.warning(f"{self.name}: 未识别的消息格式，messages={messages}")
        yield TextMessage(
            content=f"{self.name}: 未识别的消息格式。",
            source=self.name,
            role="assistant"
        ) 