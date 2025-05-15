from typing import Dict, List, Optional, Annotated, Literal, Union, get_args, Any, Callable
from pydantic import BaseModel, Field, field_validator, ValidationError
from datetime import datetime
from loguru import logger
from ..types import ResponseType, success, error
from ..errors import ErrorMessages
from src.types.plan import Plan, Step, Task, PlanStatus, StepStatus, TaskStatus, TaskNote
from src.tools.storage import Storage, DumbStorage, normalize_id
import traceback

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
                    
                    plan = Plan.model_validate_json(data) if isinstance(data, str) else Plan.model_validate(data)
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
            # 优先用plan.file_name（如无则用plan.name，否则None）
            file_name = getattr(plan, 'file_name', None) or getattr(plan, 'name', None)
            self.storage.save(self.namespace, plan, plan.id, file_name)
        except Exception as e:
            logger.error(f"保存计划数据失败: {e}")
            raise RuntimeError(f"计划持久化失败: {e}")

    # --- Plan Operations --- #

    def _update_next(self, plan: Plan) -> None:
        """自动更新计划的next字段，指向下一个待办任务的索引路径（如 [step_id, task_id]），全部完成时为None。"""
        for step in plan.steps:
            for task in step.tasks:
                if task.status != "completed":
                    plan.next = [step.id, task.id]
                    return
        plan.next = None

    def _create_plan(
        self,
        name: Annotated[str, "计划名称"],
        description: Annotated[str, "计划描述"],
        steps: Annotated[Optional[List[Step]], "步骤列表 (Pydantic Step models)"] = None,
        id: Annotated[str, "计划唯一标识"] = "0",
        plan_name: Annotated[Optional[str], "计划可选名称"] = None,
        parent_task: Annotated[Optional[dict], "父任务索引，如{'id':..., 'step_id':..., 'task_id':...}"] = None
    ) -> ResponseType:
        """
        内部通用计划创建方法，可选parent_task用于子计划挂载。
        """
        try:
            logger.info(f"尝试创建计划: id={id}, plan_name={plan_name}, 调用堆栈: {''.join(traceback.format_stack(limit=5))}")
            if id in self._plans:
                logger.warning(f"重复创建计划被拦截: id={id}, plan_name={plan_name}, 调用堆栈: {''.join(traceback.format_stack(limit=5))}")
                return error(ErrorMessages.PLAN_EXISTS.format(plan_id=id))
            new_plan = Plan(
                id=id,
                name=name,
                description=description,
                steps=steps if steps is not None else [],
                next=None,
                file_name=plan_name
            )
            self._update_next(new_plan)
            self._plans[id] = new_plan
            self.storage.save(self.namespace, new_plan, id, plan_name)
            # 如有parent_task，挂载到父任务的sub_plans
            if parent_task:
                p_id, s_id, t_id = parent_task['id'], parent_task['step_id'], parent_task['task_id']
                plan = self._plans.get(p_id)
                if plan:
                    step = next((s for s in plan.steps if s.id == s_id), None)
                    if step:
                        task = next((t for t in step.tasks if t.id == t_id), None)
                        if task:
                            if task.sub_plans is None:
                                task.sub_plans = []
                            task.sub_plans.append({'id': id, 'name': name})
                            self._save_plan(plan)
            return success("计划创建成功", data=new_plan.model_dump(mode='json'))
        except ValidationError as ve:
            logger.error(f"创建计划时Pydantic校验失败: {ve}")
            return error(f"创建计划时数据校验失败: {ve}")
        except Exception as e:
            logger.exception(f"创建计划时发生未知错误: {e}")
            return error(str(e))

    def create_plan(
        self,
        name: Annotated[str, "计划名称"],
        description: Annotated[str, "计划描述"],
        steps: Annotated[Optional[List[Step]], "步骤列表 (Pydantic Step models)"] = None,
        id: Annotated[str, "计划唯一标识"] = "0",
        plan_name: Annotated[Optional[str], "计划可选名称"] = None
    ) -> ResponseType:
        """
        创建新计划（仅SOPManager使用）。
        Args:
            name: 计划名称。
            description: 计划描述。
            steps: 步骤列表。
            id: 计划唯一标识。
            plan_name: 计划可选名称。
        Returns:
            ResponseType: 新建计划信息。
        """
        return self._create_plan(name, description, steps, id, plan_name, parent_task=None)

    def create_sub_plan(
        self,
        name: Annotated[str, "子计划名称"],
        description: Annotated[str, "子计划描述"],
        steps: Annotated[Optional[List[Step]], "步骤列表 (Pydantic Step models)"] = None,
        id: Annotated[str, "子计划唯一标识"] = "0.1",
        plan_name: Annotated[Optional[str], "子计划可选名称"] = None,
        parent_task: Annotated[dict, "父任务索引，必须包含id, step_id, task_id"] = None
    ) -> ResponseType:
        """
        创建子计划（仅SOPAgent使用）。
        Args:
            name: 子计划名称。
            description: 子计划描述。
            steps: 步骤列表。
            id: 子计划唯一标识。
            plan_name: 子计划可选名称。
            parent_task: 父任务索引，必须包含id, step_id, task_id。
        Returns:
            ResponseType: 新建子计划信息。
        """
        if not parent_task:
            return error("parent_task为必填，必须包含id, step_id, task_id")
        return self._create_plan(name, description, steps, id, plan_name, parent_task=parent_task)

    def get_plan(self, id: str) -> ResponseType:
        """
        获取指定计划的详细信息，包括计划结构、状态和所有步骤、任务。

        Args:
            id (str): 计划唯一标识（plan_id）。
        Returns:
            ResponseType: 包含计划详细结构、状态、所有步骤和任务的dict。
        重要说明：
            - 返回结构中包含 next 字段，格式为 [step_id, task_id]，均为字符串。
            - next 指向下一个必须推进的任务（即第一个未完成的任务）。
            - 只能推进 next 指向的任务，不能跳步或提前推进后续任务。
        用法示例：
            - 查询计划当前状态、所有步骤、任务分配情况。
            - 获取计划的最新任务ID、步骤ID，用于后续工具调用。
            - 通过 next 字段唯一确定下一个任务。
        返回示例：
            {
                "id": "0",                  # 计划ID
                "name": "SAFE_SOP_v8.1_Declarative",  # 计划名称
                "status": "in_progress",   # 计划状态
                "steps": [...],              # 步骤列表
                "next": ["3", "2"]      # 下一个必须推进的任务 [step_id, task_id]
            }
        """
        plan = self._plans.get(id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=id))
        return success("获取计划成功", data=plan.model_dump(mode='json'))

    def delete_plan(self, id: str) -> ResponseType:
        if id not in self._plans:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=id))
        deleted_plan_name = self._plans[id].name
        self.storage.delete(self.namespace, id)
        del self._plans[id]
        logger.info(f"计划 '{deleted_plan_name}' (ID: {id}) 已删除")
        return success(f"计划 {id} 已删除")

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
        
        # 检查索引是否越界
        if insert_after_index is not None and (insert_after_index < -1 or insert_after_index >= len(plan.steps)):
            return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(
                index=insert_after_index,
                plan_id=plan_id_str,
                total=len(plan.steps)
            ))

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
        self._cascade_status_update(plan)
        self._update_next(plan)
        self._save_plan(plan)
        logger.info(f"步骤 '{new_step.description[:30]}...' 已添加到计划 '{plan.name}'")
        return success("步骤添加成功", data=plan.model_dump(mode='json'))

    def _cascade_status_update(self, plan: Plan) -> None:
        """
        递归刷新plan下所有step和task的状态，实现任务→步骤→计划的级联状态同步。
        """
        step_status_set = set()
        for step in plan.steps:
            original_step_status = step.status
            if not step.tasks:
                step.status = "not_started"
            elif all(task.status == "completed" for task in step.tasks):
                step.status = "completed"
            elif any(task.status == "in_progress" for task in step.tasks):
                step.status = "in_progress"
            elif all(task.status == "not_started" for task in step.tasks):
                step.status = "not_started"
            else:
                step.status = "in_progress"  # 存在completed和not_started混合
            if step.status != original_step_status:
                logger.info(f"步骤 '{step.id or step.index}' 状态根据任务自动更新为: {step.status}")
            step_status_set.add(step.status)
        original_plan_status = plan.status
        if step_status_set == {"completed"} and plan.steps:
            plan.status = "completed"
        elif "in_progress" in step_status_set or ("completed" in step_status_set and "not_started" in step_status_set):
             plan.status = "in_progress"
        else:
            plan.status = "not_started"
        if plan.status != original_plan_status:
            logger.info(f"计划 '{plan.name}' (ID: {plan.id}) 状态根据步骤自动更新为: {plan.status}")

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
        self._cascade_status_update(plan)
        self._update_next(plan)
        self._save_plan(plan)
        logger.info(f"任务 '{new_task.name}' 已添加到计划 '{plan.name}' 的步骤 '{target_step.id or target_step.index}'")
        return success("任务添加成功", data=target_step.model_dump(mode='json'))
        
    def update_task(
        self,
        plan_id: Annotated[str, "计划ID"],
        step_id: Annotated[str, "步骤ID"],
        task_id: Annotated[str, "任务ID"],
        update_data: Annotated[Dict[str, Any], "要更新的字段及新值"],
        author: Annotated[str, "操作人名称"]
    ) -> ResponseType:
        """
        更新指定计划下某步骤的某个任务，并自动追加操作记录（note），支持sub_plan_id关联。
        Args:
            plan_id: 计划ID。
            step_id: 步骤ID。
            task_id: 任务ID。
            update_data: 要更新的字段及新值。
            author: 操作人名称。
        Returns:
            ResponseType: 更新结果。
        """
        logger.info(f"[update_task] called with plan_id={plan_id}, step_id={step_id}, task_id={task_id}, update_data={update_data}, author={author}")
        tm = self.turn_manager
        if author is None:
            logger.error("update_task 必须传入 author")
            return error("update_task 必须传入 author")
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
        # 字段更新
        updated_fields = []
        for k, v in update_data.items():
            if k == "sub_plan_id":
                # 关联子计划
                if target_task.sub_plans is None:
                    target_task.sub_plans = []
                # 只添加id，name需由调用方补充或后续完善
                target_task.sub_plans.append({"id": v, "name": None})
                updated_fields.append(k)
            elif k == "notes":
                from src.types.plan import TaskNote
                # 如果传入的是字符串，自动转为TaskNote
                if isinstance(v, str):
                    v = [TaskNote(author=author, content=v, turn=tm.turn)]
                elif isinstance(v, dict):
                    v = [TaskNote(**v)]
                elif isinstance(v, list):
                    v = [TaskNote(**item) if isinstance(item, dict) else item for item in v]
                setattr(target_task, k, v)
                updated_fields.append(k)
            elif hasattr(target_task, k):
                setattr(target_task, k, v)
                updated_fields.append(k)
        # notes内容
        from src.types.plan import TaskNote
        note = TaskNote(author=author, content="任务状态/内容变更", turn=tm.turn)
        if not hasattr(target_task, "notes") or target_task.notes is None:
            target_task.notes = []
        target_task.notes.append(note)
        logger.debug(f"[update_task] notes追加: {note}")
        logger.info(f"[update_task] after: task.status={target_task.status}, updated_fields={updated_fields}")
        self._cascade_status_update(plan)
        self._update_next(plan)
        self._save_plan(plan)
        return success({"id": target_task.id, "name": target_task.name, "status": target_task.status, "notes": target_task.notes})

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
        plan_id: Annotated[str, "计划ID"],
        step_id: Annotated[str, "步骤ID"],
        task_id: Annotated[str, "任务ID"]
    ) -> ResponseType:
        """
        获取指定任务详细信息，并补充plan_info/step_info。
        Args:
            plan_id: 计划ID。
            step_id: 步骤ID。
            task_id: 任务ID。
        Returns:
            ResponseType: 任务详细信息+plan_info/step_info。
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
        return success("获取任务成功", data={
            "task": task.model_dump(mode='json'),
            "plan_info": {"name": getattr(plan, "name", None), "label": None, "description": plan.description},
            "step_info": {"name": step.name, "label": None, "description": step.description}
        })

    def tool_list(self) -> list:
        """只返回新API工具方法对象集合。"""
        return [
            self.get_plan,
            self.create_plan,
            self.create_sub_plan,
            self.get_task,
            self.update_task,
        ]
    