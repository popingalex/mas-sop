from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, List, Optional, Union, Literal
from pydantic import BaseModel
import json
from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString
import re

Format = Literal["yaml", "json"]
Mode = Literal["multi", "single"]

def sanitize_filename(index: str, name: Optional[str] = None) -> str:
    """
    生成合法文件名。index必须，name可选且只允许字母、数字、下划线。
    文件名格式：x.y_title.yaml 或 x.y.yaml
    """
    if name:
        name = name.strip().replace(" ", "_")
        name = re.sub(r'[^\w]', '', name)
        if name:
            return f"{index}_{name}"
    return index

class Storage(ABC):
    @abstractmethod
    def save(self, namespace: str, obj: BaseModel, index: str, name: Optional[str] = None): ...
    @abstractmethod
    def load(self, namespace: str, index: str) -> Optional[dict]: ...
    @abstractmethod
    def delete(self, namespace: str, index: str): ...
    @abstractmethod
    def list(self, namespace: str) -> List[dict]: ...

class FileStorage(Storage):
    def __init__(self, base_dir: Union[str, Path], format: Format = "yaml", mode: Mode = "multi"):
        self.base_dir = Path(base_dir)
        self.format = format
        self.mode = mode
        self.yaml = YAML(typ='rt')
        self.yaml.indent(mapping=2, sequence=4, offset=2)
        self.yaml.preserve_quotes = True
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_file_path(self, namespace: str, index: str, name: Optional[str] = None) -> Path:
        ns_dir = self.base_dir / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        ext = 'yaml' if self.format == 'yaml' else 'json'
        fname = sanitize_filename(index, name)
        return ns_dir / f"{fname}.{ext}"

    def _find_file_by_index(self, namespace: str, index: str) -> Optional[Path]:
        ns_dir = self.base_dir / namespace
        if not ns_dir.exists():
            return None
        ext = 'yaml' if self.format == 'yaml' else 'json'
        # 匹配 x.y.yaml 或 x.y_title.yaml，但不匹配 x.y.z.yaml
        pattern = re.compile(rf'^{re.escape(index)}(_[^.]*)?\.{ext}$')
        for file in ns_dir.iterdir():
            if file.is_file() and pattern.match(file.name):
                return file
        return None

    def _to_serializable(self, obj: Any) -> Any:
        from typing import TypedDict
        if isinstance(obj, BaseModel):
            return obj.model_dump(mode='json')
        elif isinstance(obj, dict):
            return {k: self._to_serializable(v) for k, v in obj.items()}
        elif isinstance(obj, (list, tuple)):
            return [self._to_serializable(i) for i in obj]
        # TypedDict本质是dict，已处理
        else:
            return obj

    def save(self, namespace: str, obj: Any, index: str, name: Optional[str] = None):
        file_path = self._get_file_path(namespace, index, name)
        data = self._to_serializable(obj)
        # 自动将多行description转为LiteralScalarString
        def convert_multiline(d, prefix="root"):
            if isinstance(d, dict):
                for k, v in d.items():
                    if k == 'description':
                        if not isinstance(v, str):
                            d[k] = str(v)
                        if isinstance(d[k], str) and '\n' in d[k]:
                            d[k] = LiteralScalarString(d[k])
                    if isinstance(v, dict):
                        convert_multiline(v, prefix=f"{prefix}.{k}")
                    elif isinstance(v, list):
                        for idx, item in enumerate(v):
                            if isinstance(item, dict):
                                convert_multiline(item, prefix=f"{prefix}.{k}[{idx}]")
        convert_multiline(data)
        if self.format == 'yaml':
            with open(file_path, 'w', encoding='utf-8') as f:
                self.yaml.dump(data, f)
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, namespace: str, index: str) -> Optional[dict]:
        file_path = self._find_file_by_index(namespace, index)
        if not file_path or not file_path.exists():
            return None
        if self.format == 'yaml':
            with open(file_path, 'r', encoding='utf-8') as f:
                return self.yaml.load(f)
        else:
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)

    def delete(self, namespace: str, index: str):
        file_path = self._find_file_by_index(namespace, index)
        if file_path and file_path.exists():
            file_path.unlink()

    def list(self, namespace: str) -> List[dict]:
        ns_dir = self.base_dir / namespace
        if not ns_dir.exists():
            return []
        ext = 'yaml' if self.format == 'yaml' else 'json'
        result = []
        for file in ns_dir.glob(f"*.{ext}"):
            if self.format == 'yaml':
                with open(file, 'r', encoding='utf-8') as f:
                    result.append(self.yaml.load(f))
            else:
                with open(file, 'r', encoding='utf-8') as f:
                    result.append(json.load(f))
        return result

class DumbStorage(Storage):
    def save(self, namespace: str, obj: Any, index: str, name: Optional[str] = None):
        pass
    def load(self, namespace: str, index: str) -> Optional[dict]:
        return None
    def delete(self, namespace: str, index: str):
        pass
    def list(self, namespace: str) -> List[dict]:
        return []

def normalize_id(index: str, name: str = "") -> str:
    """
    生成合法的id，格式为：序号_名称（只保留字母、数字、下划线、短横线），如果名称无效则只用序号。
    """
    name = name.strip().replace(" ", "_")
    name = re.sub(r'[^\w\-]', '', name)
    if name:
        return f"{index}_{name}"
    return str(index) 