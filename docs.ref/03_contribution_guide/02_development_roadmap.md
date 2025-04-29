# SAFE 框架开发路线图 (Roadmap) v1.0

## 1. 愿景

SAFE 框架的目标是成为一个健壮、灵活且可扩展的平台，用于构建基于 SOP (Standard Operating Procedures, 标准操作规程) 的多智能体系统 (Multi-Agent Systems, MAS)，专门用于复杂场景下的应急响应规划辅助。我们旨在创建一个能够让领域专家轻松配置、模拟和评估应急预案的工具。

## 2. 当前状态 (截至 v1.0 设计阶段)

*   定义了 SAFE 核心角色 (Strategist, Awareness, Field Expert, Executor)。
*   设计了基于 `team.yaml` 的 SOP 驱动工作流配置模式。
*   提出了 `SafeBaseRole` 作为抽象基类，用于处理任务执行和内部复杂任务规划。
*   制定了提示词工程指南 (`01_prompting_guide.md`)。
*   建立了初步的贡献指南 (`01_contributing.md`)。

## 3. 近期目标 (Short-Term Goals, 未来 1-3 个月)

*   **核心实现 (Core Implementation)**:
    *   **`SafeBaseRole` 实现**: 实现 `02_base_role_design.md` 中描述的核心逻辑，包括复杂度评估、内部规划调用、计划日志记录和简单/复杂任务执行路径。
    *   **`PlanManager` (或等效机制) 实现**: 创建或集成一个组件，用于加载 `team.yaml` 中的全局工作流，实例化 `OverallPlan`，跟踪任务状态，并将任务分配给指定的智能体。
    *   **`ArtifactManager` (或等效机制) 实现**: 创建或集成一个组件，用于存储和检索由智能体生成或使用的信息资产 (Assets)，支持标准资产名称。
    *   **基础角色实现**: 实现 `Strategist`, `Awareness`, `Field Expert`, `Executor` 的 Python 类，继承自 `SafeBaseRole`，并包含其特定的 `actions` 和 `tools` 引用。
*   **基础动作/工具 (Basic Actions/Tools)**:
    *   **信息检索工具 (Information Retriever Tool)**: 实现一个基础工具，允许智能体从模拟的知识库或文档集中检索信息。
    *   **简单分析动作 (Simple Analysis Actions)**: 为 `Awareness` 和 `Field Expert` 实现基础的基于 LLM 的分析动作 (例如, `AnalyzeSituation`, `AssessRiskLevel`)。
    *   **计划更新/查询动作 (Plan Update/Query Actions)**: 实现与 `PlanManager` 交互的动作 (例如, `UpdateTaskStatus`, `GetNextTask`)。
    *   **资产操作动作 (Asset Handling Actions)**: 实现与 `ArtifactManager` 交互的动作 (例如, `StoreReport`, `RetrieveMapData`)。
*   **端到端测试 (End-to-End Testing)**:
    *   创建一个简单的 SOP (`team.yaml`) 和场景，用于测试框架的基本端到端流程。
    *   开发基础的测试脚本 (`pytest`)，验证任务是否按预期分配、执行和完成。

## 4. 中期目标 (Mid-Term Goals, 未来 3-6 个月)

*   **增强的智能体能力 (Enhanced Agent Capabilities)**:
    *   **领域特定工具 (Domain-Specific Tools)**: 为 `Field Expert` 开发更具体的工具（例如，化学品属性查询、资源调度模拟接口）。
    *   **执行器仿真接口 (Executor Simulation Interface)**: 实现 `Executor` 与模拟环境 (例如, EVE NG, 或自定义仿真器) 交互的工具或动作。
    *   **高级分析动作 (Advanced Analysis Actions)**: 开发更复杂的 LLM 驱动分析动作，可能涉及多轮思考或结构化输出。
*   **工作流与规划 (Workflow & Planning)**:
    *   **动态调整 (Dynamic Adaptation)**: 探索允许 `Strategist` 根据实时情况有限度地调整 `OverallPlan` 的机制。
    *   **子流程支持 (Sub-workflow Support)**: 考虑如何在 `team.yaml` 或智能体内部更明确地支持和管理 SOP 子流程。
    *   **规划健壮性 (Planning Robustness)**: 改进 `SafeBaseRole` 的内部规划逻辑，使其能处理更复杂的依赖关系和失败情况。
*   **评估与可视化 (Evaluation & Visualization)**: (TBD - 待定)
    *   定义评估 SAFE 团队绩效的指标 (Metrics) (例如，计划完成时间、资源利用率、风险降低程度)。
    *   探索可视化 `OverallPlan` 执行进度和智能体交互的方法。
*   **文档与示例 (Documentation & Examples)**:
    *   提供更多关于如何配置 `team.yaml` 以适应不同 SOP 的示例。
    *   完善开发者文档，包括 `Action` 和 `Tool` 的 API 参考。

## 5. 长期目标 (Long-Term Goals, 未来 6+ 个月)

*   **人机交互 (Human-in-the-Loop)**:
    *   实现允许人类用户审查计划、提供反馈或接管特定任务的机制 (例如, `SafeBaseRole.request_assistance`)。
*   **多团队协调 (Multi-Team Coordination)**: (探索性)
    *   研究支持多个 SAFE 团队（可能专注于不同方面）协同工作的架构。
*   **自适应学习 (Adaptive Learning)**: (研究性)
    *   探索让智能体根据过去的模拟结果或反馈调整其行为或规划策略的方法。
*   **更广泛的集成 (Broader Integration)**:
    *   与其他应急管理平台或数据源集成。
*   **社区与生态 (Community & Ecosystem)**:
    *   建立一个活跃的贡献者社区。
    *   鼓励开发特定领域的 SAFE 扩展或插件。

## 6. 如何贡献

如果您对路线图中的任何项目感兴趣，请查看 `01_contributing.md` 中的贡献流程，并在相关的 GitHub 议题 (Issues) 中开始讨论！我们欢迎各种形式的帮助。 