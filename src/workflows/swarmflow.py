from autogen_agentchat.teams import Swarm
from src.agents.sop_agent import SOPAgent, TurnManager
from autogen_agentchat.conditions import FunctionalTermination
from src.config.parser import TeamConfig
from src.tools.plan import PlanManager
from src.tools.artifact_manager import ArtifactManager
from src.agents.starter import Starter, StarterResult
from src.agents.reviewer import Reviewer
from loguru import logger
from autogen_agentchat.messages import TextMessage, StructuredMessage
from src.tools.storage import FileStorage
from typing import cast
from string import Template

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

def build_sop_swarm_group(team_config: TeamConfig,
                          model_client,
                          plan_id,
                          plan_manager: PlanManager,
                          artifact_manager=None):
    """
    根据团队配置、模型、计划管理器和计划ID组装SwarmGroup。
    只包含团队成员SOPAgent，终止条件为计划全部完成。
    """
    turn_manager = TurnManager()
    participants = []
    agent_names = [agent_conf.name for agent_conf in team_config.agents]
    for agent_conf in team_config.agents:
        # prompt变量替换
        prompt = agent_conf.prompt
        if prompt:
            prompt_tpl = Template(prompt)
            prompt = prompt_tpl.safe_substitute(
                agent={'name': agent_conf.name},
                role_config={'expertise_area': getattr(agent_conf, 'expertise_area', '')}
            )
        agent = SOPAgent(
            name=agent_conf.name,
            model_client=model_client,
            plan_manager=plan_manager,
            agent_config=agent_conf,
            turn_manager=turn_manager,
            artifact_manager=artifact_manager,
            prompt=prompt,
            handoffs=agent_names
        )
        participants.append(agent)

    async def plan_is_done(messages):
        plan = plan_manager.get_plan(plan_id)
        return plan and plan['status'] == 'completed'

    termination_condition = FunctionalTermination(plan_is_done)

    return Swarm(participants=participants, termination_condition=termination_condition)

async def run_swarm(team_config, model_client, log_dir, initial_message_content):
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
    starter_result = cast(StarterResult, cast(StructuredMessage, task_result.messages[-1]).content)


    plan_id = starter_result.plan_id
    swarm_group = build_sop_swarm_group(team_config, model_client, plan_id, plan_manager, artifact_manager)
    async for event in swarm_group.run_stream(task=starter_result.model_dump_json()):
        yield event
    reviewer = Reviewer(model_client=model_client, plan_manager=plan_manager, artifact_manager=artifact_manager)
    review_result = await reviewer.run(plan_id=plan_id)
    yield {"type": "review", "result": review_result}