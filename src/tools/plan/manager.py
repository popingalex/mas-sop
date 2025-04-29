from typing import Dict, List, Any, Optional, Annotated, Literal
from uuid import uuid4, UUID
from pydantic import BaseModel, Field, field_validator, ValidationError
from datetime import datetime
from loguru import logger
import os
import json

# Assuming types.py is in the parent directory or PYTHONPATH is configured
from ..types import ResponseType, success, error

# --- Pydantic Models for Plan and Step --- #

PlanStatus = Literal["not_started", "in_progress", "completed", "error"]
StepStatus = Literal["not_started", "in_progress", "completed", "error"]

class Note(BaseModel):
    """代表附加到步骤的笔记。"""
    id: UUID = Field(default_factory=uuid4)
    content: str
    author: str
    timestamp: datetime = Field(default_factory=datetime.now)

class Step(BaseModel):
    """代表计划中的一个步骤。"""
    id: str # Usually index as string, managed by PlanManager
    title: str = Field(..., min_length=1)
    content: str = ""
    status: StepStatus = "not_started"
    assignee: str = Field(..., min_length=1)
    notes: List[Note] = Field(default_factory=list)
    sub_plan_ids: List[UUID] = Field(default_factory=list) # IDs of sub-plans linked to this step
    result: Optional[Any] = None # Optional field to store step execution result

class Plan(BaseModel):
    """代表一个完整的计划或子计划。"""
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(..., min_length=1)
    steps: List[Step] = Field(default_factory=list)
    reporter: str = Field(..., min_length=1)
    # ID of the parent step (format "plan_uuid/step_id_str") if this is a sub-plan
    parent_step_id: Optional[str] = None
    status: PlanStatus = "not_started"

    @field_validator('parent_step_id')
    @classmethod
    def check_parent_step_id_format(cls, v):
        if v is None:
            return v
        if isinstance(v, str) and "/" in v:
            try:
                # Check if the plan part is a valid UUID
                UUID(v.split("/", 1)[0])
                return v
            except ValueError:
                raise ValueError('parent_step_id 的计划部分必须是有效的 UUID')
        raise ValueError('parent_step_id 必须是 "plan_uuid/step_id_str" 格式的字符串或 None')

# --- PlanManager Class --- #

class PlanManager:
    """管理计划和步骤，使用 Pydantic 模型。"""

    def __init__(self, log_dir: Optional[str] = None):
        """初始化 PlanManager，可选支持基于文件的持久化。"""
        self._plans: Dict[UUID, Plan] = {}
        self.log_dir = log_dir
        self.plans_file = None
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            self.plans_file = os.path.join(log_dir, "plans.json")
            self._load_from_file()

    def _load_from_file(self) -> None:
        """从 JSON 文件加载计划数据。"""
        if not self.plans_file or not os.path.exists(self.plans_file):
            self._plans = {}
            logger.info("未找到计划文件或未配置日志目录，初始化为空。")
            return

        loaded_count = 0
        failed_count = 0
        temp_plans: Dict[UUID, Plan] = {}
        try:
            with open(self.plans_file, "r", encoding="utf-8") as f:
                plans_data: List[Dict] = json.load(f)

            for data in plans_data:
                try:
                    plan = Plan.model_validate(data)
                    temp_plans[plan.id] = plan
                    loaded_count += 1
                except ValidationError as ve:
                    logger.error(f"加载单个计划时验证失败: {ve}, data: {data}")
                    failed_count += 1
                except Exception as e:
                    logger.error(f"加载单个计划时发生未知错误: {e}, data: {data}")
                    failed_count += 1

            self._plans = temp_plans
            log_message = f"从 {self.plans_file} 加载完成：成功 {loaded_count} 个计划"
            if failed_count > 0:
                log_message += f"，失败 {failed_count} 个"
            logger.info(log_message)

        except json.JSONDecodeError as e:
            logger.error(f"加载计划文件 JSON 解析错误: {self.plans_file}, {e}")
            self._plans = {}
        except Exception as e:
            logger.error(f"加载计划文件时发生未知错误: {e}")
            self._plans = {}

    def _save_to_file(self) -> None:
        """将所有计划数据保存到 JSON 文件。"""
        if not self.plans_file:
            return
        try:
            plans_list = [plan.model_dump(mode='json') for plan in self._plans.values()]
            os.makedirs(os.path.dirname(self.plans_file), exist_ok=True)
            with open(self.plans_file, "w", encoding="utf-8") as f:
                json.dump(plans_list, f, ensure_ascii=False, indent=2)
            # logger.debug(f"成功将 {len(plans_list)} 个计划保存到 {self.plans_file}") # Debug level might be better
        except Exception as e:
            logger.error(f"保存计划数据到文件失败: {e}")

    # --- Plan Operations --- #

    def create_plan(
        self,
        title: Annotated[str, "计划的标题"],
        reporter: Annotated[str, "创建计划的 Agent 或用户标识"],
        steps_data: Annotated[Optional[List[Dict]], "可选：包含步骤信息的字典列表，例如 [{'title': 'Step 1', 'assignee': 'AgentA', 'content': '...'}] "] = None,
        parent_step_id: Annotated[Optional[str], "可选：如果这是一个子计划，指定父步骤的 ID (格式: \"plan_uuid/step_index_str\")"] = None,
        plan_id_str: Annotated[Optional[str], "可选：指定计划的 UUID 字符串"] = None
    ) -> ResponseType:
        """创建一个新的计划 (Plan)。"""
        plan_data = {"title": title, "reporter": reporter}
        if parent_step_id is not None:
            plan_data["parent_step_id"] = parent_step_id
        if steps_data is not None:
            # Basic validation before passing to Pydantic
            if not isinstance(steps_data, list):
                 return error("'steps_data' 必须是字典列表")
            plan_data["steps"] = steps_data # Pydantic will validate steps structure

        try:
            plan_id: Optional[UUID] = None
            if plan_id_str:
                try:
                    plan_id = UUID(plan_id_str)
                    if plan_id in self._plans:
                         return error(f"计划 ID {plan_id_str} 已存在")
                    plan_data['id'] = plan_id # Pass validated UUID to model
                except ValueError:
                    return error(f"提供的 plan_id_str '{plan_id_str}' 不是有效的 UUID 格式")

            new_plan = Plan.model_validate(plan_data)
            plan_id = new_plan.id # Get the final ID (generated or provided)

            # Renumber step IDs if steps were provided
            for i, step in enumerate(new_plan.steps):
                step.id = str(i)

            self._plans[plan_id] = new_plan

            # 如果是子计划，更新父步骤的 sub_plan_ids
            if new_plan.parent_step_id:
                self._link_sub_plan_to_parent(new_plan.parent_step_id, plan_id)

            self._save_to_file()
            logger.info(f"计划 '{new_plan.title}' (ID: {plan_id}) 创建成功 by {new_plan.reporter}")
            return success("计划创建成功", result=new_plan.model_dump(mode='json'))

        except ValidationError as ve:
            logger.error(f"创建计划时验证失败: {ve}, data: {plan_data}")
            return error(f"创建计划失败：输入数据验证错误 - {ve}")
        except Exception as e:
            logger.error(f"创建计划时发生未知错误: {e}")
            return error(f"创建计划时发生未知错误: {e}")

    def _link_sub_plan_to_parent(self, parent_step_id_str: str, child_plan_id: UUID) -> None:
        """内部辅助方法：将子计划 ID 添加到父步骤的 sub_plan_ids。"""
        try:
            parent_plan_id_str, parent_step_idx_str = parent_step_id_str.split("/", 1)
            parent_plan_id = UUID(parent_plan_id_str)
            parent_plan = self._plans.get(parent_plan_id)

            if not parent_plan:
                logger.error(f"链接子计划失败，找不到父计划: {parent_plan_id_str}")
                return

            step_found = False
            for step in parent_plan.steps:
                if step.id == parent_step_idx_str:
                    if child_plan_id not in step.sub_plan_ids:
                        step.sub_plan_ids.append(child_plan_id)
                        logger.info(f"已将子计划 {child_plan_id} 添加到父步骤 {parent_step_id_str} 的 sub_plan_ids 中")
                    step_found = True
                    break

            if not step_found:
                logger.error(f"链接子计划失败，找不到步骤 {parent_step_idx_str} 在计划 {parent_plan_id_str} 中")

        except ValueError:
             logger.error(f"链接子计划失败，父步骤 ID 格式错误: {parent_step_id_str}")
        except Exception as e:
            logger.error(f"链接子计划时发生未知错误: {e}")

    def get_plan(self, plan_id_str: Annotated[str, "要获取的计划的 UUID 字符串"]) -> ResponseType:
        """获取指定 ID 的计划详情。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(f"提供的 plan_id_str '{plan_id_str}' 不是有效的 UUID 格式")

        plan = self._plans.get(plan_id)
        if not plan:
            return error(f"计划 {plan_id_str} 未找到")
        return success("获取计划成功", result=plan.model_dump(mode='json'))

    def list_plans(self) -> ResponseType:
        """列出所有计划。"""
        plan_list = [p.model_dump(mode='json') for p in self._plans.values()]
        logger.info(f"列出 {len(plan_list)} 个计划")
        return success("获取计划列表成功", result=plan_list)

    async def get_next_executable_step(self, assignee: Optional[str] = None) -> Optional[Step]:
        """查找下一个状态为 'not_started' 的步骤。
        
        Args:
            assignee: 可选，用于过滤特定分配对象的步骤。

        Returns:
            第一个匹配的 Step 对象，如果未找到则返回 None。
        """
        logger.debug(f"Searching for next executable step (assignee: {assignee or 'Any'})...")
        # 简单的顺序查找，可以优化为更复杂的调度逻辑
        for plan_id in self._plans:
            plan = self._plans[plan_id]
            # 只在状态为 'not_started' 或 'in_progress' 的计划中查找步骤
            if plan.status not in ["not_started", "in_progress"]:
                 continue 
                 
            for step in plan.steps:
                if step.status == "not_started":
                    if assignee is None or step.assignee == assignee:
                        logger.info(f"Found next executable step: Plan {plan_id} Step {step.id} ('{step.title}') for assignee '{step.assignee}'")
                        # 返回 Step 模型实例，确保调用方拿到完整信息
                        # 需要确保返回的 Step 包含 plan_id 信息，以便后续更新
                        # 可以在 Step 模型中添加 plan_id 字段，或者在这里返回一个包含 plan_id 的字典
                        # 暂时返回原始 Step 对象，调用方需要 plan_id 可从 manager 获取
                        # **重要**: 返回 Pydantic 模型，SOPAgent 中类型提示是 Step
                        # 但是直接返回 plan.steps 里的 Step 可能缺少 Plan ID 信息
                        # 最好的方式可能是返回一个包含 plan_id 和 step 数据的字典或新模型
                        # 简单起见，暂时返回 Step，但标记这里可能需要修改
                        # TODO: Consider returning a dict with {'plan_id': plan_id, 'step': step.model_dump()} for clarity
                        return step # 返回 Pydantic 模型实例
        
        logger.debug("No executable step found.")
        return None

    def delete_plan(self, plan_id_str: Annotated[str, "要删除的计划的 UUID 字符串"]) -> ResponseType:
        """删除指定 ID 的计划。注意：这不会自动删除子计划或更新父计划的引用。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(f"提供的 plan_id_str '{plan_id_str}' 不是有效的 UUID 格式")

        if plan_id not in self._plans:
            return error(f"计划 {plan_id_str} 未找到")

        deleted_plan_title = self._plans[plan_id].title
        # TODO: Handle parent/child references? Maybe just log a warning?
        # For now, simple deletion.
        del self._plans[plan_id]
        self._save_to_file()
        logger.info(f"计划 '{deleted_plan_title}' (ID: {plan_id_str}) 已删除")
        return success(f"计划 {plan_id_str} 已删除")

    def update_plan_status(
        self, plan_id_str: Annotated[str, "要更新状态的计划的 UUID 字符串"],
        status: Annotated[PlanStatus, "新的计划状态 (not_started, in_progress, completed, error)"]
    ) -> ResponseType:
        """更新指定计划的状态。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(f"提供的 plan_id_str '{plan_id_str}' 不是有效的 UUID 格式")

        plan = self._plans.get(plan_id)
        if not plan:
            return error(f"计划 {plan_id_str} 未找到")

        # Validate status
        valid_statuses = get_args(PlanStatus)
        if status not in valid_statuses:
            return error(f"无效的状态 '{status}'. 允许的状态: {valid_statuses}")

        if plan.status != status:
            plan.status = status
            self._save_to_file()
            logger.info(f"计划 '{plan.title}' (ID: {plan_id_str}) 状态更新为: {status}")
            return success("计划状态更新成功", result=plan.model_dump(mode='json'))
        else:
            return success("计划状态未改变", result=plan.model_dump(mode='json'))

    # --- Step Operations --- #

    def add_step(
        self,
        plan_id_str: Annotated[str, "步骤所属计划的 UUID 字符串"],
        title: Annotated[str, "新步骤的标题"],
        assignee: Annotated[str, "负责执行步骤的 Agent 或用户标识"],
        content: Annotated[str, "可选：步骤的详细描述"] = "",
        insert_after_step_index: Annotated[Optional[int], "可选：将步骤插入到指定索引之后 (从 0 开始)，默认为追加到末尾"] = None
    ) -> ResponseType:
        """向指定计划添加一个新步骤。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(f"提供的 plan_id_str '{plan_id_str}' 不是有效的 UUID 格式")

        plan = self._plans.get(plan_id)
        if not plan:
            return error(f"计划 {plan_id_str} 未找到")

        # Determine insertion index
        insert_index: int
        if insert_after_step_index is None:
            insert_index = len(plan.steps)
        else:
            if not isinstance(insert_after_step_index, int) or insert_after_step_index < -1 or insert_after_step_index >= len(plan.steps):
                 return error(f"无效的 insert_after_step_index: {insert_after_step_index}. 应为 -1 到 {len(plan.steps)-1} 之间的整数。")
            insert_index = insert_after_step_index + 1

        try:
            # Create new Step object (Pydantic will validate title, assignee)
            # ID will be assigned after insertion
            new_step = Step(id="TEMP", title=title, content=content, assignee=assignee)

            # Insert and renumber steps
            plan.steps.insert(insert_index, new_step)
            for i, step in enumerate(plan.steps):
                step.id = str(i)

            self._recalculate_plan_status(plan_id) # Recalculate plan status after adding step
            self._save_to_file()
            logger.info(f"步骤 '{title}' (ID: {new_step.id}) 已添加到计划 '{plan.title}' (ID: {plan_id_str}) 的索引 {new_step.id}")
            return success("步骤添加成功", result=plan.model_dump(mode='json')) # Return the whole updated plan

        except ValidationError as ve:
             logger.error(f"添加步骤时验证失败: {ve}, title={title}, assignee={assignee}")
             return error(f"添加步骤失败：输入数据验证错误 - {ve}")
        except Exception as e:
             logger.error(f"添加步骤时发生未知错误: {e}")
             return error(f"添加步骤时发生未知错误: {e}")

    def update_step(
        self,
        plan_id_str: Annotated[str, "步骤所属计划的 UUID 字符串"],
        step_index: Annotated[int, "要更新的步骤的索引 (从 0 开始)"],
        update_data: Annotated[Dict[str, Any], "包含要更新字段的字典，例如 {'title': '新标题', 'status': 'in_progress', 'result': ...}"]
    ) -> ResponseType:
        """更新计划中指定索引的步骤。

           可更新字段: title, content, status, assignee, result
        """
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(f"提供的 plan_id_str '{plan_id_str}' 不是有效的 UUID 格式")

        plan = self._plans.get(plan_id)
        if not plan:
            return error(f"计划 {plan_id_str} 未找到")

        if not isinstance(step_index, int) or step_index < 0 or step_index >= len(plan.steps):
            return error(f"无效的步骤索引 {step_index} (计划 {plan_id_str} 只有 {len(plan.steps)} 个步骤)")

        step_to_update = plan.steps[step_index]

        if not isinstance(update_data, dict) or not update_data:
             return error("'update_data' 必须是一个非空字典")

        allowed_updates = {"title", "content", "status", "assignee", "result"}
        actual_updates = {k: v for k, v in update_data.items() if k in allowed_updates}

        if not actual_updates:
            return error(f"'update_data' 中没有可更新的字段。允许的字段: {allowed_updates}")

        try:
            # Validate status if provided
            if "status" in actual_updates:
                valid_statuses = get_args(StepStatus)
                if actual_updates["status"] not in valid_statuses:
                    return error(f"无效的状态 '{actual_updates['status']}'. 允许的状态: {valid_statuses}")

            # Use model_copy for safe update and validation
            updated_step = step_to_update.model_copy(update=actual_updates)
            plan.steps[step_index] = updated_step # Replace the step in the list

            self._recalculate_plan_status(plan_id) # Recalculate plan status after step update
            self._save_to_file()
            updated_fields_str = ", ".join(actual_updates.keys())
            logger.info(f"计划 '{plan.title}' 的步骤 {step_index} ('{updated_step.title}') 更新了字段: {updated_fields_str}")
            return success("步骤更新成功", result=updated_step.model_dump(mode='json'))

        except ValidationError as ve:
            logger.error(f"更新步骤 {step_index} 时验证失败: {ve}, updates: {actual_updates}")
            return error(f"更新步骤失败：输入数据验证错误 - {ve}")
        except Exception as e:
            logger.error(f"更新步骤 {step_index} 时发生未知错误: {e}")
            return error(f"更新步骤 {step_index} 时发生未知错误: {e}")

    def add_note_to_step(
        self,
        plan_id_str: Annotated[str, "步骤所属计划的 UUID 字符串"],
        step_index: Annotated[int, "要添加笔记的步骤的索引 (从 0 开始)"],
        content: Annotated[str, "笔记内容"],
        author: Annotated[str, "添加笔记的 Agent 或用户标识"]
    ) -> ResponseType:
        """向指定计划的指定步骤添加笔记。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(f"提供的 plan_id_str '{plan_id_str}' 不是有效的 UUID 格式")

        plan = self._plans.get(plan_id)
        if not plan:
            return error(f"计划 {plan_id_str} 未找到")

        if not isinstance(step_index, int) or step_index < 0 or step_index >= len(plan.steps):
            return error(f"无效的步骤索引 {step_index} (计划 {plan_id_str} 只有 {len(plan.steps)} 个步骤)")

        step_to_update = plan.steps[step_index]

        if not content or not author:
             return error("笔记内容 (content) 和作者 (author) 不能为空")

        try:
            new_note = Note(content=str(content), author=str(author))
            step_to_update.notes.append(new_note)
            self._save_to_file()
            logger.info(f"笔记已添加到计划 '{plan.title}' 的步骤 {step_index} ('{step_to_update.title}') by {author}")
            # Return the updated step or the note?
            return success("笔记添加成功", result=new_note.model_dump(mode='json'))
        except ValidationError as ve:
             logger.error(f"添加笔记时验证失败: {ve}, content={content}, author={author}")
             return error(f"添加笔记失败：输入数据验证错误 - {ve}")
        except Exception as e:
             logger.error(f"添加笔记时发生未知错误: {e}")
             return error(f"添加笔记时发生未知错误: {e}")

    def _recalculate_plan_status(self, plan_id: UUID) -> None:
        """根据步骤状态重新计算并可能更新计划状态。"""
        plan = self._plans.get(plan_id)
        if not plan:
            return

        original_status = plan.status
        if not plan.steps:
            # No steps, plan remains not_started unless manually set otherwise?
            # Or should it be completed? Let's keep it as is for now.
            # plan.status = "completed" # Or keep original?
            pass
        elif any(step.status == "error" for step in plan.steps):
            plan.status = "error"
        elif all(step.status == "completed" for step in plan.steps):
            plan.status = "completed"
        elif any(step.status == "in_progress" for step in plan.steps) or \
             (all(step.status == "not_started" for step in plan.steps) and original_status == "in_progress"): # If any step started, plan is in_progress
             plan.status = "in_progress"
        # Otherwise, it stays not_started or its current state if manually set

        if plan.status != original_status:
            logger.info(f"计划 '{plan.title}' (ID: {plan_id}) 状态根据步骤自动更新为: {plan.status}")
            self._save_to_file() # Save if status changed

    # --- Utility --- #
    @staticmethod
    def format_parent_step_id(plan_id: UUID, step_id: str) -> str:
        """格式化父步骤 ID。"""
        return f"{str(plan_id)}/{step_id}" 