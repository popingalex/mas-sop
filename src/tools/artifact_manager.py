import os
from pathlib import Path
from typing import Dict, Any, Optional, List, TypedDict
from loguru import logger
from ruamel.yaml import YAML, YAMLError
import io
from datetime import datetime
from .types import ResponseType, success, error
from .errors import ErrorMessages

# --- REMOVED Global in-memory storage ---
# _artifact_storage: Dict[str, Any] = {}

class Artifact(TypedDict, total=False):
    """制品数据结构
    
    必需字段：
    - id: 制品ID（文件名）
    - content: 制品内容（当前仅支持字符串）
    - created_at: 创建时间
    - format: 存储格式，当前仅支持 'yaml'
    
    可选字段：
    - description: 制品描述
    - event_id: 关联的事件ID
    - path: 文件路径
    """
    id: str  # 制品ID（文件名）
    content: str  # 制品内容
    created_at: datetime  # 创建时间
    format: str  # 存储格式
    description: str  # 制品描述
    event_id: str  # 关联的事件ID
    path: str  # 文件路径

class ArtifactManager:
    """管理制品，将其保存为 YAML 文件。"""

    def __init__(self, base_dir: Optional[Path | str] = None):
        """初始化制品管理器。

        Args:
            base_dir: 制品存储目录，如果不指定则使用当前目录下的 'artifacts' 子目录
        """
        if base_dir:
            self._base_dir = Path(base_dir)
        else:
            self._base_dir = Path("artifacts")
        
        try:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"制品管理器初始化完成，基础目录：{self._base_dir.resolve()}")
        except OSError as e:
            logger.error(f"创建制品目录失败 {self._base_dir}: {e}")
            raise

        self._yaml = YAML(typ='safe')
        self._yaml.indent(mapping=2, sequence=4, offset=2)
        self._yaml.preserve_quotes = True 

    def _get_artifact_path(self, name: str, event_id: Optional[str] = None) -> Path:
        """构建制品文件路径。"""
        safe_name = name.replace('/', '_').replace('\\', '_').replace(':', '_')
        filename = f"{safe_name}.yaml"
        if event_id:
            safe_event_id = event_id.replace('/', '_').replace('\\', '_').replace(':', '_')
            filename = f"{safe_event_id}___{safe_name}.yaml"
        return self._base_dir / filename

    async def save_artifact(
        self, 
        content: str,
        description: Optional[str] = None,
        name: Optional[str] = None,
        event_id: Optional[str] = None,
        preferred_format: str = 'yaml'
    ) -> ResponseType:
        """保存制品到文件。

        Args:
            content: 制品内容（当前仅支持字符串）
            description: 用于生成文件名的描述（如果未提供name）
            name: 制品的逻辑名称（用于生成文件名），优先级高于description
            event_id: 可选的命名空间标识
            preferred_format: 目前仅支持'yaml'

        Note:
            - name 和 description 至少需要提供一个
            - 如果同时提供，description 会作为注释保存
            - 文件名会自动处理特殊字符
        """
        if preferred_format.lower() != 'yaml':
            return error(ErrorMessages.ARTIFACT_FORMAT_UNSUPPORTED.format(format=preferred_format))

        if not name and not description:
            return error(ErrorMessages.ARTIFACT_NAME_REQUIRED)

        artifact_name = name if name else description
        if not artifact_name:
            return error(ErrorMessages.ARTIFACT_NAME_INVALID)

        file_path = self._get_artifact_path(artifact_name, event_id)
        logger.debug(f"正在保存制品 '{artifact_name}' (Event: {event_id}) 到文件: {file_path}")

        try:
            # 构建制品数据
            artifact: Artifact = {
                "id": file_path.name,
                "content": content,
                "created_at": datetime.now(),
                "format": "yaml"
            }
            if description:
                artifact["description"] = description
            if event_id:
                artifact["event_id"] = event_id

            # 保存到文件
            with open(file_path, 'w', encoding='utf-8') as f:
                self._yaml.dump(artifact, f)
            
            logger.info(f"制品 '{artifact_name}' 已保存为 {artifact['id']}")
            # 返回不包含 content 的制品数据
            artifact_info = {k: v for k, v in artifact.items() if k != 'content'}
            return success("制品保存成功", data=artifact_info)

        except (OSError, YAMLError, TypeError) as e:
            logger.exception(f"保存制品 '{artifact_name}' 到 {file_path} 失败: {e}")
            return error(str(e))

    async def load_artifact(self, artifact_id: str) -> ResponseType:
        """根据ID（文件名）加载制品。

        Args:
            artifact_id: 制品ID（文件名，如 'report.yaml' 或 'event1__report.yaml'）
        """
        file_path = self._base_dir / artifact_id
        logger.debug(f"尝试从文件加载制品: {file_path}")

        if not file_path.exists() or not file_path.is_file():
            return error(ErrorMessages.NOT_FOUND.format(resource="制品", id_str=artifact_id))

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                artifact = self._yaml.load(f)
            logger.info(f"成功加载制品: {artifact_id}")
            return success("制品加载成功", data=artifact)
        except (OSError, YAMLError) as e:
            logger.exception(f"从 {file_path} 加载或解析制品失败: {e}")
            return error(str(e))

    async def list_artifacts(self, event_id: Optional[str] = None) -> ResponseType:
        """列出可用的制品。

        Args:
            event_id: 可选的事件ID过滤器，如果提供则只返回该事件相关的制品
        """
        logger.debug(f"列出 {self._base_dir} 中的制品 (Event 过滤: {event_id})")
        artifacts = []
        try:
            for item in self._base_dir.iterdir():
                if item.is_file() and item.suffix.lower() == '.yaml':
                    if event_id:
                        safe_event_id = event_id.replace('/', '_').replace('\\', '_').replace(':', '_')
                        prefix = f"{safe_event_id}__"
                        if item.name.startswith(prefix):
                            with open(item, 'r', encoding='utf-8') as f:
                                artifact = self._yaml.load(f)
                                # 不返回内容
                                if 'content' in artifact:
                                    del artifact['content']
                                artifacts.append(artifact)
                    else:
                        with open(item, 'r', encoding='utf-8') as f:
                            artifact = self._yaml.load(f)
                            # 不返回内容
                            if 'content' in artifact:
                                del artifact['content']
                            artifacts.append(artifact)
            return success("获取制品列表成功", data=artifacts)
        except OSError as e:
            logger.error(f"列出制品失败 {self._base_dir}: {e}")
            return error(str(e))
         
    def tool_list(self) -> List[str]:
        """返回工具列表。"""
        return [
            "save_artifact",
            "load_artifact",
            "list_artifacts"
        ]

# --- Placeholder for future Plan Manager Client ---
# This would interact with the WorkflowEngine or a separate planning service
# class PlanManagerClient:
#     def get_current_task(self, agent_name: str) -> Optional[Dict]: ...
#     def update_task_status(self, step_id: str, task_id: str, status: str, message: Optional[str] = None): ...
#     def create_sub_plan(self, parent_step_id: str, tasks: List[Dict]) -> str: ... 

