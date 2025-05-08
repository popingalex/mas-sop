from typing import Dict, List, Optional, Annotated, Literal, Union, get_args, Any
from uuid import uuid4, UUID
from pydantic import BaseModel, Field, field_validator, ValidationError
from datetime import datetime
from loguru import logger
import os
import json

# Assuming types.py is in the parent directory or PYTHONPATH is configured
from ..types import ResponseType, success, error
from ..errors import ErrorMessages
from src.types.plan import Plan, Step, Task, PlanStatus, StepStatus # Import Pydantic models and new Status types if defined there

# --- Type Definitions --- #

# PlanStatus, StepStatus are now expected to be imported from .types or defined within Pydantic models if needed for validation.
# Note TypedDict - REMOVED for now
# Step TypedDict - REMOVED (using Pydantic Step from .types)
# Plan TypedDict - REMOVED (using Pydantic Plan from .types)

class UUIDEncoder(json.JSONEncoder):
    """自定义JSON编码器，支持UUID序列化"""
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        # if isinstance(obj, datetime): # Keep if notes or other datetime fields are re-introduced
        #     return obj.isoformat()
        if isinstance(obj, BaseModel): # Add support for Pydantic models
            return obj.model_dump()
        return super().default(obj)

# --- PlanManager Class --- #

class PlanManager:
    """管理计划和步骤，使用 Pydantic 模型。"""

    def __init__(self, log_dir: Optional[str] = None):
        """初始化 PlanManager，可选支持基于文件的持久化。"""
        self._plans: Dict[UUID, Plan] = {} # Plan is now Pydantic model
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
                plans_data: List[Dict] = json.load(f) # Load as list of dicts first

            for data in plans_data:
                try:
                    # Validate and convert plan_id from str to UUID if necessary before Plan.model_validate
                    # Assuming 'id' in JSON is a string representation of UUID.
                    plan_id_str = data.get("id")
                    if not plan_id_str:
                        logger.error(f"加载计划数据时缺少ID: {data}")
                        failed_count += 1
                        continue
                    
                    # Ensure data["id"] is UUID for Pydantic model if it expects UUID type directly
                    # Our Pydantic Plan model has id: str, so direct validation is fine.
                    plan = Plan.model_validate(data) # Use Pydantic model validation
                    temp_plans[UUID(plan.id)] = plan # Store with UUID as key
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
            # Convert Pydantic models to dicts for JSON serialization using model_dump()
            plans_list = [plan.model_dump(mode='json') for plan in self._plans.values()] 
            os.makedirs(os.path.dirname(self.plans_file), exist_ok=True)
            with open(self.plans_file, "w", encoding="utf-8") as f:
                json.dump(plans_list, f, ensure_ascii=False, indent=2) # UUIDEncoder might not be needed if model_dump handles it
        except Exception as e:
            logger.error(f"保存计划数据到文件失败: {e}")

    # --- Plan Operations --- #

    def create_plan(
        self,
        title: Annotated[str, "计划标题"],
        description: Annotated[str, "计划描述"],
        steps: Annotated[Optional[List[Step]], "步骤列表 (Pydantic Step models)"] = None,
        plan_id_str: Annotated[Optional[str], "指定计划ID (string for UUID)"] = None
    ) -> ResponseType:
        """创建新计划，使用Pydantic模型。
        
        Args:
            title: 计划标题
            description: 计划描述
            steps: 步骤列表 (Pydantic Step models), 每个步骤可以包含tasks.
            plan_id_str: 指定计划ID (字符串形式的UUID)，如果不指定则自动生成.
        """
        try:
            plan_id: UUID
            if plan_id_str:
                try:
                    plan_id = UUID(plan_id_str)
                    if plan_id in self._plans:
                        return error(ErrorMessages.PLAN_EXISTS.format(plan_id=plan_id_str))
                except ValueError:
                    return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))
            else:
                plan_id = uuid4()

            # Create Plan Pydantic model instance
            new_plan = Plan(
                id=str(plan_id), # Store as string in model as per definition
                title=title,
                description=description,
                steps=steps if steps is not None else []
                # status is defaulted by Pydantic model to "pending" if Plan model has it, or set explicitly here.
                # Our current Plan model in types.py does not have a top-level status.
                # It would be good to add status: PlanStatus = "not_started" to the Plan model in types.py
            )
            
            self._plans[plan_id] = new_plan # Use UUID object as key
            self._save_to_file()
            
            # Return the Pydantic model directly, or its dict representation
            return success("计划创建成功", data=new_plan.model_dump(mode='json'))
            
        except ValidationError as ve: # Catch Pydantic validation errors if steps_data is malformed
            logger.error(f"创建计划时Pydantic校验失败: {ve}")
            return error(f"创建计划时数据校验失败: {ve}")
        except Exception as e:
            logger.exception(f"创建计划时发生未知错误: {e}")
            return error(str(e))

    def get_plan(self, plan_id_str: Annotated[str, "要获取的计划的 UUID 字符串"]) -> ResponseType:
        """获取指定 ID 的计划详情。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))
        return success("获取计划成功", data=plan.model_dump(mode='json')) # Return dict representation

    def list_plans(self) -> ResponseType:
        """列出所有计划。"""
        # Return list of dict representations of plans
        plan_list = [p.model_dump(mode='json') for p in self._plans.values()]
        logger.info(f"列出 {len(plan_list)} 个计划")
        return success("获取计划列表成功", data=plan_list)

    def delete_plan(self, plan_id_str: Annotated[str, "要删除的计划的 UUID 字符串"]) -> ResponseType:
        """删除指定 ID 的计划。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        if plan_id not in self._plans:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        deleted_plan_title = self._plans[plan_id].title
        del self._plans[plan_id]
        self._save_to_file()
        logger.info(f"计划 '{deleted_plan_title}' (ID: {plan_id_str}) 已删除")
        return success(f"计划 {plan_id_str} 已删除")

    # update_plan_status can be reinstated or modified if direct status manipulation is needed
    # For now, plan status is primarily derived via _recalculate_plan_status
    def update_plan_status(
        self, plan_id_str: Annotated[str, "要更新状态的计划的 UUID 字符串"],
        status: Annotated[PlanStatus, "新的计划状态"]
    ) -> ResponseType:
        """更新指定计划的状态。通常计划状态由步骤状态派生，但此方法允许直接设置。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        valid_statuses = get_args(PlanStatus)
        if status not in valid_statuses:
            return error(ErrorMessages.PLAN_INVALID_STATUS.format(
                status=status,
                valid_statuses=valid_statuses
            ))

        if plan.status != status:
            plan.status = status
            self._save_to_file()
            logger.info(f"计划 '{plan.title}' (ID: {plan_id_str}) 状态手动更新为: {status}")
            return success("计划状态更新成功", data=plan.model_dump(mode='json'))
        else:
            return success("计划状态未改变", data=plan.model_dump(mode='json'))

    # --- Step Operations --- #

    def add_step(
        self,
        plan_id_str: Annotated[str, "步骤所属计划的 UUID 字符串"],
        step_data: Annotated[Step, "要添加的步骤对象 (Pydantic Step model, index will be ignored and recalculated)"],
        insert_after_index: Annotated[Optional[int], "可选：将步骤插入到指定索引之后 (从 0 开始)，默认为追加到末尾"] = None
    ) -> ResponseType:
        """添加新步骤到指定计划。步骤的 index 会被重新计算。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))
        
        # Ensure step_data is a Pydantic Step model instance or can be validated into one.
        # For simplicity, assume step_data is already a valid Pydantic Step object by the caller.
        # The id and index of the new step will be set/overwritten by this method.
        new_step = step_data.model_copy(deep=True) # Work with a copy

        if insert_after_index is not None:
            if not (-1 <= insert_after_index < len(plan.steps)):
                return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(
                    index=insert_after_index,
                    plan_id=plan_id_str,
                    total=len(plan.steps)
                ))
            plan.steps.insert(insert_after_index + 1, new_step)
        else:
            plan.steps.append(new_step)

        # Re-index all steps and assign unique IDs if they don't have one
        for i, s in enumerate(plan.steps):
            s.index = i
            if s.id is None: # Assign a simple string ID if not present
                s.id = f"step_{i}"
        
        self._recalculate_plan_status(plan_id)
        self._save_to_file()
        
        logger.info(f"步骤 '{new_step.description[:30]}...' 已添加到计划 '{plan.title}'")
        return success("步骤添加成功", data=plan.model_dump(mode='json'))

    def update_step(
        self,
        plan_id_str: Annotated[str, "计划ID"],
        step_id_or_index: Annotated[Union[str, int], "步骤的ID或索引"],
        update_data: Annotated[Dict[str, Any], "要更新的字段字典 (部分更新)"]
    ) -> ResponseType:
        """更新指定计划中特定步骤的信息。可以更新 description, assignee, status, tasks。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        target_step: Optional[Step] = None
        if isinstance(step_id_or_index, int):
            if 0 <= step_id_or_index < len(plan.steps):
                target_step = plan.steps[step_id_or_index]
            else:
                return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(index=step_id_or_index, plan_id=plan_id_str, total=len(plan.steps)))
        elif isinstance(step_id_or_index, str):
            for s in plan.steps:
                if s.id == step_id_or_index:
                    target_step = s
                    break
            if not target_step:
                return error(ErrorMessages.STEP_NOT_FOUND_BY_ID.format(step_id=step_id_or_index, plan_id=plan_id_str))
        else:
            return error("step_id_or_index 必须是字符串ID或整数索引。")

        # Apply updates
        updated_fields = []
        if "description" in update_data:
            target_step.description = update_data["description"]
            updated_fields.append("description")
        if "assignee" in update_data:
            target_step.assignee = update_data["assignee"]
            updated_fields.append("assignee")
        if "status" in update_data:
            new_status = update_data["status"]
            if new_status not in get_args(StepStatus):
                return error(f"无效的步骤状态: {new_status}. 允许的状态: {get_args(StepStatus)}")
            target_step.status = new_status
            updated_fields.append("status")
        
        # For tasks, we expect a full replacement list or specific task operations (add_task, update_task)
        # Simple partial update of tasks list here can be complex.
        # If 'tasks' is in update_data, it should be a List[Task] or List[dict] to be validated.
        if "tasks" in update_data:
            try:
                validated_tasks = [Task.model_validate(t) for t in update_data["tasks"]]
                target_step.tasks = validated_tasks
                updated_fields.append("tasks")
            except ValidationError as ve:
                return error(f"更新步骤时任务数据校验失败: {ve}")
            except Exception as e:
                 return error(f"更新步骤时处理任务数据出错: {e}")

        if not updated_fields:
            return success("没有要更新的有效字段。", data=target_step.model_dump(mode='json'))

        self._recalculate_plan_status(plan_id)
        self._save_to_file()
        
        logger.info(f"计划 '{plan.title}' 的步骤 '{target_step.id if target_step.id else target_step.index}' 更新了字段: {', '.join(updated_fields)}")
        return success("步骤更新成功", data=target_step.model_dump(mode='json'))

    def _recalculate_plan_status(self, plan_id: UUID) -> None:
        """根据步骤状态重新计算并可能更新计划状态。"""
        plan = self._plans.get(plan_id)
        if not plan:
            return

        original_status = plan.status
        if not plan.steps: # No steps
            # If a plan has no steps, should its status be 'completed' or remain 'not_started'?
            # For now, let's say if it had steps and all were completed, it becomes completed.
            # If it never had steps, its status might be manually set or remain not_started.
            # This behavior might need refinement. If it's not_started and has no steps, it remains not_started.
            if original_status != "completed": # Avoid changing if it was explicitly completed
                 plan.status = "not_started"
        elif all(step.status == "completed" for step in plan.steps):
            plan.status = "completed"
        elif any(step.status == "error" for step in plan.steps):
            plan.status = "error"
        elif any(step.status == "in_progress" for step in plan.steps) or \
             (any(step.status == "completed" for step in plan.steps) and original_status == "not_started") or \
             (all(step.status == "not_started" for step in plan.steps) and original_status == "in_progress"): 
             plan.status = "in_progress"
        elif all(step.status == "not_started" for step in plan.steps) and original_status != "in_progress":
            plan.status = "not_started" # All steps are new or reset
        # else: plan status remains unchanged if no clear transition

        if plan.status != original_status:
            logger.info(f"计划 '{plan.title}' (ID: {str(plan_id)}) 状态根据步骤自动更新为: {plan.status}")
            # _save_to_file() will be called by the public method that triggered this recalculation
            # self._save_to_file() # Avoid double saving if called from a method that already saves

    # --- Task Operations --- #

    def add_task_to_step(
        self,
        plan_id_str: Annotated[str, "计划ID"],
        step_id_or_index: Annotated[Union[str, int], "步骤的ID或索引"],
        task_data: Annotated[Task, "要添加的任务对象 (Pydantic Task model)"]
    ) -> ResponseType:
        """向指定计划的特定步骤添加新任务。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        target_step: Optional[Step] = None
        if isinstance(step_id_or_index, int):
            if 0 <= step_id_or_index < len(plan.steps):
                target_step = plan.steps[step_id_or_index]
            else:
                return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(index=step_id_or_index, plan_id=plan_id_str, total=len(plan.steps)))
        elif isinstance(step_id_or_index, str):
            for s in plan.steps:
                if s.id == step_id_or_index:
                    target_step = s
                    break
            if not target_step:
                return error(ErrorMessages.STEP_NOT_FOUND_BY_ID.format(step_id=step_id_or_index, plan_id=plan_id_str))
        else:
            return error("step_id_or_index 必须是字符串ID或整数索引。")
        
        # Ensure task_data is a Pydantic Task model instance.
        # Assume it's passed correctly by the caller.
        new_task = task_data.model_copy(deep=True)

        # Assign a task_id if not provided? The model requires task_id.
        # Ensure task_id is unique within the step?
        existing_task_ids = {t.id for t in target_step.tasks}
        if new_task.id in existing_task_ids:
            # Handle duplicate task_id, e.g., append a suffix or return error
            # For now, let's assume caller provides unique task_id or overwriting is ok/intended.
            # Alternative: Generate a unique ID if needed.
            logger.warning(f"任务 ID '{new_task.id}' 已存在于步骤 '{target_step.id or target_step.index}'. 允许添加，可能导致重复。")
            # OR return error(f"任务 ID '{new_task.task_id}' 已存在于步骤 '{target_step.id or target_step.index}'")
        
        target_step.tasks.append(new_task)
        
        # Should adding a task change step/plan status? Probably not directly.
        # self._recalculate_plan_status(plan_id) 
        self._save_to_file()
        
        logger.info(f"任务 '{new_task.name}' 已添加到计划 '{plan.title}' 的步骤 '{target_step.id or target_step.index}'")
        return success("任务添加成功", data=target_step.model_dump(mode='json'))
        
    def update_task_in_step(
        self,
        plan_id_str: Annotated[str, "计划ID"],
        step_id_or_index: Annotated[Union[str, int], "步骤的ID或索引"],
        task_id: Annotated[str, "要更新的任务的task_id"],
        update_data: Annotated[Dict[str, Any], "要更新的字段字典 (部分更新)"]
    ) -> ResponseType:
        """更新指定计划特定步骤中某个任务的信息。可以更新 name, assignee, description, status。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        target_step: Optional[Step] = None
        if isinstance(step_id_or_index, int):
            if 0 <= step_id_or_index < len(plan.steps):
                target_step = plan.steps[step_id_or_index]
            else:
                return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(index=step_id_or_index, plan_id=plan_id_str, total=len(plan.steps)))
        elif isinstance(step_id_or_index, str):
            for s in plan.steps:
                if s.id == step_id_or_index:
                    target_step = s
                    break
            if not target_step:
                 return error(ErrorMessages.STEP_NOT_FOUND_BY_ID.format(step_id=step_id_or_index, plan_id=plan_id_str))
        else:
            return error("step_id_or_index 必须是字符串ID或整数索引。")
        
        target_task: Optional[Task] = None
        for task in target_step.tasks:
            if task.id == task_id:
                target_task = task
                break
        
        if not target_task:
            return error(f"在步骤 '{target_step.id or target_step.index}' 中未找到 task_id 为 '{task_id}' 的任务。")

        # Apply updates
        updated_fields = []
        if "name" in update_data:
            target_task.name = update_data["name"]
            updated_fields.append("name")
        if "assignee" in update_data:
            target_task.assignee = update_data["assignee"]
            updated_fields.append("assignee")
        if "description" in update_data:
            target_task.description = update_data["description"]
            updated_fields.append("description")
        if "status" in update_data:
            new_status = update_data["status"]
            if new_status not in get_args(TaskStatus):
                return error(f"无效的任务状态: {new_status}. 允许的状态: {get_args(TaskStatus)}")
            target_task.status = new_status
            updated_fields.append("status")
            
        # Add other updatable fields from Task model if needed, e.g., is_atomic if re-added

        if not updated_fields:
            return success("没有要更新的有效字段。", data=target_task.model_dump(mode='json'))

        # Does updating a task status trigger step/plan status recalculation?
        # Yes, if a task completes/errors, the step might complete/error.
        self._recalculate_step_status(target_step) # Need to implement this helper
        self._recalculate_plan_status(plan_id)
        self._save_to_file()
        
        logger.info(f"计划 '{plan.title}' 步骤 '{target_step.id or target_step.index}' 的任务 '{task_id}' 更新了字段: {', '.join(updated_fields)}")
        return success("任务更新成功", data=target_task.model_dump(mode='json'))

    def _recalculate_step_status(self, step: Step) -> None:
        """根据其任务状态重新计算并可能更新步骤状态。"""
        original_status = step.status
        if not step.tasks:
            # If a step has no tasks, should it be considered completed?
            # Or does it rely on its own description/assignee to be acted upon?
            # Let's assume a step without tasks requires manual status update or remains not_started.
            if original_status != "completed":
                step.status = "not_started"
        elif all(task.status == "completed" for task in step.tasks):
            step.status = "completed"
        elif any(task.status == "error" for task in step.tasks):
            step.status = "error"
        elif any(task.status == "in_progress" for task in step.tasks) or \
             (any(task.status == "completed" for task in step.tasks) and original_status == "not_started") or \
             (all(task.status == "not_started" for task in step.tasks) and original_status == "in_progress"): 
             step.status = "in_progress"
        elif all(task.status == "not_started" for task in step.tasks) and original_status != "in_progress":
             step.status = "not_started"
        # else: step status remains unchanged
        
        if step.status != original_status:
             logger.info(f"步骤 '{step.id or step.index}' 状态根据任务自动更新为: {step.status}")
             # Saving is handled by the caller (update_task_in_step)

    # --- Helper & Utility Methods (continued) --- #
    def get_next_pending_step(self, plan_id_str: Annotated[str, "计划ID"]) -> ResponseType:
        """获取指定计划中第一个状态为 'not_started' 的步骤。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        # Find the first step with status "not_started"
        for step in plan.steps:
            if step.status == "not_started":
                return success("获取下一个待处理步骤成功", data=step.model_dump(mode='json'))

        # If no "not_started" step is found
        # Check overall plan status for context
        current_plan_status = plan.status
        if current_plan_status == "completed":
            return success("计划已完成，没有待处理步骤。", data=None)
        elif current_plan_status == "error":
            return success("计划状态为错误，没有待处理步骤。", data=None)
        elif current_plan_status == "in_progress":
             return success("计划正在进行中，但没有 'not_started' 状态的步骤（可能都在进行中或已完成/出错）。", data=None)
        else: # Plan is likely still "not_started" but has no steps or only non-"not_started" steps
             return success("计划中没有状态为 'not_started' 的待处理步骤。", data=None)

    def tool_list(self) -> List[str]:
        """Returns a list of tool names."""
        # This list will need to be updated based on final methods
        return [
            "create_plan",
            "get_plan",
            "list_plans",
            "delete_plan",
            # "update_plan_status", # Commented out for now
            "add_step",
            "update_step",
            "add_task_to_step",      # New
            "update_task_in_step",   # New
            "get_next_pending_step"
            # "add_note_to_step", # Removed for now
        ]
    