# SAFE SOP 多智能体协作系统设计思路 (基于 AutoGen GraphFlow v0.5.6)

**文档版本:** 1.0
**日期:** 2025-05-04

## 1. 项目目标

构建一个基于 AutoGen 的多智能体系统（MAS），用于自动化执行 SAFE 应急响应标准操作规程（SOP）。该系统需要能够处理固定的 SOP 流程，并能在流程中动态地管理和执行由 LLM 生成的复杂任务子计划。

## 2. 背景与挑战

*   **SAFE SOP**: 一个结构化的、多阶段的应急响应流程，定义了不同阶段的目标、任务和负责角色（如 `config.yaml` 中所示）。
*   **两层计划结构**:
    *   **第一层 (固定)**: 宏观的 SOP 流程，包含预定义的阶段和主要任务分配。
    *   **第二层 (动态)**: SOP 中的某些任务可能比较复杂（非原子性），需要根据实时情况和上下文，由 LLM 动态分解成更细粒度的子任务（动态计划）。
*   **挑战**: 如何在多智能体框架中，既能严格遵循固定的 SOP 流程，又能灵活处理动态生成的子任务计划，并保证上下文的有效传递和管理。

## 3. 技术选型：GraphFlow vs. Swarm

经过讨论和分析 `config.yaml` 中体现的流程特点，我们决定采用 AutoGen **GraphFlow** 模式，而非 Swarm 或简单的 `RoundRobinGroupChat` / `SelectorGroupChat`。

*   **选择理由**:
    *   **结构化流程匹配**: SAFE SOP 本质上是一个有向图（步骤有明确的先后和依赖关系），与 GraphFlow 基于图的执行模型高度契合。
    *   **确定性控制**: 应急响应流程需要高确定性，GraphFlow 提供的精确流程控制优于 Swarm 的涌现式协作。
    *   **条件处理**: GraphFlow 支持基于条件的流程跳转，适合处理 SOP 中可能存在的决策点。
    *   **官方推荐**: GraphFlow 被推荐用于需要严格控制顺序、条件分支和处理复杂多步流程的场景。

## 4. 核心架构：以 Strategist 为中心的星型循环图 (Star-Shaped Loop GraphFlow)

为了解决"两层计划"的挑战，并规避动态创建嵌套 GraphFlow 的复杂性，我们采用以下架构：

*   **图结构**: 一个**固定**的星型图。
    *   **中心节点**: `Strategist` Agent。
    *   **外围节点**: `Awareness`, `FieldExpert`, `Executor` 等执行角色 Agent。
    *   **边**:
        *   `Strategist` <=> `Awareness`
        *   `Strategist` <=> `FieldExpert`
        *   `Strategist` <=> `Executor`
        *   (可能还有 `Strategist` <=> `Strategist` 的自循环边，用于内部状态更新或决策)

*   **工作模式**:
    *   `Strategist` 作为**绝对的控制中心和协调者**。
    *   `Strategist` 负责：
        *   理解初始任务，选择并加载对应的 SOP。
        *   **管理主 SOP 流程的推进**：按顺序触发 SOP 各阶段的任务。
        *   **处理动态计划**: 当遇到复杂的、非原子的 SOP 任务时，`Strategist` **内部** (可能通过调用 LLM 或规则) 将其分解为子任务。
        *   **任务分配**: 将主 SOP 任务或动态子任务，通过生成带有特定**路由条件**的消息，分配给相应的外围 Agent。
        *   **条件判断与流程控制**: 接收外围 Agent 的返回结果，判断下一步行动（分配下一个子任务、推进到 SOP 下一阶段、或结束流程）。
        *   **信息整合**: 汇总所有 Agent 的结果，维护全局状态。
    *   **外围 Agent** (`Awareness`, `FieldExpert`, `Executor`) 作为**执行者**：
        *   接收 `Strategist` 分配的具体任务指令。
        *   执行任务（调用工具、进行分析等）。
        *   **无条件地**将执行结果返回给 `Strategist`。
        *   它们之间**不直接交互**。

*   **条件路由**:
    *   **只有**从 `Strategist` 发出的边需要配置 `condition` (字符串类型)。
    *   `Strategist` 在分配任务时，其发出的消息内容或元数据中需要包含能触发对应 `condition` 的**路由标识符** (例如: `"route_to_Awareness"`, `"assign_task_2.1"`, `"request_expert_analysis"`)。
    *   从外围 Agent 返回 `Strategist` 的边**不需要** `condition`。

## 5. 上下文管理

*   GraphFlow **依赖 AutoGen 核心的共享消息历史**来传递上下文。
*   当一个 Agent 被激活时，它会收到**完整的、截至当前节点的共享消息历史**。
*   **关键**: 外围 Agent 的 **prompt** 需要精心设计，使其能够**聚焦处理 `Strategist` 最新下发的任务指令**，同时能从历史消息中获取必要的背景信息，避免信息过载。`Strategist` 也需要具备从完整历史中提取关键信息、管理不同层级计划上下文的能力。

## 6. 优势

*   **GraphFlow 实现简单**: 固定图结构易于构建和维护。
*   **动态性处理**: 将动态计划的复杂性内化到 `Strategist` 的智能中，避免了动态图的工程难题。
*   **控制集中**: 流程控制逻辑清晰，集中在 `Strategist`。
*   **符合 SOP 模式**: `Strategist` 的中心协调角色符合实际应急指挥模式。

## 7. 潜在挑战

*   **Strategist 复杂度高**: 对 `Strategist` 的 prompt 设计、状态管理、任务分解、决策逻辑要求非常高。
*   **中心化瓶颈**: 所有交互通过 `Strategist`，可能成为性能瓶颈。
*   **外围 Agent Prompt 设计**: 需要确保外围 Agent 能在完整历史中准确聚焦当前任务。

## 8. 初步开发计划

1.  **实现 GraphFlow 构建函数**: 创建一个 Python 函数，能够根据 `config.yaml`（或解析后的对象）生成所需的星型 GraphFlow 图结构 (`DiGraph`)。
2.  **Agent 实现 - Strategist**:
    *   重点设计其 Prompt，使其具备 SOP 流程管理、任务分解（识别复杂任务并生成子任务）、任务分配（生成带路由条件的消息）、结果整合和决策能力。
    *   实现其内部状态管理逻辑（跟踪 SOP 进度、子任务状态等）。
3.  **Agent 实现 - 外围 Agent**:
    *   设计其 Prompt，使其能接收 `Strategist` 的指令，聚焦执行，并清晰地返回结果。
    *   集成必要的工具（如搜索、PlanManager、ArtifactManager 等）。
4.  **定义消息格式/条件**: 确定 `Strategist` 用来路由的 `condition` 字符串格式，以及 Agent 间传递任务/结果的消息结构。
5.  **集成与测试**:
    *   编写集成测试，模拟完整的 SOP 执行流程。
    *   重点测试 `Strategist` 的调度逻辑和动态任务处理。
    *   逐步增加 SOP 复杂度和边界条件测试。
6.  **(可选) 工具函数**: 实现一个工具函数，供 `Strategist` 调用，用于基于自然语言描述动态生成子任务列表（如果需要 LLM 辅助分解）。

## 9. 总结

采用以 `Strategist` 为中心的**星型循环 GraphFlow** 架构，是平衡 SOP 结构化需求、动态任务处理复杂性以及当前 AutoGen GraphFlow 能力的一个务实方案。开发重点在于 `Strategist` Agent 的智能化设计和健壮性。 