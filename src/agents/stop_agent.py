from autogen_agentchat.agents import AssistantAgent
from autogen_agentchat.messages import TextMessage, BaseChatMessage
import logging

class StopAgent(AssistantAgent):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = getattr(self, 'name', 'StopAgent')

    async def on_messages_stream(self, messages: list[BaseChatMessage], cancellation_token=None, **kwargs):
        for msg in messages:
            if msg.content and (msg.content.strip() == "ALL_TASKS_DONE" or msg.content.strip() == "TERMINATE"):
                logging.info(f"{self.name}: 收到终止信号，内容: {msg.content}")
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