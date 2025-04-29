# Executor Agent 规范 v1.0

## 1. 概述

`Executor` Agent 是 SAFE 框架（或类似采用规划-执行分离模式的框架）中的一个特殊智能体角色。其核心职责是充当内部规划决策（由 Strategist 等角色完成并体现在最终的 `FinalResponsePlan` 中）与外部执行验证环境 (Execution Verification Environment, EVE) 之间的桥梁。

Executor 负责将高层级的行动计划**转译**为 EVE 可以理解和执行的指令，**驱动** EVE 运行模拟，并**获取和处理**模拟执行的结果，为计划的有效性提供初步验证。

该规范旨在定义 Executor Agent 的核心功能、行为和所需能力，保持框架无关性。

## 2. 核心目标与定位

*   **计划转译 (Plan Translation)**: 将抽象的行动方案/计划转换为具体的、可由 EVE 执行的指令序列或配置。
*   **模拟驱动 (Simulation Driving)**: 负责启动、控制和监控 EVE 的模拟执行过程。
*   **结果获取与报告 (Result Fetching & Reporting)**: 从 EVE 收集执行日志和关键结果指标，并将其格式化为结构化的报告 (如 `ExecutionLogReport`)。
*   **接口抽象 (Interface Abstraction)**: 作为规划层和执行验证层之间的清晰接口，隔离两者的复杂性。
*   **验证而非执行 (Verification, Not Real Execution)**: 其目标是**模拟验证**计划，而非进行真实的物理干预。

## 3. 核心职责与工作流程 (对应 SOP-05)

Executor Agent 主要在框架定义的执行验证阶段被激活，其典型工作流程如下：

1.  **接收任务**: 从驱动智能体 (如 Strategist) 接收执行模拟验证的任务，通常输入是最终确定的应急处置计划 (`FinalResponsePlan`) 的引用或内容。
2.  **加载计划**: 从 `ArtifactManager` 加载 `FinalResponsePlan`。
3.  **计划转译**: 调用内部能力 (例如 `TranslatePlanToEVECommands` Action) 将计划内容转译为 EVE 指令序列。
4.  **驱动模拟**: 调用内部能力 (例如 `DriveEVESimulation` Action)，该能力负责：
    *   初始化和配置 EVE（通过 EVE 接口）。
    *   将转译后的指令发送给 EVE 执行。
    *   根据需要监控 EVE 状态或等待其完成。
5.  **获取结果**: 模拟结束后，调用内部能力 (例如 `FetchEVEResults` Action) 从 EVE 获取执行日志和结果数据。
6.  **处理与存储结果**: 对获取的原始结果进行处理和格式化，生成 `ExecutionLogReport`。
7.  **存储报告**: 调用 `ArtifactManager` 的 `save` 方法存储 `ExecutionLogReport`。
8.  **更新状态**: 调用 `Plan Tool` 的 `update_task_status` 方法，标记 SOP-05 任务完成。
9.  **通知完成**: (可选) 向驱动智能体发送消息，通知模拟执行完成。

## 4. 所需能力 (Actions & Tools)

Executor Agent 需要具备以下核心能力 (以 Actions 形式定义) 和访问的工具 (Tools)：

*   **Actions**: (具体实现可能依赖 LLM 或专用逻辑)
    *   `TranslatePlanToEVECommands`: 输入计划内容，输出 EVE 指令序列。
    *   `DriveEVESimulation`: 输入 EVE 指令序列，负责与 EVE 接口交互以执行模拟。
    *   `FetchEVEResults`: 与 EVE 接口交互以获取结果。
    *   `ProcessEVEResults`: 处理原始结果，生成结构化报告。
*   **Tools**: (由框架提供)
    *   `Plan Tool`: 用于更新任务状态。
    *   `ArtifactManager`: 用于加载计划和存储结果报告。

## 5. 与 EVE 的交互接口 (抽象)

Executor 的功能高度依赖于其对接的 EVE。为了保持 Executor 规范的通用性，我们**不在此定义具体的 EVE API**，而是假定存在一个**抽象的 EVE 接口层**，Executor 的 `DriveEVESimulation` 和 `FetchEVEResults` Action 通过这个抽象层与具体的 EVE 实现交互。这个抽象接口层可能需要提供类似以下的功能：

*   `setup_environment(config: dict)`: 配置模拟环境。
*   `execute_command(command: dict)`: 执行单条指令。
*   `run_simulation(command_sequence: list)`: 执行完整的指令序列。
*   `get_status() -> str`: 获取当前模拟状态。
*   `get_logs() -> list`: 获取执行日志。
*   `get_results() -> dict`: 获取关键结果指标。

**(建议：创建一个单独的 `07_eve_interface_spec.md` 来详细定义这个抽象接口)**

## 6. 实现说明

*   **转译逻辑**: `TranslatePlanToEVECommands` 是核心，可能需要利用 LLM 的理解和转换能力，或基于规则的解析器。
*   **EVE 适配**: `DriveEVESimulation` 和 `FetchEVEResults` 的具体实现需要适配目标 EVE 的实际接口。
*   **无领域知识**: Executor 本身应尽可能少地包含应急领域的专业知识，专注于接口转换和流程驱动。

## 7. 待讨论问题

*   行动计划 (`FinalResponsePlan`) 的标准化格式，以便于转译。
*   EVE 指令集的标准化程度。
*   如何处理模拟执行过程中的错误和中断？
*   Executor 是否需要支持并发执行多个模拟？

--- 