from typing import Dict, Any, List, Optional, Literal, Annotated
from datetime import datetime
from uuid import uuid4, UUID
from pydantic import BaseModel, Field, field_validator, ValidationError
# Assuming types.py is in the same directory or PYTHONPATH is configured
from .types import (
    ResponseType, success, error
)
from loguru import logger
import os
import json

class Artifact(BaseModel):
    """Pydantic 模型，用于定义资产的数据结构和验证规则。"""
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(..., min_length=1) # 标题不能为空
    content: Any # 内容可以是任何类型
    tags: List[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    author: str = Field(..., min_length=1) # 作者不能为空

    @field_validator('tags', mode='before')
    @classmethod
    def ensure_tags_list_of_strings(cls, v):
        if isinstance(v, list):
            if all(isinstance(tag, str) for tag in v):
                return v
            else:
                # Attempt to convert non-strings, log warning
                logger.warning(f"Artifact tags list contained non-string elements, attempting conversion: {v}")
                return [str(tag) for tag in v]
        elif v is None:
            return []
        raise ValueError('tags must be a list of strings')

    # Pydantic v2 uses model_dump, model_validate etc.
    # Methods like model_dump() and model_validate() are built-in.

class ArtifactManager:
    """管理资产 (Artifacts)，使用 Pydantic 进行数据验证。"""

    def __init__(self, log_dir: Optional[str] = None):
        """初始化资产管理器，可选支持基于文件的持久化。

        Args:
            log_dir: 可选，用于存储 artifacts.json 的目录路径。
                     如果提供，则启用持久化。
        """
        self._artifacts: Dict[UUID, Artifact] = {}
        self.log_dir = log_dir
        self.artifacts_file = None
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
            # 使用 UUID 作为文件名的一部分可能不是最佳选择，这里仍用固定名称
            self.artifacts_file = os.path.join(log_dir, "artifacts.json")
            self._load_from_file()

    def _load_from_file(self):
        """从 JSON 文件加载资产数据（如果配置了日志目录）。"""
        if not self.artifacts_file or not os.path.exists(self.artifacts_file):
            self._artifacts = {}
            logger.info("未找到资产文件或未配置日志目录，初始化为空。")
            return

        loaded_count = 0
        failed_count = 0
        temp_artifacts: Dict[UUID, Artifact] = {}
        try:
            with open(self.artifacts_file, 'r', encoding='utf-8') as f:
                artifacts_data: List[Dict] = json.load(f)

            for data in artifacts_data:
                try:
                    # 从字典验证并创建 Pydantic 模型
                    artifact = Artifact.model_validate(data)
                    temp_artifacts[artifact.id] = artifact
                    loaded_count += 1
                except ValidationError as ve:
                    logger.error(f"加载单个资产时验证失败: {ve}, data: {data}")
                    failed_count += 1
                except Exception as e:
                    logger.error(f"加载单个资产时发生未知错误: {e}, data: {data}")
                    failed_count += 1

            self._artifacts = temp_artifacts
            log_message = f"从 {self.artifacts_file} 加载完成：成功 {loaded_count} 个"
            if failed_count > 0:
                log_message += f"，失败 {failed_count} 个"
            logger.info(log_message)

        except json.JSONDecodeError as e:
            logger.error(f"加载资产文件 JSON 解析错误: {self.artifacts_file}, {e}")
            self._artifacts = {}
        except Exception as e:
            logger.error(f"加载资产文件时发生未知错误: {e}")
            self._artifacts = {}

    def _save_to_file(self):
        """将所有资产保存到 JSON 文件（如果配置了日志目录）。"""
        if not self.artifacts_file:
            return

        try:
            # 使用 Pydantic 的 model_dump 将模型转为字典进行序列化
            # 使用 default=str 来处理 UUID 和 datetime 等非原生 JSON 类型
            artifacts_data = [artifact.model_dump(mode='json') for artifact in self._artifacts.values()]
            with open(self.artifacts_file, 'w', encoding='utf-8') as f:
                json.dump(artifacts_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存资产到文件 {self.artifacts_file} 失败: {e}")

    def _create(self, data: Dict, artifact_id: Optional[str] = None) -> ResponseType:
        """内部方法：创建资产。"""
        if not isinstance(data, dict):
            return error("创建资产时 'data' 必须是字典")

        try:
            # 如果提供了 artifact_id，尝试转换为 UUID
            if artifact_id:
                try:
                    data['id'] = UUID(artifact_id)
                except ValueError:
                    return error(f"提供的 artifact_id '{artifact_id}' 不是有效的 UUID 格式")

            # 使用 Pydantic 进行验证和创建
            new_artifact = Artifact.model_validate(data)

            if new_artifact.id in self._artifacts:
                return error(f"资产 ID {new_artifact.id} 已存在")

            self._artifacts[new_artifact.id] = new_artifact
            self._save_to_file()
            logger.info(f"资产 '{new_artifact.title}' (ID: {new_artifact.id}) 创建成功 by {new_artifact.author}")
            # 返回验证后的模型数据（字典格式）
            return success("资产创建成功", new_artifact.model_dump(mode='json'))
        except ValidationError as ve:
            logger.error(f"创建资产时验证失败: {ve}, data: {data}")
            return error(f"创建资产失败：输入数据验证错误 - {ve}")
        except Exception as e:
            logger.error(f"创建资产时发生未知错误: {e}")
            return error(f"创建资产时发生未知错误: {e}")

    def _get(self, artifact_id: str) -> ResponseType:
        """内部方法：获取资产详情。"""
        try:
            target_id = UUID(artifact_id)
            artifact = self._artifacts.get(target_id)
            if not artifact:
                return error(f"资产 {artifact_id} 未找到")
            logger.info(f"获取资产 '{artifact.title}' (ID: {artifact_id})")
            return success("获取资产成功", artifact.model_dump(mode='json'))
        except ValueError:
             return error(f"提供的 artifact_id '{artifact_id}' 不是有效的 UUID 格式")

    def _list(self, options: Optional[Dict] = None) -> ResponseType:
        """内部方法：获取资产列表，支持过滤。"""
        results = list(self._artifacts.values())
        tags_filter: Optional[List[str]] = None
        keywords: Optional[str] = None

        if isinstance(options, dict):
            tags_filter = options.get("tags")
            keywords = options.get("keywords")
        elif options is not None:
            logger.warning(f"'options' 参数应为字典，但收到了 {type(options)} 类型，已忽略。")

        # Filter by tags
        if isinstance(tags_filter, list) and tags_filter:
            try:
                tag_set = set(map(str, tags_filter))
                results = [a for a in results if tag_set.issubset(set(a.tags))]
            except Exception as e:
                 logger.warning(f"处理 tags 过滤时出错: {e}, tags_filter: {tags_filter}")
        elif tags_filter is not None:
            logger.warning(f"list options: 'tags' 应为列表，但收到了 {type(tags_filter)} 类型，已忽略。")

        # Filter by keywords
        if isinstance(keywords, str) and keywords:
            kw = keywords.lower()
            filtered_results = []
            for a in results:
                match = False
                if kw in a.title.lower():
                    match = True
                elif isinstance(a.content, str) and kw in a.content.lower():
                    match = True
                if match:
                    filtered_results.append(a)
            results = filtered_results
        elif keywords is not None:
             logger.warning(f"list options: 'keywords' 应为字符串，但收到了 {type(keywords)} 类型，已忽略。")

        logger.info(f"列出 {len(results)} 个资产 (过滤条件: tags={tags_filter}, keywords={keywords})")
        return success("获取资产列表成功", [a.model_dump(mode='json') for a in results])

    def _delete(self, artifact_id: str) -> ResponseType:
        """内部方法：删除资产。"""
        try:
            target_id = UUID(artifact_id)
            if target_id not in self._artifacts:
                return error(f"资产 {artifact_id} 未找到")
            deleted_artifact_title = self._artifacts[target_id].title
            del self._artifacts[target_id]
            self._save_to_file()
            logger.info(f"资产 '{deleted_artifact_title}' (ID: {artifact_id}) 已删除")
            return success(f"资产 {artifact_id} 已删除")
        except ValueError:
            return error(f"提供的 artifact_id '{artifact_id}' 不是有效的 UUID 格式")

    def _update(self, artifact_id: str, data: Dict) -> ResponseType:
        """内部方法：更新资产。"""
        try:
            target_id = UUID(artifact_id)
            if not isinstance(data, dict):
                return error("更新资产时 'data' 必须是字典")
            if not data:
                return error("更新资产时 'data' 不能为空字典")
            if target_id not in self._artifacts:
                return error(f"资产 {artifact_id} 未找到")

            artifact = self._artifacts[target_id]
            updated_fields = []

            # 创建一个包含当前数据的字典用于更新
            update_data = artifact.model_dump()
            update_data.update(data) # 应用传入的 data 覆盖

            # 从更新后的字典重新验证，确保类型和约束
            # 移除不允许修改的字段，防止验证错误
            update_data.pop('id', None)
            update_data.pop('created_at', None)

            # 创建一个临时副本进行验证，如果失败则不修改原始对象
            temp_artifact_data = artifact.model_copy(update=update_data).model_dump()

            # Pydantic v2: .model_copy(update=...) handles validation implicitly
            updated_artifact = artifact.model_copy(update=update_data)

            # 检查哪些字段实际发生了变化 (与原 artifact 对比)
            original_dump = artifact.model_dump()
            updated_dump = updated_artifact.model_dump()
            for key in updated_dump:
                 if key in original_dump and original_dump[key] != updated_dump[key]:
                      updated_fields.append(key)

            if not updated_fields:
                return success("资产未进行任何更新", artifact.model_dump(mode='json'))

            self._artifacts[target_id] = updated_artifact
            self._save_to_file()
            logger.info(f"资产 '{updated_artifact.title}' (ID: {artifact_id}) 更新了字段: {', '.join(updated_fields)}")
            return success("资产更新成功", updated_artifact.model_dump(mode='json'))
        except ValueError:
            return error(f"提供的 artifact_id '{artifact_id}' 不是有效的 UUID 格式")
        except ValidationError as ve:
            logger.error(f"更新资产 {artifact_id} 时验证失败: {ve}, data: {data}")
            return error(f"更新资产失败：输入数据验证错误 - {ve}")
        except Exception as e:
            logger.error(f"更新资产 {artifact_id} 时发生未知错误: {e}")
            return error(f"更新资产 {artifact_id} 时发生未知错误: {e}")

    # --- Public Tool Methods --- 

    def create_artifact(
        self,
        title: Annotated[str, "资产的标题"],
        content: Annotated[Any, "资产的内容"],
        author: Annotated[str, "创建资产的 Agent 或用户的标识"],
        tags: Annotated[Optional[List[str]], "关联的标签列表"] = None,
        artifact_id: Annotated[Optional[str], "可选：指定资产的 UUID 字符串"] = None
    ) -> ResponseType:
        """创建一个新的信息资产 (Artifact)。

        Args:
            title: 资产标题。
            content: 资产主体内容。
            author: 创建者标识。
            tags: 可选的标签列表。
            artifact_id: 可选，用于指定资产的 UUID。

        Returns:
            包含新创建资产信息的 ResponseType 字典。
        """
        data = {"title": title, "content": content, "author": author}
        if tags is not None:
            data["tags"] = tags
        # Reuse the internal _create logic
        return self._create(data=data, artifact_id=artifact_id)

    def get_artifact(
        self,
        artifact_id: Annotated[str, "要获取的资产的 UUID 字符串"]
    ) -> ResponseType:
        """获取指定 ID 的资产详情。

        Args:
            artifact_id: 目标资产的 UUID 字符串。

        Returns:
            包含资产信息的 ResponseType 字典。
        """
        # Reuse the internal _get logic
        return self._get(artifact_id=artifact_id)

    def list_artifacts(
        self,
        tags: Annotated[Optional[List[str]], "用于过滤的标签列表 (需要所有标签都匹配)"] = None,
        keywords: Annotated[Optional[str], "用于在标题和内容中搜索的关键字 (不区分大小写)"] = None
    ) -> ResponseType:
        """列出符合条件的资产。

        Args:
            tags: 可选，筛选包含所有指定标签的资产。
            keywords: 可选，筛选标题或内容中包含关键字的资产。

        Returns:
            包含符合条件的资产列表的 ResponseType 字典。
        """
        options = {}
        if tags is not None:
            options["tags"] = tags
        if keywords is not None:
            options["keywords"] = keywords
        # Reuse the internal _list logic
        return self._list(options=options if options else None)

    def update_artifact(
        self,
        artifact_id: Annotated[str, "要更新的资产的 UUID 字符串"],
        update_data: Annotated[Dict[str, Any], "包含要更新字段的字典 (例如 {'title': '新标题', 'tags': ['tag1']}) "]
    ) -> ResponseType:
        """更新指定 ID 资产的部分或全部字段。

        Args:
            artifact_id: 目标资产的 UUID 字符串。
            update_data: 包含要更新的字段和新值的字典。
                         可更新字段: title, content, tags, author。

        Returns:
            包含更新后资产信息的 ResponseType 字典。
        """
        if not update_data: # Basic check
             return error("更新资产时 'update_data' 不能为空字典")
        # Reuse the internal _update logic
        return self._update(artifact_id=artifact_id, data=update_data)

    def delete_artifact(
        self,
        artifact_id: Annotated[str, "要删除的资产的 UUID 字符串"]
    ) -> ResponseType:
        """删除指定 ID 的资产。

        Args:
            artifact_id: 目标资产的 UUID 字符串。

        Returns:
            确认删除消息的 ResponseType 字典。
        """
        # Reuse the internal _delete logic
        return self._delete(artifact_id=artifact_id)

    # --- Internal Methods (Keep or remove based on preference) ---
    # The logic is now duplicated between public and private, maybe refactor later
    # Or keep private methods if they offer different internal contracts

    def _create(self, data: Dict, artifact_id: Optional[str] = None) -> ResponseType:
        # ... (try block remains the same) ...
        try:
            # 如果提供了 artifact_id，尝试转换为 UUID
            if artifact_id:
                try:
                    data['id'] = UUID(artifact_id)
                except ValueError:
                    return error(f"提供的 artifact_id '{artifact_id}' 不是有效的 UUID 格式")

            # 使用 Pydantic 进行验证和创建
            new_artifact = Artifact.model_validate(data)

            if new_artifact.id in self._artifacts:
                return error(f"资产 ID {new_artifact.id} 已存在")

            self._artifacts[new_artifact.id] = new_artifact
            self._save_to_file()
            logger.info(f"资产 '{new_artifact.title}' (ID: {new_artifact.id}) 创建成功 by {new_artifact.author}")
            # 返回验证后的模型数据（字典格式）
            return success("资产创建成功", new_artifact.model_dump(mode='json'))
        # Corrected except blocks
        except ValidationError as ve:
            logger.error(f"创建资产时验证失败: {ve}, data: {data}")
            return error(f"创建资产失败：输入数据验证错误 - {ve}")
        except Exception as e:
            logger.error(f"创建资产时发生未知错误: {e}")
            return error(f"创建资产时发生未知错误: {e}")

    def _get(self, artifact_id: str) -> ResponseType:
        """内部方法：获取资产详情。"""
        try:
            target_id = UUID(artifact_id)
            artifact = self._artifacts.get(target_id)
            if not artifact:
                return error(f"资产 {artifact_id} 未找到")
            logger.info(f"获取资产 '{artifact.title}' (ID: {artifact_id})")
            return success("获取资产成功", artifact.model_dump(mode='json'))
        except ValueError:
             return error(f"提供的 artifact_id '{artifact_id}' 不是有效的 UUID 格式")

    def _list(self, options: Optional[Dict] = None) -> ResponseType:
        # ... (implementation as before) ...
        """内部方法：获取资产列表，支持过滤。"""
        results = list(self._artifacts.values())
        tags_filter: Optional[List[str]] = None
        keywords: Optional[str] = None

        if isinstance(options, dict):
            tags_filter = options.get("tags")
            keywords = options.get("keywords")
        elif options is not None:
            logger.warning(f"'options' 参数应为字典，但收到了 {type(options)} 类型，已忽略。")

        # Filter by tags
        if isinstance(tags_filter, list) and tags_filter:
            try:
                tag_set = set(map(str, tags_filter))
                results = [a for a in results if tag_set.issubset(set(a.tags))]
            except Exception as e:
                 logger.warning(f"处理 tags 过滤时出错: {e}, tags_filter: {tags_filter}")
        elif tags_filter is not None:
            logger.warning(f"list options: 'tags' 应为列表，但收到了 {type(tags_filter)} 类型，已忽略。")

        # Filter by keywords
        if isinstance(keywords, str) and keywords:
            kw = keywords.lower()
            filtered_results = []
            for a in results:
                match = False
                if kw in a.title.lower():
                    match = True
                elif isinstance(a.content, str) and kw in a.content.lower():
                    match = True
                if match:
                    filtered_results.append(a)
            results = filtered_results
        elif keywords is not None:
             logger.warning(f"list options: 'keywords' 应为字符串，但收到了 {type(keywords)} 类型，已忽略。")

        logger.info(f"列出 {len(results)} 个资产 (过滤条件: tags={tags_filter}, keywords={keywords})")
        return success("获取资产列表成功", [a.model_dump(mode='json') for a in results])

    def _delete(self, artifact_id: str) -> ResponseType:
        """内部方法：删除资产。"""
        try:
            target_id = UUID(artifact_id)
            if target_id not in self._artifacts:
                return error(f"资产 {artifact_id} 未找到")
            deleted_artifact_title = self._artifacts[target_id].title
            del self._artifacts[target_id]
            self._save_to_file()
            logger.info(f"资产 '{deleted_artifact_title}' (ID: {artifact_id}) 已删除")
            return success(f"资产 {artifact_id} 已删除")
        except ValueError:
            return error(f"提供的 artifact_id '{artifact_id}' 不是有效的 UUID 格式")

    def _update(self, artifact_id: str, data: Dict) -> ResponseType:
        """内部方法：更新资产。"""
        try:
            target_id = UUID(artifact_id)
            if not isinstance(data, dict):
                return error("更新资产时 'data' 必须是字典")
            if not data:
                return error("更新资产时 'data' 不能为空字典")
            if target_id not in self._artifacts:
                return error(f"资产 {artifact_id} 未找到")

            artifact = self._artifacts[target_id]
            updated_fields = []

            # 创建一个包含当前数据的字典用于更新
            update_data = artifact.model_dump()
            update_data.update(data) # 应用传入的 data 覆盖

            # 从更新后的字典重新验证，确保类型和约束
            # 移除不允许修改的字段，防止验证错误
            update_data.pop('id', None)
            update_data.pop('created_at', None)

            # 创建一个临时副本进行验证，如果失败则不修改原始对象
            temp_artifact_data = artifact.model_copy(update=update_data).model_dump()

            # Pydantic v2: .model_copy(update=...) handles validation implicitly
            updated_artifact = artifact.model_copy(update=update_data)

            # 检查哪些字段实际发生了变化 (与原 artifact 对比)
            original_dump = artifact.model_dump()
            updated_dump = updated_artifact.model_dump()
            for key in updated_dump:
                 if key in original_dump and original_dump[key] != updated_dump[key]:
                      updated_fields.append(key)

            if not updated_fields:
                return success("资产未进行任何更新", artifact.model_dump(mode='json'))

            self._artifacts[target_id] = updated_artifact
            self._save_to_file()
            logger.info(f"资产 '{updated_artifact.title}' (ID: {artifact_id}) 更新了字段: {', '.join(updated_fields)}")
            return success("资产更新成功", updated_artifact.model_dump(mode='json'))
        except ValueError:
            return error(f"提供的 artifact_id '{artifact_id}' 不是有效的 UUID 格式")
        except ValidationError as ve:
            logger.error(f"更新资产 {artifact_id} 时验证失败: {ve}, data: {data}")
            return error(f"更新资产失败：输入数据验证错误 - {ve}")
        except Exception as e:
            logger.error(f"更新资产 {artifact_id} 时发生未知错误: {e}")
            return error(f"更新资产 {artifact_id} 时发生未知错误: {e}")

    # Remove the old use_artifact method
    # def use_artifact(...): ...