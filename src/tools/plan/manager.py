from typing import Dict, List, Optional, Annotated, Literal, Union, get_args, Any, Callable
from uuid import uuid4, UUID
from pydantic import BaseModel, Field, field_validator, ValidationError
from datetime import datetime
from loguru import logger
from ..types import ResponseType, success, error
from ..errors import ErrorMessages
from src.types.plan import Plan, Step, Task, PlanStatus, StepStatus, TaskStatus, TaskNote
from src.tools.storage import Storage, DumbStorage, normalize_id

# --- PlanManager Class --- #

class PlanManager:
    """管理计划和步骤，使用 Pydantic 模型和通用存储后端。"""

    def __init__(self, turn_manager, storage: Optional[Storage] = None):
        self.storage = storage or DumbStorage()
        self.namespace = "plans"
        self.turn_manager = turn_manager  # 必须传入
        self._plans: Dict[str, Plan] = {}
        self._load_plans()

    def _load_plans(self) -> None:
        try:
            all_data = self.storage.list(self.namespace)
            loaded_count = 0
            failed_count = 0
            temp_plans: Dict[str, Plan] = {}
            
            for data in all_data:
                try:
                    plan_id_str = data.get("id")
                    if not plan_id_str:
                        logger.error(f"加载计划数据时缺少ID: {data}")
                        failed_count += 1
                        continue
                    
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
            log_message = f"加载完成：成功 {loaded_count} 个计划"
            if failed_count > 0:
                log_message += f"，失败 {failed_count} 个"
            logger.info(log_message)

        except Exception as e:
            logger.error(f"加载计划数据时发生未知错误: {e}")
            self._plans = {}

    def _save_plan(self, plan: Plan) -> None:
        try:
            self.storage.save(self.namespace, plan, plan.id)
        except Exception as e:
            logger.error(f"保存计划数据失败: {e}")
            raise RuntimeError(f"计划持久化失败: {e}")

    # --- Plan Operations --- #

    def create_plan(
        self,
        title: Annotated[str, "计划标题"],
        description: Annotated[str, "计划描述"],
        steps: Annotated[Optional[List[Step]], "步骤列表 (Pydantic Step models)"] = None,
        plan_index: Annotated[str, "计划索引，如'0'"] = "0",
        plan_name: Annotated[Optional[str], "计划可选名称"] = None
    ) -> ResponseType:
        """
        创建新计划，使用Pydantic模型。

        Args:
            title: 计划标题。
            description: 计划描述。
            steps: 步骤列表（List[Step]，可选），每个步骤支持以下字段：
                - id: 步骤唯一标识（可选）
                - name: 步骤名称（可选）
                - description: 步骤描述（必填）
                - assignee: 步骤指派人（可选）
                - status: 步骤状态（not_started, in_progress, completed, error，可选，默认not_started）
                - tasks: 任务列表（List[Task]，可选），每个任务支持：
                    - id: 任务唯一标识
                    - name: 任务名称
                    - description: 任务描述
                    - assignee: 任务指派人（可选）
                    - status: 任务状态（not_started, in_progress, completed, error，可选，默认not_started）
            plan_index: 计划索引，如'0'。
            plan_name: 计划可选名称。

        Returns:
            ResponseType: 包含新建计划的详细信息（data字段为Plan的dict结构）。
        """
        try:
            if plan_index in self._plans:
                return error(ErrorMessages.PLAN_EXISTS.format(plan_id=plan_index))
            new_plan = Plan(
                id=plan_index,
                title=title,
                description=description,
                steps=steps if steps is not None else []
            )
            self._plans[plan_index] = new_plan
            self.storage.save(self.namespace, new_plan, plan_index, plan_name)
            return success("计划创建成功", data=new_plan.model_dump(mode='json'))
        except ValidationError as ve:
            logger.error(f"创建计划时Pydantic校验失败: {ve}")
            return error(f"创建计划时数据校验失败: {ve}")
        except Exception as e:
            logger.exception(f"创建计划时发生未知错误: {e}")
            return error(str(e))

    def get_plan(self, plan_index: str) -> ResponseType:
        """
        获取指定ID的计划详情。

        Args:
            plan_index: 计划索引（字符串）。
        Returns:
            ResponseType: 包含计划的详细信息（data字段为Plan的dict结构，字段同Plan/Step/Task定义）。
        """
        plan = self._plans.get(plan_index)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_index))
        return success("获取计划成功", data=plan.model_dump(mode='json'))

    def list_plans(self) -> ResponseType:
        """
        列出所有计划。

        Returns:
            ResponseType: 包含所有计划的列表（data字段为List[Plan]的dict结构，字段同Plan/Step/Task定义）。
        """
        plan_list = [p.model_dump(mode='json') for p in self._plans.values()]
        logger.info(f"列出 {len(plan_list)} 个计划")
        return success("获取计划列表成功", data=plan_list)

    def delete_plan(self, plan_index: str) -> ResponseType:
        """
        删除指定ID的计划。

        Args:
            plan_index: 计划索引（字符串）。
        Returns:
            ResponseType: 删除结果。
        """
        if plan_index not in self._plans:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_index))

        deleted_plan_title = self._plans[plan_index].title
        self.storage.delete(self.namespace, plan_index)
        del self._plans[plan_index]
        logger.info(f"计划 '{deleted_plan_title}' (ID: {plan_index}) 已删除")
        return success(f"计划 {plan_index} 已删除")

    # --- Step Operations --- #

    def add_step(
        self,
        plan_id_str: Annotated[str, "步骤所属计划的ID"],
        step_data: Annotated[Step, "要添加的步骤对象"],
        insert_after_index: Annotated[Optional[int], "可选：将步骤插入到指定索引之后"] = None
    ) -> ResponseType:
        """
        添加新步骤到指定计划。

        Args:
            plan_id_str: 步骤所属计划的UUID字符串。
            step_data: 要添加的步骤对象（Step），支持字段：
                - id: 步骤唯一标识（可选）
                - name: 步骤名称（可选）
                - description: 步骤描述（必填）
                - assignee: 步骤指派人（可选）
                - status: 步骤状态（可选）
                - tasks: 任务列表（List[Task]，可选）
            insert_after_index: 可选，插入到指定索引后。

        Returns:
            ResponseType: 包含更新后计划的详细信息（data字段为Plan的dict结构）。
        """
        plan = self._plans.get(plan_id_str)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))
        new_step = step_data.model_copy(deep=True)
        # 自动生成step id：序号_名称
        step_index = len(plan.steps) if insert_after_index is None else insert_after_index + 1
        new_step.id = new_step.id or normalize_id(str(step_index + 1), new_step.name)
        if insert_after_index is not None:
            plan.steps.insert(insert_after_index + 1, new_step)
        else:
            plan.steps.append(new_step)
        for i, s in enumerate(plan.steps):
            s.index = i
        self._recalculate_plan_status(plan_id_str)
        self._save_plan(plan)
        logger.info(f"步骤 '{new_step.description[:30]}...' 已添加到计划 '{plan.title}'")
        return success("步骤添加成功", data=plan.model_dump(mode='json'))

    def _recalculate_plan_status(self, plan_id: str) -> None:
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
            logger.info(f"计划 '{plan.title}' (ID: {plan_id}) 状态根据步骤自动更新为: {plan.status}")
            # _save_to_file() will be called by the public method that triggered this recalculation
            # self._save_to_file() # Avoid double saving if called from a method that already saves

    # --- Task Operations --- #

    def add_task_to_step(
        self,
        plan_id_str: Annotated[str, "计划ID"],
        step_id_or_index: Annotated[Union[str, int], "步骤的ID或索引"],
        task_data: Annotated[Task, "要添加的任务对象"]
    ) -> ResponseType:
        """
        向指定计划的指定步骤添加任务。

        Args:
            plan_id_str: 计划ID。
            step_id_or_index: 步骤的ID或索引。
            task_data: 要添加的任务对象（Task），支持字段：
                - id: 任务唯一标识
                - name: 任务名称
                - description: 任务描述
                - assignee: 任务指派人（可选）
                - status: 任务状态（可选）
        Returns:
            ResponseType: 包含更新后计划的详细信息（data字段为Plan的dict结构）。
        """
        plan = self._plans.get(plan_id_str)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))
        if isinstance(step_id_or_index, int):
            if 0 <= step_id_or_index < len(plan.steps):
                target_step = plan.steps[step_id_or_index]
            else:
                return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(index=step_id_or_index, plan_id=plan_id_str, total=len(plan.steps)))
        elif isinstance(step_id_or_index, str):
            target_step = next((s for s in plan.steps if s.id == step_id_or_index), None)
            if not target_step:
                return error(ErrorMessages.STEP_NOT_FOUND_BY_ID.format(step_id=step_id_or_index, plan_id=plan_id_str))
        else:
            return error("step_id_or_index 必须是字符串ID或整数索引。")
        new_task = task_data.model_copy(deep=True)
        # 自动生成task id：序号_名称
        task_index = len(target_step.tasks)
        new_task.id = new_task.id or normalize_id(f"{target_step.index+1}.{task_index+1}", new_task.name)
        target_step.tasks.append(new_task)
        self._save_plan(plan)
        logger.info(f"任务 '{new_task.name}' 已添加到计划 '{plan.title}' 的步骤 '{target_step.id or target_step.index}'")
        return success("任务添加成功", data=target_step.model_dump(mode='json'))
        
    def update_task(
        self,
        plan_id: str,
        step_id: str,
        task_id: str,
        update_data: Dict[str, Any],
        author: str
    ) -> ResponseType:
        """
        更新指定计划下某步骤的某个任务，并自动追加操作记录（note）。

        Args:
            plan_id (str): 计划ID。
            step_id (str): 步骤ID。
            task_id (str): 任务ID。
            update_data (dict): 要更新的字段及新值，支持如下字段：
                - status (str): 任务状态（如 'completed', 'in_progress', 'not_started', 'error'）。
                - assignee (str): 任务负责人。
                - name (str): 任务名称。
                - description (str): 任务描述。
                - 其他Task模型支持的字段。
            author (str): 操作人名称，必须传入。

        Returns:
            ResponseType: 更新结果，包含任务最新状态和完整notes列表。

        说明:
            - 每次调用都会自动追加一条note，记录author、from_status、to_status、turn等。
            - notes为必填，不能为[]。
            - 仅支持已定义的任务字段更新。

        示例:
            update_task(
                plan_id="0",
                step_id="1",
                task_id="2",
                update_data={"status": "completed", "assignee": "Strategist"},
                author="Strategist"
            )
        """
        logger.info(f"[update_task] called with plan_id={plan_id}, step_id={step_id}, task_id={task_id}, update_data={update_data}, author={author}")
        tm = self.turn_manager
        if author is None:
            logger.error("update_task 必须传入 author")
            raise ValueError("update_task 必须传入 author")
        logger.info(f"[update_task] 当前turn = {tm.turn}")
        plan = self._plans.get(plan_id)
        if not plan:
            logger.error(f"[update_task] 未找到计划: {plan_id}")
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id))

        target_step: Optional[Step] = None
        for s in plan.steps:
            if s.id == step_id:
                target_step = s
                break
        if not target_step:
            logger.error(f"[update_task] 未找到步骤: {step_id}")
            return error(ErrorMessages.NOT_FOUND.format(resource="步骤", id_str=step_id))

        target_task: Optional[Task] = None
        for t in target_step.tasks:
            if t.id == task_id:
                target_task = t
                break
        if not target_task:
            logger.error(f"[update_task] 未找到任务: {task_id}")
            return error(ErrorMessages.NOT_FOUND.format(resource="任务", id_str=task_id))

        # 记录变更前状态
        from_status = getattr(target_task, "status", None)
        # 执行字段更新
        updated_fields = []
        for k, v in update_data.items():
            if hasattr(target_task, k):
                setattr(target_task, k, v)
                updated_fields.append(k)
        # 记录变更后状态
        to_status = getattr(target_task, "status", None)
        # notes内容
        note = {
            "author": author,
            "content": "任务状态/内容变更",
            "from_status": from_status,
            "to_status": to_status,
            "turn": tm.turn
        }
        if not hasattr(target_task, "notes") or target_task.notes is None:
            target_task.notes = []
        target_task.notes.append(note)
        logger.debug(f"[update_task] notes追加: {note}")
        logger.info(f"[update_task] after: task.status={target_task.status}, updated_fields={updated_fields}")
        self._save_plan(plan)
        return success({"id": target_task.id, "name": target_task.name, "status": target_task.status, "notes": target_task.notes})

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
             # Saving is handled by the caller (update_task)

    # --- Helper & Utility Methods (continued) --- #
    def get_pending(self, plan_id_str: str) -> ResponseType:
        logger.info(f"[get_pending] called for plan_id={plan_id_str}")
        try:
            plan_id = plan_id_str
        except ValueError:
            logger.error(f"[get_pending] 无效的计划ID: {plan_id_str}")
            return error(f"无效的计划ID: {plan_id_str}")
        plan = self._plans.get(plan_id)
        if not plan:
            logger.error(f"[get_pending] 未找到计划: {plan_id_str}")
            return error(f"未找到计划: {plan_id_str}")
        logger.debug(f"[get_pending] plan.status={plan.status}, steps={len(plan.steps)}")
        for step in plan.steps:
            logger.debug(f"[get_pending] step.id={step.id}, step.status={step.status}, tasks={len(step.tasks)}")
            for task in step.tasks:
                logger.debug(f"[get_pending] task.id={task.id}, task.status={task.status}")
                if hasattr(task, "subplan_id") and task.subplan_id:
                    subplan = self._plans.get(task.subplan_id)
                    if not subplan or not self._is_plan_completed(subplan):
                        logger.info(f"[get_pending] 存在未完成的子计划任务: step={step.id}, task={task.id}")
                        return success("存在未完成的子计划任务", data={
                            "status": "pending",
                            "step": step.model_dump(mode='json'),
                            "task": task.model_dump(mode='json')
                        })
                elif task.status != "completed":
                    logger.info(f"[get_pending] 存在未完成任务: step={step.id}, task={task.id}")
                    return success("存在未完成任务", data={
                        "status": "pending",
                        "step": step.model_dump(mode='json'),
                        "task": task.model_dump(mode='json')
                    })
        logger.info(f"[get_pending] 所有任务已完成: plan_id={plan_id_str}")
        return success("所有任务已完成", data={"status": "completed"})

    def _is_plan_completed(self, plan: Plan) -> bool:
        """递归判断计划及其所有子计划是否完成"""
        for step in plan.steps:
            for task in step.tasks:
                if hasattr(task, "subplan_id") and task.subplan_id:
                    subplan = self._plans.get(task.subplan_id)
                    if not subplan or not self._is_plan_completed(subplan):
                        return False
                elif task.status != "completed":
                    return False
        return True

    def get_task(
        self,
        plan_id: str,
        step_id: str,
        task_id: str
    ) -> ResponseType:
        """
        根据计划ID、步骤ID、任务ID查找并返回任务内容。

        Args:
            plan_id (str): 计划ID。
            step_id (str): 步骤ID。
            task_id (str): 任务ID。
        Returns:
            ResponseType: 查询结果，data字段为任务内容（dict），未找到时返回错误信息。
        """
        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id))
        step = next((s for s in plan.steps if s.id == step_id), None)
        if not step:
            return error(ErrorMessages.NOT_FOUND.format(resource="步骤", id_str=step_id))
        task = next((t for t in step.tasks if t.id == task_id), None)
        if not task:
            return error(ErrorMessages.NOT_FOUND.format(resource="任务", id_str=task_id))
        return success("获取任务成功", data=task.model_dump(mode='json'))

    def tool_list(self) -> List[Callable]:
        """返回PlanManager可用的工具方法对象集合。"""
        return [
            self.create_plan,
            self.get_plan,
            self.list_plans,
            self.delete_plan,
            self.add_step,
            self.add_task_to_step,
            self.update_task,
            self.get_pending,
            self.get_task,
        ]
    