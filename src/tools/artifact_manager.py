from typing import Dict, Any, Optional, List, Callable
from datetime import datetime
from uuid import UUID, uuid4
from pydantic import BaseModel, Field, ValidationError, field_validator
from src.tools.storage import Storage, DumbStorage, normalize_id

# --- 统一的 Artifact 数据结构 ---
class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    content: Any
    tags: List[str] = []
    created_at: datetime = Field(default_factory=datetime.now)
    author: str
    description: Optional[str] = None

    @field_validator('title', 'author')
    @classmethod
    def not_empty(cls, v, info):
        if not v or not v.strip():
            raise ValueError(f"{info.field_name}不能为空")
        return v

class ArtifactManager:
    def __init__(self, turn_manager, storage: Optional[Storage] = None):
        self.turn_manager = turn_manager
        self.storage = storage or DumbStorage()
        self.namespace = "artifacts"

    def create_artifact(self, title: str, content: Any, author: str, tags: Optional[List[str]] = None, description: Optional[str] = None, artifact_index: str = '', artifact_name: Optional[str] = None) -> Dict[str, Any]:
        try:
            artifact = Artifact(id=artifact_index, title=title, content=content, author=author, tags=tags or [], description=description)
            self.storage.save(self.namespace, artifact, artifact_index, artifact_name)
            return {"success": True, "data": artifact.model_dump(mode='json')}
        except (ValidationError, ValueError) as ve:
            return {"success": False, "error": str(ve)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def get_artifact(self, artifact_index: str) -> Dict[str, Any]:
        try:
            data = self.storage.load(self.namespace, artifact_index)
            if data:
                return {"success": True, "data": data}
            return {"success": False, "error": "未找到指定ID的artifact"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def list_artifacts(self, tags: Optional[List[str]] = None, keywords: Optional[str] = None) -> Dict[str, Any]:
        try:
            all_data = self.storage.list(self.namespace)
            # 过滤
            if tags:
                tag_set = set(tags)
                all_data = [a for a in all_data if tag_set.issubset(set(a.get('tags', [])))]
            if keywords:
                kw = keywords.lower()
                all_data = [a for a in all_data if kw in a.get('title', '').lower() or (isinstance(a.get('content', ''), str) and kw in a.get('content', '').lower())]
            return {"success": True, "data": all_data}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def update_artifact(self, artifact_index: str, update_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            data = self.storage.load(self.namespace, artifact_index)
            if not data:
                return {"success": False, "error": "未找到指定ID的artifact"}
            artifact = Artifact.model_validate(data)
            updated = artifact.model_copy(update=update_data)
            self.storage.save(self.namespace, updated, artifact_index, updated.title)
            return {"success": True, "data": updated.model_dump(mode='json')}
        except ValidationError as ve:
            return {"success": False, "error": str(ve)}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def delete_artifact(self, artifact_index: str) -> Dict[str, Any]:
        try:
            self.storage.delete(self.namespace, artifact_index)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def tool_list(self) -> list[Callable]:
        return [
            self.create_artifact,
            self.get_artifact,
            self.list_artifacts,
            self.update_artifact,
            self.delete_artifact
        ]


