from typing import Dict, List, Optional, Annotated, Literal, Union, get_args
from typing_extensions import TypedDict
from uuid import uuid4, UUID
from pydantic import BaseModel, Field, field_validator, ValidationError
from datetime import datetime
from loguru import logger
import os
import json

# Assuming types.py is in the parent directory or PYTHONPATH is configured
from ..types import ResponseType, success, error
from ..errors import ErrorMessages

# --- Type Definitions --- #

PlanStatus = Literal["not_started", "in_progress", "completed", "error"]
StepStatus = Literal["not_started", "in_progress", "completed", "error"]

class Note(TypedDict):
    """步骤笔记"""
    id: UUID  # 系统生成
    content: str  # 笔记内容
    author: str  # 作者ID
    timestamp: datetime  # 系统生成

class Step(TypedDict, total=False):
    """步骤数据结构
    
    必填字段：
    - title: 步骤标题
    - assignee: 负责人ID
    
    可选字段（根据操作类型）：
    - id: 系统分配的步骤ID，创建时不需要
    - content: 步骤详细内容
    - status: 步骤状态，创建时默认为 "not_started"
    - notes: 笔记列表，系统管理
    - sub_plan_ids: 子计划ID列表，系统管理
    """
    # 必填字段
    title: str
    assignee: str
    
    # 可选字段
    id: str  # 系统分配，创建时不需要
    content: str  # 可选的详细内容
    status: StepStatus  # 步骤状态
    notes: List[Note]  # 系统管理的笔记列表
    sub_plan_ids: List[UUID]  # 系统管理的子计划列表

class Plan(TypedDict, total=False):
    """计划数据结构
    
    必填字段：
    - title: 计划标题
    - reporter: 创建者ID
    
    可选字段：
    - id: 系统分配的UUID，创建时可选
    - steps: 步骤列表
    - parent_step_id: 父步骤ID（子计划时使用）
    - status: 计划状态，创建时默认为 "not_started"
    """
    # 必填字段
    title: str
    reporter: str
    
    # 可选字段
    id: UUID  # 系统分配或指定
    steps: List[Step]  # 步骤列表
    parent_step_id: str  # 父步骤ID
    status: PlanStatus  # 计划状态

class UUIDEncoder(json.JSONEncoder):
    """自定义JSON编码器，支持UUID序列化"""
    def default(self, obj):
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)

def _validate_parent_step_id(parent_step_id: Optional[str]) -> bool:
    """验证父步骤ID格式"""
    if parent_step_id is None:
        return True
    if isinstance(parent_step_id, str) and "/" in parent_step_id:
        try:
            UUID(parent_step_id.split("/", 1)[0])
            return True
        except ValueError:
            return False
    return False

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
                    temp_plans[plan["id"]] = plan
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
            plans_list = [plan for plan in self._plans.values()]
            os.makedirs(os.path.dirname(self.plans_file), exist_ok=True)
            with open(self.plans_file, "w", encoding="utf-8") as f:
                json.dump(plans_list, f, ensure_ascii=False, indent=2, cls=UUIDEncoder)
        except Exception as e:
            logger.error(f"保存计划数据到文件失败: {e}")

    # --- Plan Operations --- #

    def create_plan(
        self,
        title: Annotated[str, "计划标题"],
        reporter: Annotated[str, "创建者ID"],
        steps_data: Annotated[Optional[List[Step]], "步骤列表"] = None,
        parent_step_id: Annotated[Optional[str], "父步骤ID"] = None,
        plan_id_str: Annotated[Optional[str], "指定计划ID"] = None
    ) -> ResponseType:
        """创建新计划。
        
        Args:
            title: 计划标题
            reporter: 创建者ID
            steps_data: 步骤列表，每个步骤的字段要求：
                - 必需字段：
                    - title: 步骤标题
                    - assignee: 负责人ID
                - 可选字段：
                    - content: 步骤内容
                - 其他字段将被忽略
            parent_step_id: 父步骤ID（格式："plan_uuid/step_id_str"）
            plan_id_str: 指定计划ID，如果不指定则自动生成
        """
        try:
            # 创建基本计划数据
            plan: Plan = {
                "title": title,
                "reporter": reporter,
                "status": "not_started"
            }
            
            # 处理计划ID
            if plan_id_str:
                try:
                    plan_id = UUID(plan_id_str)
                    if plan_id in self._plans:
                        return error(ErrorMessages.PLAN_EXISTS.format(plan_id=plan_id_str))
                    plan["id"] = plan_id
                except ValueError:
                    return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))
            else:
                plan["id"] = uuid4()
            
            # 处理父步骤ID
            if parent_step_id:
                if not _validate_parent_step_id(parent_step_id):
                    return error(ErrorMessages.PLAN_INVALID_PARENT_STEP)
                plan["parent_step_id"] = parent_step_id
            
            # 处理步骤
            if steps_data:
                plan_steps: List[Step] = []
                for idx, step_data in enumerate(steps_data):
                    step: Step = {
                        "id": str(idx),
                        "title": step_data["title"],
                        "assignee": step_data["assignee"],
                        "status": "not_started",
                        "content": step_data.get("content", ""),
                        "notes": [],
                        "sub_plan_ids": []
                    }
                    plan_steps.append(step)
                plan["steps"] = plan_steps
            else:
                plan["steps"] = []
            
            # 保存计划
            self._plans[plan["id"]] = plan
            self._save_to_file()
            
            return success("计划创建成功", data=plan)
            
        except KeyError as e:
            return error(ErrorMessages.PLAN_MISSING_REQUIRED.format(field=str(e)))
        except Exception as e:
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
        return success("获取计划成功", data=plan)

    def list_plans(self) -> ResponseType:
        """列出所有计划。"""
        plan_list = [p for p in self._plans.values()]
        logger.info(f"列出 {len(plan_list)} 个计划")
        return success("获取计划列表成功", data=plan_list)

    def delete_plan(self, plan_id_str: Annotated[str, "要删除的计划的 UUID 字符串"]) -> ResponseType:
        """删除指定 ID 的计划。注意：这不会自动删除子计划或更新父计划的引用。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        if plan_id not in self._plans:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        deleted_plan_title = self._plans[plan_id]["title"]
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
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        # Validate status
        valid_statuses = get_args(PlanStatus)
        if status not in valid_statuses:
            return error(ErrorMessages.PLAN_INVALID_STATUS.format(
                status=status,
                valid_statuses=valid_statuses
            ))

        if plan["status"] != status:
            plan["status"] = status
            self._save_to_file()
            logger.info(f"计划 '{plan['title']}' (ID: {plan_id_str}) 状态更新为: {status}")
            return success("计划状态更新成功", data=plan)
        else:
            return success("计划状态未改变", data=plan)

    # --- Step Operations --- #

    def add_step(
        self,
        plan_id_str: Annotated[str, "步骤所属计划的 UUID 字符串"],
        title: Annotated[str, "新步骤的标题"],
        assignee: Annotated[str, "负责执行步骤的 Agent 或用户标识"],
        content: Annotated[str, "可选：步骤的详细描述"] = "",
        insert_after_step_index: Annotated[Optional[int], "可选：将步骤插入到指定索引之后 (从 0 开始)，默认为追加到末尾"] = None
    ) -> ResponseType:
        """添加新步骤到指定计划。"""
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        # 创建新步骤
        new_step: Step = {
            "title": title,
            "assignee": assignee,
            "content": content,
            "status": "not_started",
            "notes": []
        }

        # 获取或初始化步骤列表
        steps = plan.get("steps", [])
        if not steps:
            plan["steps"] = steps

        # 插入步骤
        if insert_after_step_index is not None:
            if insert_after_step_index < -1 or insert_after_step_index >= len(steps):
                return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(
                    index=insert_after_step_index,
                    plan_id=plan_id_str,
                    total=len(steps)
                ))
            steps.insert(insert_after_step_index + 1, new_step)
        else:
            steps.append(new_step)

        # 更新步骤索引
        for i, step in enumerate(steps):
            step["id"] = f"{i}"

        # 保存更改
        self._save_to_file()

        # 记录操作
        step_id = len(steps) - 1 if insert_after_step_index is None else insert_after_step_index + 1
        logger.info(f"步骤 '{title}' (ID: {step_id}) 已添加到计划 '{plan['title']}' (ID: {plan_id}) 的索引 {step_id}")

        try:
            return success("步骤添加成功", data=plan)
        except Exception as e:
            logger.error(f"添加步骤时发生未知错误: {e}")
            return error(str(e))

    def update_step(
        self,
        plan_id_str: Annotated[str, "计划ID"],
        step_index: Annotated[int, "步骤索引"],
        update_data: Annotated[Step, "更新数据"]
    ) -> ResponseType:
        """更新步骤信息。
        
        Args:
            plan_id_str: 计划ID
            step_index: 步骤索引
            update_data: 更新数据，字段要求：
                - 可选字段（至少需要一个）：
                    - title: 步骤标题
                    - content: 步骤内容
                    - status: 步骤状态
                    - assignee: 负责人ID
                - 系统管理字段（将被忽略）：
                    - id
                    - notes
                    - sub_plan_ids
        
        状态变更会触发计划状态的自动更新。
        """
        try:
            plan_id = UUID(plan_id_str)
            plan = self._plans.get(plan_id)
            if not plan or not plan.get("steps"):
                return error(ErrorMessages.PLAN_NO_STEPS.format(plan_id=plan_id_str))
            
            if step_index < 0 or step_index >= len(plan["steps"]):
                return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(
                    index=step_index,
                    plan_id=plan_id_str,
                    total=len(plan["steps"])
                ))
            
            current_step = plan["steps"][step_index]
            
            # 只更新允许的字段
            updatable_fields = {"title", "content", "status", "assignee"}
            for field in updatable_fields:
                if field in update_data:
                    current_step[field] = update_data[field]
            
            self._recalculate_plan_status(plan_id)
            self._save_to_file()
            
            return success("步骤更新成功", data=current_step)
            
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))
        except Exception as e:
            return error(str(e))

    def add_note_to_step(
        self,
        plan_id_str: Annotated[str, "计划ID"],
        step_index: Annotated[int, "步骤索引"],
        content: Annotated[str, "笔记内容"],
        author: Annotated[str, "作者ID"]
    ) -> ResponseType:
        """添加步骤笔记。
        
        Args:
            plan_id_str: 计划ID
            step_index: 步骤索引
            content: 笔记内容
            author: 作者ID
        
        Note:
            笔记的 id 和 timestamp 由系统自动生成。
            笔记将按时间顺序追加到步骤的笔记列表中。
        """
        try:
            plan_id = UUID(plan_id_str)
        except ValueError:
            return error(ErrorMessages.INVALID_UUID.format(id_str=plan_id_str))

        plan = self._plans.get(plan_id)
        if not plan:
            return error(ErrorMessages.NOT_FOUND.format(resource="计划", id_str=plan_id_str))

        if not isinstance(step_index, int) or step_index < 0 or step_index >= len(plan["steps"]):
            return error(ErrorMessages.PLAN_STEP_INDEX_OUT_OF_RANGE.format(
                index=step_index,
                plan_id=plan_id_str,
                total=len(plan["steps"])
            ))

        step_to_update = plan["steps"][step_index]

        if not content or not author:
             return error(ErrorMessages.NOTE_CONTENT_AUTHOR_REQUIRED)

        try:
            new_note = Note(
                id=uuid4(),
                content=str(content),
                author=str(author),
                timestamp=datetime.now()
            )
            if "notes" not in step_to_update:
                step_to_update["notes"] = []
            step_to_update["notes"].append(new_note)
            self._save_to_file()
            logger.info(f"笔记已添加到计划 '{plan['title']}' 的步骤 {step_index} ('{step_to_update['title']}') by {author}")
            return success("笔记添加成功", data=step_to_update)
        except ValidationError as ve:
             logger.error(f"添加笔记时验证失败: {ve}, content={content}, author={author}")
             return error(ErrorMessages.NOTE_VALIDATION_ERROR.format(error=str(ve)))
        except Exception as e:
             logger.error(f"添加笔记时发生未知错误: {e}")
             return error(str(e))

    def _recalculate_plan_status(self, plan_id: UUID) -> None:
        """根据步骤状态重新计算并可能更新计划状态。"""
        plan = self._plans.get(plan_id)
        if not plan:
            return

        original_status = plan["status"]
        if not plan["steps"]:
            # No steps, plan remains not_started unless manually set otherwise?
            # Or should it be completed? Let's keep it as is for now.
            # plan["status"] = "completed" # Or keep original?
            pass
        elif any(step["status"] == "error" for step in plan["steps"]):
            plan["status"] = "error"
        elif all(step["status"] == "completed" for step in plan["steps"]):
            plan["status"] = "completed"
        elif any(step["status"] == "in_progress" for step in plan["steps"]) or \
             (all(step["status"] == "not_started" for step in plan["steps"]) and original_status == "in_progress"): # If any step started, plan is in_progress
             plan["status"] = "in_progress"
        # Otherwise, it stays not_started or its current state if manually set

        if plan["status"] != original_status:
            logger.info(f"计划 '{plan['title']}' (ID: {plan_id}) 状态根据步骤自动更新为: {plan['status']}")
            self._save_to_file() # Save if status changed

    # --- Utility --- #
    @staticmethod
    def format_parent_step_id(plan_id: UUID, step_id: str) -> str:
        """格式化父步骤 ID。"""
        return f"{str(plan_id)}/{step_id}" 
    
    def tool_list(self) -> List[str]:
        """Returns a list of tool names."""
        return [
            "create_plan",
            "get_plan",
            "list_plans",
            "delete_plan",
            "update_plan_status",
            "add_step",
            "update_step",
            "add_note_to_step"
        ]
    