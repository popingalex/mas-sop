# 通用资产管理工具 (`ArtifactManager`) 规范 v1.1

## 1. 概述

`ArtifactManager Tool` 是一个为多智能体框架设计的通用工具。其核心职责是提供一个标准化的接口，用于在指定的工作空间内**存储和检索信息资产 (Artifacts)**，这些资产通常是智能体在执行任务过程中产生或消耗的文件（如报告、数据文件、代码等）。

该工具旨在提供可靠的文件系统操作接口，其具体后端实现可以多样化 (例如，可以基于标准库 `pathlib`、`shutil`，或参考其他现有库，但接口本身保持通用)。

## 2. 核心概念

*   **工作空间 (Workspace)**: 执行任务的根目录。
*   **资产 (Artifact)**: 指智能体处理的任何信息单元，通常以文件形式存储。需要定义一个通用的**资产数据结构**来表示，至少包含资产的逻辑**名称/标识符 (Identifier/Name)** 和**内容 (Content)**，并可能包含存储路径信息。
*   **资产存储 (Artifact Storage)**: 底层的文件系统或存储机制。

## 3. 数据结构 (概念性)

需要定义一个通用的资产表示方式。

```python
# --- 概念性数据结构 (示例) ---
from typing import Optional

class Artifact:
    identifier: str # 逻辑名称或标识符，例如 "results/report.txt"
    content: bytes | str # 文件内容
    # 可选：物理存储路径等元数据
    physical_path: Optional[str] = None

```

## 4. API 方法定义

`ArtifactManager` 应提供以下核心方法供智能体调用：

*   **`save(artifact: Artifact) -> bool`**
    *   **描述**: 将提供的资产内容保存到工作空间内的指定逻辑路径 (由 `artifact.identifier` 定义)。如果目录不存在，应尝试创建。
    *   **参数**: `artifact` (包含 `identifier` 和 `content` 的对象)。
    *   **返回**: 保存成功返回 `True`，失败返回 `False`。
    *   **逻辑**: 将 `artifact.identifier` 映射到工作空间内的物理路径，并将 `artifact.content` 写入该路径。处理可能的 IO 错误。

*   **`load(identifier: str, expected_type: type = str) -> Optional[Artifact]`**
    *   **描述**: 从工作空间加载指定逻辑标识符的资产内容。
    *   **参数**: `identifier` (资产的逻辑名称/路径), `expected_type` (可选，指定期望的内容类型，如 `str` 或 `bytes`，默认为 `str`)。
    *   **返回**: 包含 `identifier` 和加载的 `content` 的 `Artifact` 对象，如果文件不存在或无法读取则返回 `None`。
    *   **逻辑**: 将 `identifier` 映射到物理路径，读取文件内容，根据 `expected_type` 进行解码 (如果是文本)，构建并返回 `Artifact` 对象。处理 IO 错误和解码错误。

*   **`list(directory_identifier: str = ".") -> List[str]`**
    *   **描述**: 列出指定逻辑目录下的资产标识符 (文件和子目录名)。
    *   **参数**: `directory_identifier` (要列出的目录的逻辑路径，默认为工作空间根目录)。
    *   **返回**: 目录下的标识符列表。
    *   **逻辑**: 将 `directory_identifier` 映射到物理路径，列出该目录内容。处理路径不存在等错误。

*   **(可选) `delete(identifier: str) -> bool`**
    *   **描述**: 删除指定逻辑标识符的资产。
    *   **参数**: `identifier`。
    *   **返回**: 删除成功返回 `True`。

## 5. 实现说明

*   **工作空间**: 需要明确如何确定和配置工作空间的根目录。
*   **路径映射**: 需要实现逻辑标识符 (`identifier`) 到物理文件系统路径的转换逻辑。
*   **错误处理**: 必须健壮地处理文件不存在、权限不足、IO 错误等。
*   **并发**: 如果框架支持并发，需要考虑文件操作的原子性或加锁。
*   **调用接口**: `ArtifactManager` 的功能应通过框架提供的标准机制暴露给智能体调用。

## 6. 待讨论问题

*   资产标识符 (`identifier`) 的具体格式和规范？是否支持相对/绝对路径？
*   错误处理的具体策略？返回 `False` 还是抛出异常？
*   大文件处理策略？流式读写？
*   版本控制或历史记录是否需要（Phase 1 可能不需要）？

--- 