import os
import pytest
from pathlib import Path
from datetime import datetime
from src.tools.artifact_manager import ArtifactManager
from src.tools.errors import ErrorMessages

@pytest.fixture
def temp_artifacts_dir(tmp_path):
    """创建临时制品目录"""
    artifacts_dir = tmp_path / "test_artifacts"
    artifacts_dir.mkdir()
    return artifacts_dir

@pytest.fixture
def artifact_manager(temp_artifacts_dir):
    """创建ArtifactManager实例"""
    return ArtifactManager(base_dir=temp_artifacts_dir)

@pytest.mark.asyncio
async def test_artifact_lifecycle(artifact_manager):
    """测试制品的完整生命周期：保存、加载、列表"""
    # 1. 基本保存
    content = "test content"
    name = "test_artifact"
    description = "Test description"
    save_result = await artifact_manager.save_artifact(
        content=content,
        name=name,
        description=description
    )
    assert save_result["status"] == "success"
    assert save_result["data"]["id"].endswith(".yaml")
    assert save_result["data"]["description"] == description
    artifact_id = save_result["data"]["id"]
    
    # 2. 加载制品
    load_result = await artifact_manager.load_artifact(artifact_id)
    assert load_result["status"] == "success"
    assert load_result["data"]["content"] == content
    assert load_result["data"]["description"] == description
    
    # 3. 保存第二个制品
    await artifact_manager.save_artifact(
        content="content2",
        name="artifact2",
        description="Second artifact"
    )
    
    # 4. 列出所有制品
    list_result = await artifact_manager.list_artifacts()
    assert list_result["status"] == "success"
    assert len(list_result["data"]) == 2
    # 验证列表中不包含内容字段
    for artifact in list_result["data"]:
        assert "content" not in artifact
        assert "description" in artifact

@pytest.mark.asyncio
async def test_artifact_with_event_id(artifact_manager):
    """测试带事件ID的制品管理"""
    # 1. 保存带事件ID的制品
    event_id = "event123"
    content = "test content"
    name = "test_artifact"
    
    save_result = await artifact_manager.save_artifact(
        content=content,
        name=name,
        event_id=event_id
    )
    assert save_result["status"] == "success"
    assert save_result["data"]["event_id"] == event_id
    assert "event123___test_artifact.yaml" in save_result["data"]["id"]
    
    # 2. 保存另一个不同事件的制品
    await artifact_manager.save_artifact(
        content="other content",
        name="other_artifact",
        event_id="event456"
    )
    
    # 3. 按事件ID列出制品
    list_result = await artifact_manager.list_artifacts(event_id=event_id)
    assert list_result["status"] == "success"
    assert len(list_result["data"]) == 1
    assert list_result["data"][0]["event_id"] == event_id
    
    # 4. 列出所有制品
    all_result = await artifact_manager.list_artifacts()
    assert all_result["status"] == "success"
    assert len(all_result["data"]) == 2

@pytest.mark.asyncio
async def test_artifact_error_cases(artifact_manager):
    """测试制品操作的错误情况"""
    # 1. 缺少必要参数
    missing_params_result = await artifact_manager.save_artifact(content="test")
    assert missing_params_result["status"] == "error"
    assert ErrorMessages.ARTIFACT_NAME_REQUIRED == missing_params_result["message"]
    
    # 2. 加载不存在的制品
    nonexistent_id = "nonexistent.yaml"
    nonexistent_result = await artifact_manager.load_artifact(nonexistent_id)
    assert nonexistent_result["status"] == "error"
    assert ErrorMessages.NOT_FOUND.format(resource="制品", id_str=nonexistent_id) == nonexistent_result["message"]
    
    # 3. 使用不支持的格式
    format_name = "json"
    invalid_format_result = await artifact_manager.save_artifact(
        content="test",
        name="test",
        preferred_format=format_name
    )
    assert invalid_format_result["status"] == "error"
    assert ErrorMessages.ARTIFACT_FORMAT_UNSUPPORTED.format(format=format_name) == invalid_format_result["message"]

@pytest.mark.asyncio
async def test_artifact_file_operations(artifact_manager, temp_artifacts_dir):
    """测试制品的文件操作"""
    # 1. 验证文件创建
    content = "test content"
    name = "test_artifact"
    save_result = await artifact_manager.save_artifact(
        content=content,
        name=name
    )
    assert save_result["status"] == "success"
    
    file_path = Path(temp_artifacts_dir) / save_result["data"]["id"]
    assert file_path.exists()
    assert file_path.is_file()
    
    # 2. 验证文件内容
    with open(file_path, "r", encoding="utf-8") as f:
        file_content = f.read()
        assert content in file_content
        assert name in file_content

def test_tool_list(artifact_manager):
    """测试工具列表完整性"""
    tools = artifact_manager.tool_list()
    expected_tools = {
        "save_artifact",
        "load_artifact",
        "list_artifacts"
    }
    assert set(tools) == expected_tools 