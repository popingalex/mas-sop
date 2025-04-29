# 团队配置规范 v1.0

## 1. 概述

本文档定义了用于配置多智能体团队（特别是在 SAFE 框架或类似模式下）的文件格式和解析逻辑。配置文件旨在以声明方式定义团队的组成、每个智能体的角色、特定配置以及它们可以使用的工具/能力。

目标是提供一种清晰、可读且与具体框架实现细节解耦的方式来设置和启动多智能体协作任务。

## 2. 配置格式

推荐使用 **YAML** 格式，因其具有良好的可读性和对复杂结构的支持。

## 3. 示例配置文件 (`team_config_example.yaml`)

```yaml
# 示例：SAFE 应急响应团队配置
version: 1.0
team_name: EmergencyResponseTeam_Alpha

global_settings:
  # 可选：全局默认设置，可被单个智能体覆盖
  default_llm_config: 
    model: "gpt-4" 
    temperature: 0.7
    # ... 其他 LLM 参数
  shared_tools:
    # 默认所有智能体都能访问的工具类名或标识符
    - PlanTool
    - ArtifactManager

agents:
  # 团队成员列表
  - name: Strategist_01 
    role_class: "safe_framework.roles.Strategist" # 引用智能体角色的 Python 类路径或注册名
    role_config:
      # 传递给角色类构造函数 __init__ 的特定参数
      instructions: "根据事件报告制定高层应急响应计划。优先考虑人员安全和关键基础设施保护。"
      llm_config: # 覆盖全局 LLM 配置
        model: "gpt-4-turbo" 
        max_tokens: 2000
    assigned_tools: # 该智能体特有的或需要显式分配的工具
      - CollaborationAction 

  - name: Awareness_Sensor_Analyst
    role_class: "safe_framework.roles.Awareness"
    role_config:
      sensor_types_to_monitor: ["traffic_cameras", "weather_feeds", "social_media_keywords"]
      alert_threshold: 0.8 # 示例：特定配置参数
      instructions: "监控指定传感器数据，识别关键事件模式，提供态势感知更新。"
    assigned_tools:
      # 可能需要特定的数据查询工具
      - SensorDataQueryTool 

  - name: Field_Expert_FireSafety
    role_class: "safe_framework.roles.FieldExpert"
    role_config:
      expertise_area: "Fire Safety and Suppression"
      instructions: "基于态势更新和初步计划，就火灾相关事件提供专业建议和可行性评估。"
      # 该角色可能不需要特定的 LLM 配置，使用全局默认

  - name: Executor_SimRunner
    role_class: "safe_framework.roles.Executor"
    role_config:
      eve_interface_config: # Executor 特有的 EVE 接口配置
        type: "StandardEVE_v1" # 指向具体的 EVE 适配器类型
        endpoint: "http://localhost:8080/eve_api" # EVE 服务地址
      instructions: "接收最终计划，将其转换为模拟指令，在 EVE 中执行并报告结果。"
    # Executor 可能不需要访问 shared_tools，其功能通过内部 Actions 和 EVE 交互实现
    # 但它仍需 ArtifactManager (加载计划/存报告) 和 PlanTool (更新状态)，若未共享则需在此分配

# 可以添加其他顶层配置，如工作流定义、全局消息总线配置等
```

## 4. 解析与初始化逻辑

框架在启动时应包含一个加载器 (Loader) 组件，负责解析此配置文件并初始化团队：

1.  **读取文件**: 加载器读取指定的 YAML 配置文件。
2.  **解析全局设置**: 处理 `global_settings`，准备好默认配置和共享工具列表。
3.  **遍历 Agents**: 迭代 `agents` 列表中的每个智能体定义。
4.  **解析 Agent 定义**: 对于每个定义：
    *   获取 `name`, `role_class`, `role_config`, 和 `assigned_tools`。
    *   **类解析**: 将 `role_class` 字符串解析为实际的 Python 类对象（可能通过动态导入或预先注册的映射）。
    *   **工具解析**: 解析 `assigned_tools` 和 `shared_tools`，准备好要注入给智能体的工具实例或引用。注意处理工具的依赖和初始化。
    *   **配置合并**: （可选）如果提供了 `role_config` 中的 `llm_config`，则覆盖全局默认 `llm_config`。将最终的配置字典准备好。
    *   **实例化**: 调用解析出的 `role_class` 的构造函数 (`__init__`)，传入 `name`、合并后的 `role_config` 以及解析后的工具实例列表。
    *   **注册/管理**: 将实例化的智能体对象添加到框架的内部管理结构中（例如，一个智能体注册表或列表），以便后续进行消息路由、任务分配等。
5.  **完成初始化**: 所有智能体实例化并注册后，团队初始化完成，可以开始接收外部输入或执行预定工作流。

## 5. 关键配置字段说明

*   `version`: 配置文件的版本号，用于兼容性管理。
*   `team_name`: 团队的描述性名称。
*   `global_settings`:
    *   `default_llm_config`: 为所有智能体提供的默认 LLM 配置。
    *   `shared_tools`: 默认情况下所有智能体都可以访问的工具列表。
*   `agents`: 一个列表，包含团队中每个智能体的定义。
    *   `name`: 智能体的唯一标识符/名称。
    *   `role_class`: 指向实现该智能体角色的 Python 类。这通常是类的完全限定路径字符串，或者是在框架中注册的别名。
    *   `role_config`: 一个字典，包含传递给智能体类构造函数的特定配置参数。其结构完全取决于对应的 `role_class` 如何定义其 `__init__` 方法。
    *   `assigned_tools`: （可选）显式分配给该智能体的工具列表，会与 `shared_tools` 合并（具体合并策略由框架决定，例如覆盖或追加）。

## 6. 框架无关性

虽然示例中的类路径 (`safe_framework.roles.*`) 是具体的，但配置结构本身是通用的。不同的多智能体框架可以通过实现自己的加载器来解析这种结构，并将 `role_class` 和 `assigned_tools` 映射到它们各自的智能体实现和工具管理机制上。关键在于约定配置文件的结构和字段含义。

--- 