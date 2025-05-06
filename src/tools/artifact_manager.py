import os
from pathlib import Path
from typing import Dict, Any, Optional, List, Literal
from typing_extensions import TypedDict
from loguru import logger
from ruamel.yaml import YAML, YAMLError
import io
from datetime import datetime
from .types import ResponseType, success, error
from .errors import ErrorMessages
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ValidationError, field_validator
import json

# --- REMOVED Global in-memory storage ---
# _artifact_storage: Dict[str, Any] = {}

# --- 统一的 Artifact 数据结构 ---
class Artifact(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    content: Any
    tags: List[str] = []
    created_at: datetime = Field(default_factory=datetime.now)
    author: str
    description: Optional[str] = None
    path: Optional[str] = None  # 仅多文件模式下记录物理路径

    @field_validator('title', 'author')
    @classmethod
    def not_empty(cls, v, info):
        if not v or not v.strip():
            raise ValueError(f"{info.field_name}不能为空")
        return v

class ArtifactManager:
    """管理制品，将其保存为 YAML 文件。"""

    def __init__(
        self,
        base_dir: str | Path = ".",
        storage_mode: Literal["single", "multi"] = "single",
        storage_format: Literal["yaml", "json"] = "yaml"
    ):
        """初始化制品管理器。

        Args:
            base_dir: 制品存储目录，如果不指定则使用当前目录下的 'artifacts' 子目录
            storage_mode: 存储模式，"single" 表示单文件模式，"multi" 表示多文件模式
            storage_format: 存储格式，"yaml" 表示 YAML 格式，"json" 表示 JSON 格式
        """
        self.base_dir = Path(base_dir)
        self.storage_mode = storage_mode
        self.storage_format = storage_format
        self.yaml = YAML(typ='safe')
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        self.yaml.preserve_quotes = True

        if self.storage_mode == "single":
            self.artifact_file = self.base_dir / f"artifact.{self.storage_format}"
            self.base_dir.mkdir(parents=True, exist_ok=True)
            if not self.artifact_file.exists():
                self._save_all([])
        else:
            self.artifact_dir = self.base_dir / "artifact"
            self.artifact_dir.mkdir(parents=True, exist_ok=True)

    # --- 单文件模式下的全部读写 ---
    def _load_all(self) -> List[Artifact]:
        if not self.artifact_file.exists():
            return []
        try:
            if self.storage_format == "yaml":
                with open(self.artifact_file, 'r', encoding='utf-8') as f:
                    data = self.yaml.load(f) or []
            else:
                with open(self.artifact_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            return [Artifact.model_validate(a) for a in data]
        except Exception as e:
            logger.error(f"加载artifact文件失败: {e}")
            return []

    def _save_all(self, artifacts: List[Artifact]):
        data = [a.model_dump(mode='json') for a in artifacts]
        try:
            if self.storage_format == "yaml":
                with open(self.artifact_file, 'w', encoding='utf-8') as f:
                    self.yaml.dump(data, f)
            else:
                with open(self.artifact_file, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存artifact文件失败: {e}")

    # --- 多文件模式下的单个读写 ---
    def _get_artifact_path(self, artifact_id: UUID) -> Path:
        ext = 'yaml' if self.storage_format == 'yaml' else 'json'
        return self.artifact_dir / f"{artifact_id}.{ext}"

    def _load_one(self, artifact_id: UUID) -> Optional[Artifact]:
        file_path = self._get_artifact_path(artifact_id)
        if not file_path.exists():
            return None
        try:
            if self.storage_format == "yaml":
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = self.yaml.load(f)
            else:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            return Artifact.model_validate(data)
        except Exception as e:
            logger.error(f"加载artifact文件失败: {e}")
            return None

    def _save_one(self, artifact: Artifact):
        file_path = self._get_artifact_path(artifact.id)
        data = artifact.model_dump(mode='json')
        try:
            if self.storage_format == "yaml":
                with open(file_path, 'w', encoding='utf-8') as f:
                    self.yaml.dump(data, f)
            else:
                with open(file_path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存artifact文件失败: {e}")

    # --- CRUD 接口 ---
    def create_artifact(self, title: str, content: Any, author: str, tags: Optional[List[str]] = None, description: Optional[str] = None) -> Dict[str, Any]:
        try:
            artifact = Artifact(title=title, content=content, author=author, tags=tags or [], description=description)
            if self.storage_mode == "single":
                artifacts = self._load_all()
                artifacts.append(artifact)
                self._save_all(artifacts)
            else:
                self._save_one(artifact)
            return {"success": True, "data": artifact.model_dump(mode='json')}
        except (ValidationError, ValueError) as ve:
            return {"success": False, "error": str(ve)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_artifact(self, artifact_id: str) -> Dict[str, Any]:
        try:
            uuid_obj = UUID(artifact_id)
            if self.storage_mode == "single":
                artifacts = self._load_all()
                for a in artifacts:
                    if a.id == uuid_obj:
                        return {"success": True, "data": a.model_dump(mode='json')}
                return {"success": False, "error": "未找到指定ID的artifact"}
            else:
                artifact = self._load_one(uuid_obj)
                if artifact:
                    return {"success": True, "data": artifact.model_dump(mode='json')}
                return {"success": False, "error": "未找到指定ID的artifact"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_artifacts(self, tags: Optional[List[str]] = None, keywords: Optional[str] = None) -> Dict[str, Any]:
        try:
            if self.storage_mode == "single":
                artifacts = self._load_all()
            else:
                artifacts = []
                for file in self.artifact_dir.glob(f"*.{self.storage_format}"):
                    artifact = self._load_one(UUID(file.stem))
                    if artifact:
                        artifacts.append(artifact)
            # 过滤
            if tags:
                tag_set = set(tags)
                artifacts = [a for a in artifacts if tag_set.issubset(set(a.tags))]
            if keywords:
                kw = keywords.lower()
                artifacts = [a for a in artifacts if kw in a.title.lower() or (isinstance(a.content, str) and kw in a.content.lower())]
            return {"success": True, "data": [a.model_dump(mode='json') for a in artifacts]}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_artifact(self, artifact_id: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            uuid_obj = UUID(artifact_id)
            if self.storage_mode == "single":
                artifacts = self._load_all()
                for idx, a in enumerate(artifacts):
                    if a.id == uuid_obj:
                        updated = a.model_copy(update=update_data)
                        artifacts[idx] = updated
                        self._save_all(artifacts)
                        return {"success": True, "data": updated.model_dump(mode='json')}
                return {"success": False, "error": "未找到指定ID的artifact"}
            else:
                artifact = self._load_one(uuid_obj)
                if not artifact:
                    return {"success": False, "error": "未找到指定ID的artifact"}
                updated = artifact.model_copy(update=update_data)
                self._save_one(updated)
                return {"success": True, "data": updated.model_dump(mode='json')}
        except ValidationError as ve:
            return {"success": False, "error": str(ve)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_artifact(self, artifact_id: str) -> Dict[str, Any]:
        try:
            uuid_obj = UUID(artifact_id)
            if self.storage_mode == "single":
                artifacts = self._load_all()
                new_artifacts = [a for a in artifacts if a.id != uuid_obj]
                if len(new_artifacts) == len(artifacts):
                    return {"success": False, "error": "未找到指定ID的artifact"}
                self._save_all(new_artifacts)
                return {"success": True}
            else:
                file_path = self._get_artifact_path(uuid_obj)
                if file_path.exists():
                    file_path.unlink()
                    return {"success": True}
                return {"success": False, "error": "未找到指定ID的artifact"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    # --- 导入导出功能 ---
    def import_artifact_from_file(self, file_path: str) -> Dict[str, Any]:
        try:
            path = Path(file_path)
            if path.suffix == ".yaml":
                with open(path, 'r', encoding='utf-8') as f:
                    data = self.yaml.load(f)
            elif path.suffix == ".json":
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                return {"success": False, "error": "仅支持yaml/json文件"}
            artifact = Artifact.model_validate(data)
            if self.storage_mode == "single":
                artifacts = self._load_all()
                artifacts.append(artifact)
                self._save_all(artifacts)
            else:
                self._save_one(artifact)
            return {"success": True, "data": artifact.model_dump(mode='json')}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def export_artifact_to_file(self, artifact_id: str, file_path: str) -> Dict[str, Any]:
        try:
            uuid_obj = UUID(artifact_id)
            if self.storage_mode == "single":
                artifacts = self._load_all()
                artifact = next((a for a in artifacts if a.id == uuid_obj), None)
            else:
                artifact = self._load_one(uuid_obj)
            if not artifact:
                return {"success": False, "error": "未找到指定ID的artifact"}
            path = Path(file_path)
            data = artifact.model_dump(mode='json')
            if path.suffix == ".yaml":
                with open(path, 'w', encoding='utf-8') as f:
                    self.yaml.dump(data, f)
            elif path.suffix == ".json":
                with open(path, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
            else:
                return {"success": False, "error": "仅支持yaml/json文件"}
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def tool_list(self) -> List[str]:
        """返回工具列表。"""
        return [
            "create_artifact",
            "get_artifact",
            "list_artifacts",
            "update_artifact",
            "delete_artifact",
            "import_artifact_from_file",
            "export_artifact_to_file"
        ]

# --- Placeholder for future Plan Manager Client ---
# This would interact with the WorkflowEngine or a separate planning service
# class PlanManagerClient:
#     def get_current_task(self, agent_name: str) -> Optional[Dict]: ...
#     def update_task_status(self, step_id: str, task_id: str, status: str, message: Optional[str] = None): ...
#     def create_sub_plan(self, parent_step_id: str, tasks: List[Dict]) -> str: ... 

