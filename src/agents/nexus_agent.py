from typing import Optional, List, Dict, Any, AsyncGenerator, Sequence, cast
from uuid import UUID
from loguru import logger
import traceback
import json

from autogen_agentchat.messages import TextMessage, BaseChatMessage, BaseTextChatMessage
from autogen_agentchat.base import Response

from autogen_core.models import ChatCompletionClient
from autogen_core import MessageContext

from .base_sop_agent import BaseSOPAgent
# from .judge_agent import JudgeAgent # JudgeAgent not directly used in core SOP flow for now
from ..types import JudgeDecision # Keep if quick_think or similar is used elsewhere
from ..config.parser import AgentConfig, TeamConfig
from ..tools.plan.manager import PlanManager, Step, Plan
from ..tools.errors import ErrorMessages
from ..types import ResponseType, success, error
from ..types.plan import Plan, Step, Task, PlanTemplate
from .judge import JudgeAgent, JudgeDecision # Import JudgeAgent and JudgeDecision

# Placeholder for the actual tool schema if we were using AutoGen's tool registration
# For now, PlanManager methods will be called directly by NexusAgent's Python code,
# but this call is conceptually decided by the LLM.

ASSISTANT_MESSAGE_TERMINATE = "TERMINATE"
ASSISTANT_MESSAGE_ALL_TASKS_DONE = "ALL_TASKS_DONE"

# 定义常量用于LLM意图识别或生成的消息内容
TOOL_CREATE_PLAN = "create_plan"
TOOL_GET_PLAN = "get_plan"
TOOL_GET_NEXT_STEP = "get_next_pending_step"
TOOL_UPDATE_STEP = "update_step"
MSG_ALL_TASKS_DONE = "ALL_TASKS_DONE"
MSG_TERMINATE = "TERMINATE"

# System message for NexusAgent
NEXUS_AGENT_SYSTEM_MESSAGE = """你是 NexusCoordinator，一个经验丰富的SOP流程协调专家。

**核心职责**:
1.  **新任务处理**: 当收到全新的用户任务时：
    a.  **必须首先调用** `judge_task_type_tool` 工具来分析任务类型。
    b.  **分析工具结果**:
        *   如果类型是 `PLAN`，你的下一个任务是参照系统提供的可用SOP Workflow模板列表，选择最合适的一个，并为该计划设定一个清晰的标题。然后，**直接在你的响应中** 清晰地说明你选择的模板名称 (`chosen_template_name`) 和计划标题 (`plan_title`)，例如："已选择模板 '模板A'，计划标题为 '处理X的计划'。请创建主计划。" (系统将根据此信息创建主计划)。计划创建成功后 (系统会通知你计划ID)，你的下一个行动是调用 `get_next_pending_step_tool` 工具获取第一个待办步骤。
        *   如果类型是 `SIMPLE`，则尝试直接生成对用户请求的回应。
        *   如果类型是 `UNCLEAR` 或 `SEARCH`，你将告知用户并通常会终止当前交互 (输出 `TERMINATE`)。

2.  **进行中计划的驱动**:
    *   当一个主计划正在执行中（例如，你收到了一个LeafAgent完成步骤的消息，或者计划刚创建完毕），你需要驱动其按步骤进行。
    *   通常，你的行动是调用 `get_next_pending_step_tool` 来获取下一个待处理的步骤。
    *   在处理一个已完成的步骤后，你应该先调用 `update_step_status_tool` 将其标记为 `completed`，然后再调用 `get_next_pending_step_tool` 获取下一步。
    *   你**不负责**为LeafAgent创建或管理其内部的子计划。

3.  **工具使用 (可用工具列表)**:
    *   `judge_task_type_tool(task_description: str)`: 分析给定任务描述的类型 (PLAN, SIMPLE, SEARCH, UNCLEAR)。返回包含类型、置信度和原因的JSON字符串。
    *   `get_next_pending_step_tool(plan_id: str)`: 获取指定 plan_id 中主计划的下一个待处理步骤。返回步骤详情JSON或无待处理步骤的消息。
    *   `update_step_status_tool(plan_id: str, step_identifier: str, new_status: str)`: 更新指定 plan_id 中某个步骤的状态 (例如, 'completed', 'in_progress')。`step_identifier` 可以是步骤ID。
    *   `get_plan_details_tool(plan_id: str)`: 获取指定 plan_id 的主计划完整详情JSON。
    *   **注意**: 你**不直接调用** `create_plan` 工具来创建基于SOP的主计划。你只需要在判断任务为PLAN后，在你的文本响应中提供 `chosen_template_name` 和 `plan_title`。

4.  **任务分派与流程结束**:
    *   当你通过 `get_next_pending_step_tool` 获取到待办步骤后，提取步骤信息 (特别是 `assignee` 和任务描述)，然后生成并发送清晰的任务指令给对应的 `assignee` (LeafAgent)。标准格式为 "HANDOFF_TO_[AssigneeName]" 并在消息体中包含任务细节。
    *   当 `get_next_pending_step_tool` 返回主计划"没有待处理步骤"时，生成并发送内容为 `ALL_TASKS_DONE` 的消息给 `StopAgent`。

**重要沟通指令**:
*   **最高优先级 (SYSTEM_DIRECTIVE)**: 如果你的消息历史中，最新一条来自用户且内容以 "SYSTEM_DIRECTIVE:" 开头，你必须严格按照该指令的文本内容作为你的最终输出，忽略所有其他思考和工作流程。
*   当你需要调用工具时，必须使用结构化的工具调用格式（如果模型支持），或者清晰说明 "调用工具 `tool_name`，参数为：..."。

(LeafAgent能力信息相关的提示已移除，因为Nexus不直接使用它们创建子计划)
"""

class NexusAgent(BaseSOPAgent):
    """NexusAgent: 中心协调者, LLM驱动, 通过PlanManager工具管理SOP计划并分发任务。"""

    def __init__(
        self,
        name: str,
        agent_config: AgentConfig,
        model_client: ChatCompletionClient,
        plan_manager: PlanManager,
        team_config: Optional[TeamConfig] = None,
        artifact_manager: Optional[Any] = None,
        system_message: Optional[str] = None,
        **kwargs,
    ):
        effective_system_message = system_message or NEXUS_AGENT_SYSTEM_MESSAGE

        super().__init__(
            name=name,
            agent_config=agent_config,
            model_client=model_client,
            plan_manager=plan_manager,
            artifact_manager=artifact_manager,
            system_message=effective_system_message,
            **kwargs
        )
        self.team_config = team_config
        self.current_plan_id: Optional[UUID] = None
        self.last_dispatched_step: Optional[Step] = None

        logger.info(f"[{self.name}] Initialized. PlanManager tools are conceptually available.")

    async def on_messages_stream(
        self,
        messages: Sequence[BaseChatMessage],
        ctx: MessageContext, 
    ) -> AsyncGenerator[TextMessage | Response, None]:
        
        logger.info(f"[{self.name}]: === 周期开始: 收到 {len(messages) if messages else '0'} 条消息。当前计划 ID: {self.current_plan_id} ===")
        
        context_for_llm: List[BaseChatMessage] = list(messages)
        is_new_task_trigger = False
        last_message_content_for_judge = ""

        if messages:
            last_msg = messages[-1]
            if last_msg.source != self.name and not self.current_plan_id:
                 is_new_task_trigger = True
                 if isinstance(last_msg, BaseTextChatMessage):
                    last_message_content_for_judge = last_msg.content
                 else:
                    # Handle cases where the message might not be simple text, e.g., tool calls or multi-modal
                    # For now, if it's not text, JudgeAgent might not be able to process it well.
                    logger.warning(f"[{self.name}]: Last message is not text, JudgeAgent might not process it effectively.")
                    # last_message_content_for_judge will remain empty, leading to UNCLEAR from JudgeAgent or an error.


        if is_new_task_trigger:
            logger.info(f"[{self.name}]: New task received ('{last_message_content_for_judge[:50]}...'). Invoking JudgeAgent for analysis.")
            
            if not last_message_content_for_judge:
                logger.warning(f"[{self.name}]: New task trigger, but no text content found in the last message. JudgeAgent cannot proceed effectively.")
                # Yield an error or UNCLEAR message directly
                yield TextMessage(content=f"[{self.name}] Error: New task received without processable content.", source=self.name, role="assistant")
                yield Response(chat_message=TextMessage(content="[错误]", source=self.name))
                return

            sop_definitions_for_judge: Dict[str, Any] = {}
            if self.team_config and self.team_config.workflows:
                for wf_template in self.team_config.workflows:
                    sop_definitions_for_judge[wf_template.name] = {
                        "description": wf_template.description or "No description",
                        "steps_count": len(wf_template.steps)
                    }
            
            if not sop_definitions_for_judge:
                logger.warning(f"[{self.name}]: No SOP templates (workflows) defined in team_config. JudgeAgent will not have SOPs to choose from for PLAN type.")

            judge_agent_instance = JudgeAgent(
                name="TaskJudge", # Temporary name for this instance
                model_client=self.model_client, # Reuse Nexus's model client
                sop_definitions=sop_definitions_for_judge,
                caller_name=self.name
            )

            judge_decision_json_str: Optional[str] = None
            try:
                async for decision_output in judge_agent_instance.run(task=last_message_content_for_judge):
                    if isinstance(decision_output, dict) and "chat_message" in decision_output:
                        chat_msg = decision_output["chat_message"]
                        if isinstance(chat_msg, TextMessage):
                            judge_decision_json_str = chat_msg.content
                            logger.info(f"[{self.name}]: JudgeAgent decision: {judge_decision_json_str}")
                            break # Expecting one decision
                
                if not judge_decision_json_str:
                    raise ValueError("JudgeAgent did not return a decision.")

                judge_decision = JudgeDecision.parse_raw(judge_decision_json_str)

            except Exception as e:
                logger.error(f"[{self.name}]: Error invoking JudgeAgent or parsing its decision: {e}", exc_info=True)
                yield TextMessage(content=f"[{self.name}] Error: Failed to get a decision from JudgeAgent - {e}", source=self.name, role="assistant")
                yield Response(chat_message=TextMessage(content="[错误]", source=self.name))
                return

            if judge_decision.type == "PLAN":
                logger.info(f"[{self.name}]: JudgeAgent recommended PLAN. Reason: {judge_decision.reason}. Nexus will now select an SOP.")
                
                if self.team_config and self.team_config.workflows and len(self.team_config.workflows) > 0:
                    # --- Stage 1: SOP Template Selection and Plan Title by Nexus LLM ---
                    template_selection_context: List[BaseChatMessage] = list(messages) # Start with current messages for this specific LLM call
                    
                    template_info_parts = ["SYSTEM_CONTEXT: JudgeAgent has determined the current user request is a complex task requiring a plan (SOP).",
                                           "Your immediate task is to select the most appropriate SOP Workflow template from the list below to address the user\'s request.",
                                           f"User\'s original request: '{last_message_content_for_judge}'\n"]
                    for i, wf_template in enumerate(self.team_config.workflows):
                        steps_summary = ", ".join([step.description[:30] + "..." if len(step.description) > 30 else step.description for step in wf_template.steps[:2]])
                        template_info_parts.append(
                            f"Template {i+1}:\n"
                            f"  Name (template_name): \"{wf_template.name}\"\n"
                            f"  Description: {wf_template.description or '无描述'}\n"
                            f"  Key Steps Summary: {steps_summary or 'No specific step descriptions'}"
                        )
                    template_info_parts.append("\nAfter selecting, you MUST respond ONLY with a JSON object containing two keys: 'chosen_template_name' (the exact name of the template you selected) and 'plan_title' (a concise, descriptive title for the plan based on the user request and chosen template). Example JSON: { \"chosen_template_name\": \"SOP Template A\", \"plan_title\": \"Plan for user request X using SOP A\" }")
                    template_selection_prompt_content = "\\n\\n".join(template_info_parts)
                    
                    template_selection_context.append(TextMessage(role="user", content=template_selection_prompt_content, source="system_nexus_sop_selection"))
                    logger.info(f"[{self.name}]: Initiating LLM call for SOP template selection and plan title.")

                    try:
                        selection_llm_response_obj = await self.model_client.create(messages=[m.to_model_message() for m in template_selection_context])
                        selection_llm_response_content = ""
                        if hasattr(selection_llm_response_obj, 'content') and isinstance(selection_llm_response_obj.content, str):
                            selection_llm_response_content = selection_llm_response_obj.content.strip()
                        elif isinstance(selection_llm_response_obj, str):
                            selection_llm_response_content = selection_llm_response_obj.strip()
                        else:
                            raise ValueError(f"LLM response for SOP selection was not a string or had no content: {selection_llm_response_obj}")
                        logger.info(f"[{self.name}]: LLM response for SOP selection: '{selection_llm_response_content}'")
                        
                        # Parse the JSON response for chosen_template_name and plan_title
                        parsed_selection_json = json.loads(selection_llm_response_content)
                        chosen_template_name_from_llm = parsed_selection_json.get("chosen_template_name")
                        parsed_plan_title = parsed_selection_json.get("plan_title")

                        if not chosen_template_name_from_llm or not parsed_plan_title:
                            raise ValueError("LLM response for SOP selection did not contain 'chosen_template_name' or 'plan_title'.")

                    except Exception as selection_err:
                        logger.error(f"[{self.name}]: Error during LLM SOP selection or parsing: {selection_err}", exc_info=True)
                        yield TextMessage(content=f"[{self.name}] Error: Failed to select SOP or parse selection - {selection_err}", source=self.name, role="assistant")
                        yield Response(chat_message=TextMessage(content="[错误]", source=self.name))
                        return

                    # Find the selected template
                    selected_template: Optional[PlanTemplate] = None
                    for wf_template in self.team_config.workflows:
                        if wf_template.name == chosen_template_name_from_llm:
                            selected_template = wf_template
                            break
                    
                    if not selected_template:
                        logger.error(f"[{self.name}]: LLM chose template '{chosen_template_name_from_llm}', but it was not found in team_config.workflows.")
                        yield TextMessage(content=f"[{self.name}] Error: LLM selected SOP '{chosen_template_name_from_llm}' not found.", source=self.name, role="assistant")
                        yield Response(chat_message=TextMessage(content="[错误]", source=self.name))
                        return

                    # Create the plan using PlanManager
                    steps_data_for_plan_manager = selected_template.steps
                    logger.info(f"[{self.name}]: Creating plan '{parsed_plan_title}' with {len(steps_data_for_plan_manager)} steps from template '{selected_template.name}'.")
                    create_plan_response = self.plan_manager.create_plan(
                        title=parsed_plan_title,
                        reporter=self.name,
                        steps_data=steps_data_for_plan_manager
                    )

                    if not (create_plan_response["success"] and isinstance(create_plan_response.get("data"), dict) and create_plan_response["data"].get("id")):
                        logger.error(f"[{self.name}]: Failed to create plan using PlanManager. Response: {create_plan_response.get('message')}")
                        yield TextMessage(content=f"[{self.name}] Error: Plan creation failed - {create_plan_response.get('message')}", source=self.name, role="assistant")
                        yield Response(chat_message=TextMessage(content="[错误]", source=self.name))
                        return
                    
                    new_plan_id_str = create_plan_response["data"]["id"]
                    self.current_plan_id = UUID(str(new_plan_id_str))
                    logger.success(f"[{self.name}]: Successfully created Plan ID: {self.current_plan_id} ('{parsed_plan_title}').")

                    # --- Stage 2: Get first step and prepare for handoff (triggers next main LLM call) ---
                    # Add context about the newly created plan to the main context_for_llm
                    # This will be picked up by the subsequent main LLM call in this on_messages_stream cycle.
                    context_for_llm.append(TextMessage(
                        role="user", 
                        content=f"SYSTEM_CONTEXT: New plan '{parsed_plan_title}' (ID: {self.current_plan_id}) has been created. Your next action is to get the first pending step of this plan and prepare to hand it off to the assigned agent. You should use the 'get_next_pending_step' tool.", 
                        source="system_nexus_plan_created"
                    ))
                    logger.info(f"[{self.name}]: Added context for next LLM call to get first step of plan ID {self.current_plan_id}.")
                    # The rest of the on_messages_stream will now execute, making an LLM call with the updated context_for_llm.
                    # That LLM call is expected to trigger the 'get_next_pending_step' tool call via its regular tool-using prompt.

                else: # No SOP templates available
                    logger.warning(f"[{self.name}]: JudgeAgent recommended PLAN, but no SOP templates are available in team_config. Cannot proceed.")
                    yield TextMessage(content=f"[{self.name}] Error: Task requires a plan, but no SOP templates are configured.", source=self.name, role="assistant")
                    yield Response(chat_message=TextMessage(content="[错误]", source=self.name))
                    return
                
            elif judge_decision.type == "SIMPLE":
                logger.info(f"[{self.name}]: JudgeAgent classified task as SIMPLE. Reason: {judge_decision.reason}. Nexus will attempt to respond directly.")
                context_for_llm.append(TextMessage(role="user", content=f"SYSTEM_CONTEXT: JudgeAgent classified this as a SIMPLE task. Reason: {judge_decision.reason}. Please provide a direct response to the original query if possible, or indicate completion if no further action is needed.", source="system_nexus_internal"))

            elif judge_decision.type in ["SEARCH", "UNCLEAR"]:
                logger.info(f"[{self.name}]: JudgeAgent classified task as {judge_decision.type}. Reason: {judge_decision.reason}. Terminating or informing user.")
                final_response_content = f"The task was classified as {judge_decision.type} by the JudgeAgent. Reason: {judge_decision.reason}. I cannot proceed with a plan. Please clarify your request or try a different task."
                if judge_decision.type == "UNCLEAR":
                    final_response_content = f"The task is UNCLEAR. JudgeAgent's reason: {judge_decision.reason}. Please provide more details or clarify your request."

                term_msg = TextMessage(content=final_response_content, source=self.name, role="assistant", recipient="StopAgent") # Send to StopAgent to terminate
                yield term_msg
                yield Response(chat_message=term_msg)
                self.current_plan_id = None # Ensure no plan is active
                return # End the stream
            else: # PLAN type but no chosen_sop_name, or other unexpected type - This condition needs update
                logger.warning(f"[{self.name}]: JudgeAgent returned type '{judge_decision.type}' but it was not PLAN, or another unhandled scenario. Reason: {judge_decision.reason}. Terminating.")
                error_msg_content = f"[{self.name}] Error: JudgeAgent decision was '{judge_decision.type}'. Reason: {judge_decision.reason}. Cannot proceed with planning at this stage."
                # if judge_decision.type == "PLAN" and not judge_decision.chosen_sop_name: # This specific check is no longer relevant
                #      error_msg_content = f"[{self.name}] Error: JudgeAgent recommended PLAN but did not specify an SOP. Reason: {judge_decision.reason}."
                
                term_msg = TextMessage(content=error_msg_content, source=self.name, role="assistant", recipient="StopAgent")
                yield term_msg
                yield Response(chat_message=term_msg)
                self.current_plan_id = None
                return

            # If a plan was created, or if it's a SIMPLE task, the context_for_llm has been updated.
            # The main LLM call will now proceed. If it was a PLAN, the context has a system message about the new plan.
            # If it was SIMPLE, it has a system message to try and respond directly.
            # The previous logic of LLM selecting templates is now bypassed if JudgeAgent was invoked.

        # The rest of the original on_messages_stream logic follows,
        # which includes the main LLM call if not returned early by JudgeAgent's decision.
        # logger.debug(f"[{self.name}]: 准备调用 LLM，历史消息数: {len(context_for_llm)}")
        # Log context_for_llm if it's not too verbose, or key parts of it.
        log_msg_count = len(context_for_llm)
        last_few_msgs_summary = []
        if context_for_llm:
            for i in range(max(0, log_msg_count - 3), log_msg_count): # Log last 3 messages
                msg = context_for_llm[i]
                source = msg.source if hasattr(msg, "source") else msg.role
                content_summary = msg.content[:100] + "..." if len(msg.content) > 100 else msg.content
                last_few_msgs_summary.append(f"  - ({source}): {content_summary}")
        logger.debug(f"[{self.name}]: 准备调用 LLM (共 {log_msg_count} 条消息)。最后几条消息内容:\n" + "\n".join(last_few_msgs_summary))

        # --- Main LLM call for ongoing plan driving or post-JudgeAgent SIMPLE task handling ---
        current_context_for_llm: List[BaseChatMessage] = list(context_for_llm)

        try:
            llm_response_obj = await self.model_client.create(messages=[m.to_model_message() for m in current_context_for_llm])
            
            llm_response_content = "" 
            if hasattr(llm_response_obj, 'content') and isinstance(llm_response_obj.content, str):
                llm_response_content = llm_response_obj.content.strip()
            elif isinstance(llm_response_obj, str):
                llm_response_content = llm_response_obj.strip()
            else:
                 logger.error(f"[{self.name}]: LLM 响应格式未知或无内容: {llm_response_obj}")
                 llm_response_content = "[LLM响应无效]"

            logger.info(f"[{self.name}]: LLM 响应原文: '{llm_response_content[:300]}...'")

        except Exception as e:
            logger.error(f"[{self.name}]: LLM 调用失败: {e}", exc_info=True)
            yield TextMessage(content=f"[{self.name}] 错误: LLM 调用失败 - {e}", source=self.name, role="assistant")
            yield Response(chat_message=TextMessage(content="[错误]", source=self.name))
            return
        
        final_message_to_yield: Optional[TextMessage] = None
        tool_call_requested = None
        
        response_lower = llm_response_content.lower()
        tool_params = {} # This will be populated by regex or other parsing if a tool call is detected.
                         # For example, if LLM says "Call tool create_plan with title='Subplan X' and steps_data=[...]"
                         # This dict should be populated with {"title": "Subplan X", "steps_data": [...]} 
                         # based on parsing llm_response_content, BEFORE the `if tool_call_requested:` block.
                         # The current regex/parsing logic for create_plan is more tied to the Stage 1 JSON output.
                         # We need a more general way to parse tool call arguments from natural language if LLM doesn't use structured tool calls.

        # --- Tool Call Intent Parsing (Main Loop) ---
        # NexusAgent LLM's primary tools in this loop are for driving the *main* plan.
        # It should NOT be requesting create_plan for the main SOP plan here,
        # as that was handled in the initial task processing (Stage 1).
        
        if "调用工具 get_next_pending_step" in response_lower or "call tool get_next_pending_step" in response_lower:
            tool_call_requested = TOOL_GET_NEXT_STEP
            # Parsing plan_id might be needed if LLM specifies it, otherwise use self.current_plan_id
        elif "调用工具 update_step" in response_lower or "call tool update_step" in response_lower:
            tool_call_requested = TOOL_UPDATE_STEP
            # Placeholder for parsing step_id/index and update_data
            logger.warning(f"[{self.name}]: LLM请求调用 update_step，但参数解析逻辑未实现！")
            # tool_params = {"step_id": "...", "update_data": {"status": "completed"}} # Example
        elif "调用工具 get_plan" in response_lower or "call tool get_plan" in response_lower:
            tool_call_requested = TOOL_GET_PLAN
            # Parsing plan_id might be needed if LLM specifies it, otherwise use self.current_plan_id
        elif "调用工具 create_plan" in response_lower or "call tool create_plan" in response_lower:
            # This case is unexpected for main SOP plans according to our flow.
            # It might indicate the LLM is trying to create a plan outside the defined process,
            # or maybe it's a misunderstanding of its role.
            # We can log a warning and potentially ignore or handle as an error.
            logger.warning(f"[{self.name}]: Main LLM unexpectedly requested 'create_plan'. This is not part of the standard main plan creation flow. Ignoring request or implementing specific handling if Nexus can create non-SOP plans.")
            # tool_call_requested = TOOL_CREATE_PLAN # Decide if we allow this
            # If allowed, robust parsing of title and steps_data from LLM response is needed here.
            tool_call_requested = None # Defaulting to ignoring this unexpected request

        # --- Tool Execution (if a tool_call_requested was identified) ---
        if tool_call_requested:
            logger.info(f"[{self.name}]: 解析到 LLM 意图调用工具: {tool_call_requested} with params: {tool_params}")
            tool_execution_result: Optional[Dict[str, Any]] = None
            tool_success = False
            error_message = ""

            try:
                # Removed the TOOL_CREATE_PLAN case from here as it's handled earlier or ignored.
                if tool_call_requested == TOOL_GET_NEXT_STEP:
                    if not self.current_plan_id: raise ValueError("current_plan_id 未设置")
                    # TODO: Add parsing for plan_id from tool_params if LLM might specify it.
                    exec_resp = self.plan_manager.get_next_pending_step(str(self.current_plan_id))
                    tool_execution_result = exec_resp
                    if exec_resp["success"]:
                        tool_success = True
                        # Store the step info if successfully retrieved?
                        if exec_resp.get("data"):
                            try:
                                # Assuming data is the Step object or dict
                                self.last_dispatched_step = Step(**exec_resp["data"]) 
                            except Exception as parse_err:
                                logger.warning(f"[{self.name}]: Failed to parse step data from get_next_pending_step: {parse_err}")
                                self.last_dispatched_step = None 
                    else: error_message = exec_resp.get("message", "get_next_pending_step 执行失败")
                
                elif tool_call_requested == TOOL_UPDATE_STEP:
                    if not self.current_plan_id: raise ValueError("current_plan_id 未设置")
                    # TODO: Implement robust parsing for step_id/index and update_data from tool_params
                    step_identifier = tool_params.get("step_id") or (self.last_dispatched_step.id if self.last_dispatched_step else None)
                    update_data_dict = tool_params.get("update_data", {"status": "completed"}) # Default to marking completed?
                    if not step_identifier: raise ValueError("Missing step identifier (step_id or context) for update_step")
                    # Need logic to convert step_identifier (could be ID or index) and update_data_dict to arguments for plan_manager.update_step
                    # Assuming update_step takes plan_id, step_id (or index), and a dict for updates
                    logger.warning(f"[{self.name}]: update_step parameter handling logic needs implementation.")
                    # Example (needs real implementation based on plan_manager.update_step signature):
                    # exec_resp = self.plan_manager.update_step(
                    #     plan_id_str=str(self.current_plan_id),
                    #     step_id=step_identifier, # or step_index=...
                    #     update_data=update_data_dict
                    # )
                    # tool_execution_result = exec_resp
                    # if exec_resp["success"]: tool_success = True
                    # else: error_message = exec_resp.get("message", "update_step 执行失败")
                    raise NotImplementedError("Parsing and execution logic for update_step tool call is not fully implemented.")

                elif tool_call_requested == TOOL_GET_PLAN:
                    if not self.current_plan_id: raise ValueError("current_plan_id 未设置")
                    # TODO: Add parsing for plan_id from tool_params if LLM might specify it.
                    exec_resp = self.plan_manager.get_plan(str(self.current_plan_id))
                    tool_execution_result = exec_resp
                    if exec_resp["success"]: tool_success = True
                    else: error_message = exec_resp.get("message", "get_plan 执行失败")
                
                # else: # No need for else if create_plan is ignored/removed
                #     error_message = f"未知的工具名称: {tool_call_requested}"

            except NotImplementedError as nie:
                logger.error(f"[{self.name}]: Tool '{tool_call_requested}' logic not implemented: {nie}")
                error_message = str(nie)
                tool_execution_result = {"status": "error", "message": error_message}
            except Exception as tool_exec_err:
                 logger.error(f"[{self.name}]: 执行工具 '{tool_call_requested}' 时出错: {tool_exec_err}", exc_info=True)
                 error_message = f"执行工具时出错: {tool_exec_err}"
                 tool_execution_result = {"status": "error", "message": error_message}
            
            # --- Provide Tool Result back to LLM for next thought cycle ---
            tool_response_for_llm = TextMessage(
                role="user", # Or maybe system/tool role depending on AutoGen version/preference
                source=f"tool_{tool_call_requested}",
                content=json.dumps(tool_execution_result) if tool_execution_result else json.dumps({"status":"error", "message":error_message})
            )
            current_context_for_llm.append(tool_response_for_llm)
            
            logger.info(f"[{self.name}]: 工具 '{tool_call_requested}' 执行完毕 (Success: {tool_success})。准备再次调用 LLM 获取最终响应...")
            
            # Second LLM call within the tool execution flow
            try:
                final_llm_response_obj = await self.model_client.create(messages=[m.to_model_message() for m in current_context_for_llm])
                final_llm_response_content = ""
                if hasattr(final_llm_response_obj, 'content') and isinstance(final_llm_response_obj.content, str):
                     final_llm_response_content = final_llm_response_obj.content.strip()
                elif isinstance(final_llm_response_obj, str):
                     final_llm_response_content = final_llm_response_obj.strip()
                else:
                     logger.error(f"[{self.name}]: 第二次 LLM 调用响应格式未知: {final_llm_response_obj}")
                     final_llm_response_content = "[LLM 在工具调用后响应无效]"
                llm_response_content = final_llm_response_content # Update the content for final output
                logger.info(f"[{self.name}]: LLM 在工具调用后的最终响应: '{llm_response_content[:300]}...'")
            except Exception as e2:
                 logger.error(f"[{self.name}]: 第二次 LLM 调用失败 (在工具执行后): {e2}", exc_info=True)
                 yield TextMessage(content=f"[{self.name}] 错误: 第二次 LLM 调用失败 - {e2}", source=self.name, role="assistant")
                 yield Response(chat_message=TextMessage(content="[错误]", source=self.name))
                 return

        if llm_response_content:
            recipient = None
            
            if MSG_ALL_TASKS_DONE in llm_response_content:
                recipient = "StopAgent"
                logger.info(f"[{self.name}]: 检测到结束信号，将消息发送给 StopAgent.")
                self.current_plan_id = None
                self.last_dispatched_step = None
            elif MSG_TERMINATE in llm_response_content:
                 logger.info(f"[{self.name}]: 检测到终止信号 TERMINATE.")
                 recipient = "StopAgent"
                 self.current_plan_id = None 
                 self.last_dispatched_step = None
            else:
                 logger.info(f"[{self.name}]: LLM 生成了文本响应，将作为消息发出。")

            final_message_to_yield = TextMessage(
                content=llm_response_content,
                source=self.name,
                role="assistant",
                recipient=recipient
            )
            yield final_message_to_yield
            yield Response(chat_message=final_message_to_yield)
        else:
             logger.error(f"[{self.name}]: LLM 最终响应为空。无法继续。")
             yield TextMessage(content=f"[{self.name}] 错误: LLM 未能产生有效响应", source=self.name, role="assistant")
             yield Response(chat_message=TextMessage(content="[错误]", source=self.name))

        logger.info(f"[{self.name}]: === 周期结束 === ")

    # ... existing code ...
    # ... rest of the original code ...
    # ... existing code ... 