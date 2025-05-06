import os
import pytest
from pathlib import Path
from src.tools.artifact_manager import ArtifactManager
from uuid import UUID

def make_manager(tmp_path, mode, fmt):
    return ArtifactManager(base_dir=tmp_path, storage_mode=mode, storage_format=fmt)

@pytest.mark.parametrize("mode,fmt", [
    ("single", "yaml"),
    ("single", "json"),
    ("multi", "yaml"),
    ("multi", "json"),
])
def test_artifact_lifecycle(tmp_path, mode, fmt):
    manager = make_manager(tmp_path, mode, fmt)
    # 创建
    r = manager.create_artifact(title="t1", content="c1", author="a1", tags=["x"])
    assert r["success"]
    aid = r["data"]["id"]
    # 获取
    r2 = manager.get_artifact(str(aid))
    assert r2["success"]
    assert r2["data"]["title"] == "t1"
    # 列表
    r3 = manager.list_artifacts()
    assert r3["success"]
    assert any(a["id"] == aid for a in r3["data"])
    # 更新
    r4 = manager.update_artifact(str(aid), {"title": "t2", "tags": ["y"]})
    assert r4["success"]
    assert r4["data"]["title"] == "t2"
    # 删除
    r5 = manager.delete_artifact(str(aid))
    assert r5["success"]
    r6 = manager.get_artifact(str(aid))
    assert not r6["success"]

def test_artifact_import_export(tmp_path):
    manager = make_manager(tmp_path, "single", "yaml")
    # 创建并导出
    r = manager.create_artifact(title="t1", content="c1", author="a1")
    aid = r["data"]["id"]
    export_path = tmp_path / "exported.yaml"
    r2 = manager.export_artifact_to_file(str(aid), str(export_path))
    assert r2["success"]
    # 导入到新manager
    manager2 = make_manager(tmp_path, "multi", "json")
    r3 = manager2.import_artifact_from_file(str(export_path))
    assert r3["success"]
    # 能查到
    aid2 = r3["data"]["id"]
    r4 = manager2.get_artifact(str(aid2))
    assert r4["success"]

def test_artifact_filter(tmp_path):
    manager = make_manager(tmp_path, "single", "yaml")
    manager.create_artifact(title="foo", content="bar", author="a", tags=["x", "y"])
    manager.create_artifact(title="baz", content="qux", author="a", tags=["y"])
    # tag过滤
    r = manager.list_artifacts(tags=["x"])
    assert r["success"] and len(r["data"]) == 1
    # 关键字过滤
    r2 = manager.list_artifacts(keywords="baz")
    assert r2["success"] and len(r2["data"]) == 1

def test_artifact_error_cases(tmp_path):
    manager = make_manager(tmp_path, "single", "yaml")
    # 缺少必要参数
    r = manager.create_artifact(title="", content="", author="")
    assert not r["success"]
    # 不存在
    fake_id = str(UUID(int=1))
    r2 = manager.get_artifact(fake_id)
    assert not r2["success"]
    # 更新不存在
    r3 = manager.update_artifact(fake_id, {"title": "x"})
    assert not r3["success"]
    # 删除不存在
    r4 = manager.delete_artifact(fake_id)
    assert not r4["success"]

def test_tool_list(tmp_path):
    manager = make_manager(tmp_path, "single", "yaml")
    tools = manager.tool_list()
    expected = {"create_artifact", "get_artifact", "list_artifacts", "update_artifact", "delete_artifact", "import_artifact_from_file", "export_artifact_to_file"}
    assert set(tools) == expected 