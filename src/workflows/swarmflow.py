from autogen_agentchat.teams import Swarm
from src.agents.sop_agent import SOPAgent, TurnManager
from src.agents.sop_manager import SOPManager
from autogen_agentchat.conditions import FunctionalTermination
from src.types import TeamConfig
from src.tools.plan import PlanManager
from src.tools.artifact_manager import ArtifactManager
from src.agents.starter import Starter
from src.agents.reviewer import Reviewer
from loguru import logger
from autogen_agentchat.messages import TextMessage, StructuredMessage
from src.types.plan import PlanContext
from src.tools.storage import FileStorage
from typing import cast
from string import Template
import json

def make_swarmgroup_init_message(plan_id: str, step_id: str, task_id: str, artifact_id: str = None, event: str = None) -> TextMessage:
    """
    拼装给SwarmGroup的初始消息，包含计划ID、步骤ID、任务ID、事件资产ID（如有）、事件内容（如有）。
    """
    content = f"计划ID: {plan_id}\n步骤ID: {step_id}\n任务ID: {task_id}"
    if artifact_id:
        content += f"\n事件资产ID: {artifact_id}"
    if event:
        content += f"\n事件: {event}"
    return TextMessage(content=content, source="system")

def build_sop_swarm_group(client,
                          team_config: TeamConfig,
                          plan_manager: PlanManager,
                          artifact_manager: ArtifactManager):
    """
    组装SOPManager和所有SOPAgent为SwarmGroup成员。
    SOPManager为中心调度者，SOPAgent只负责执行。
    终止条件为计划全部完成。
    """
    turn_manager = TurnManager()
    sop_manager = SOPManager(
        plan_manager=plan_manager,
        team_config=team_config,
        artifact_manager=artifact_manager
    )
    participants = [sop_manager]
    # 组装SOPAgent
    for agent_conf in team_config.agents:
        agent = SOPAgent(
            model_client=client,
            plan_manager=plan_manager,
            agent_config=agent_conf,
            team_config=team_config,
            turn_manager=turn_manager,
            artifact_manager=artifact_manager,
            handoffs=["SOPManager"],
        )
        participants.append(agent)
    termination_condition = sop_manager.get_termination_condition()
    return Swarm(participants=participants, termination_condition=termination_condition)

async def run_swarm(model_client, team_config, log_dir, initial_message_content):
    # 全局唯一的TurnManager和Storage
    turn_manager = TurnManager()
    storage = FileStorage(base_dir=log_dir, format="yaml", mode="multi")
    plan_manager = PlanManager(turn_manager=turn_manager, storage=storage)
    artifact_manager = ArtifactManager(turn_manager=turn_manager, storage=storage)
    starter = Starter(
        name="Starter",
        model_client=model_client,
        team_config=team_config,
        plan_manager=plan_manager,
        artifact_manager=artifact_manager
    )
    task_result = await starter.run(task=initial_message_content)
    logger.info(f"[{starter.name}] 启动流程: {task_result}")
    task_msg: StructuredMessage[PlanContext] = task_result.messages[-1]
    swarm_group = build_sop_swarm_group(model_client, team_config, plan_manager, artifact_manager)
    async for event in swarm_group.run_stream(task=task_msg):
        yield event
    reviewer = Reviewer(model_client=model_client, plan_manager=plan_manager, artifact_manager=artifact_manager)
    review_result = await reviewer.run(task=task_msg)
    # logger.info(f"[{reviewer.name}] 输出总结: {review_result}")
    # 提取结构化总结
    summary = None
    if hasattr(review_result, "messages") and review_result.messages:
        last_msg = review_result.messages[-1]
        if hasattr(last_msg, "content"):
            summary = last_msg.content
            # pydantic对象转dict
            if hasattr(summary, "model_dump"):
                summary = summary.model_dump()
            # 字符串且为json，转为dict
            if isinstance(summary, str):
                try:
                    summary = json.loads(summary)
                except Exception:
                    pass
    # 日志只打印结构化总结
    logger.info(f"[{reviewer.name}] 结构化总结:\n{json.dumps(summary, ensure_ascii=False, indent=2)}")
    yield {"type": "review", "summary": summary}