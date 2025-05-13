# SAFE 框架文档 README

本目录包含 SAFE (Strategist, Awareness, Field Expert, Executor) 多智能体框架（Multi-Agent Framework）的文档，该框架旨在使用多智能体框架辅助应急响应规划。

## 目录结构

- **`01_framework_overview.md`**: 提供 SAFE 框架的高层介绍，包括其目标、SOP 驱动方法以及所涉及的角色 (Agents)。
- **`02_implementation_details/`**: 包含框架实现和配置相关的技术细节。
  - **`01_prompting_guide.md`**: 为 SAFE 智能体 (Agents) 编写高效系统提示词 (System Prompts) 的指南和最佳实践。
  - **`02_agent_base_role_design.md`**: 关于 `AgentBaseRole` 抽象基类的技术设计文档，解释其特性以及如何处理任务执行和规划 (假定一个通用的智能体基类)。
  - **`03_plan_tool_spec.md`**: `Plan Tool` 的规范，用于管理顶层计划状态。
  - **`04_collaboration_action_spec.md`**: 通用协作请求 Action (`RequestCollaboration`) 的规范。
  - **`05_artifact_manager_tool_spec.md`**: 通用资产管理工具 (`ArtifactManager`) 的规范。
- **`03_contribution_guide/`**: 为希望为 SAFE 框架贡献代码的开发者提供信息。
  - **`01_contributing.md`**: 开发环境设置、编码规范、测试流程和贡献过程的指南。
  - **`02_development_roadmap.md`**: SAFE 框架未来的开发计划和路线图 (Roadmap)。

## 阅读顺序建议

若想大致了解框架，请从 `01_framework_overview.md` 开始阅读。

若需配置或扩展智能体，请参考 `02_implementation_details/` 目录下的文档。

若计划贡献代码，请查阅 `03_contribution_guide/` 目录下的指南。

## SAFE多智能体SOP系统工程开发实施计划

本计划基于`sop_workflow.md`的架构与实现思路，直接分解为可执行的工程开发任务，适用于SAFE多智能体SOP系统的落地推进。

### 1. 配置驱动与团队/流程定义
- 目标：实现基于config.yaml的团队、角色、SOP流程、工具链等全局配置。
- 关键点：配置schema设计、动态加载、热更新。
- 交付物：标准化config.yaml模板、配置解析模块。

### 2. 资产中心（Asset Hub）与结构化消息
- 目标：实现统一的结构化资产库，支持所有产出（报告、方案、评估等）集中管理与引用。
- 关键点：资产schema、唯一ID、版本管理、资产引用机制。
- 交付物：资产库模块、pydantic消息schema、资产管理API。

### 3. 流程图（GraphFlow）与自指机制
- 目标：根据配置自动生成多智能体流程图，支持自指Edge和多轮推理。
- 关键点：GraphFlow/DiGraphBuilder自动化、节点/边条件、Agent自指、终止判定。
- 交付物：流程图生成模块、流程可视化工具、流程配置示例。

### 4. Agent行为树/状态机与异步消息流
- 目标：每个Agent基于行为树/状态机实现决策逻辑，支持异步多轮消息处理。
- 关键点：on_messages_stream异步处理、行为树建模、工具注册与调用。
- 交付物：Agent基类、行为树/状态机实现、工具注册与调用示例。

### 5. 测试用例与集成验证
- 目标：用test_graph_flow.py、test_sop_flow.py等用例验证多轮推理、结构化消息流转、终止保护等核心能力。
- 关键点：高覆盖率、边界场景、异常保护、资产一致性。
- 交付物：pytest用例、集成测试报告。

### 6. 文档与开发同步
- 目标：所有实现与`sop_workflow.md`、配置、资产、接口文档保持同步。
- 关键点：自动化文档生成、开发-文档双向校验。
- 交付物：开发文档、用户手册、接口说明。

### 7. 工程推进建议
| 步骤 | 主要任务 | 关键技术 | 交付物 |
|------|----------|----------|--------|
| 1 | 配置驱动与解析 | schema设计、动态加载 | config.yaml、解析模块 |
| 2 | 资产中心实现 | 资产schema、版本管理 | 资产库、API |
| 3 | 流程图与自指 | GraphFlow自动化 | 流程生成模块 |
| 4 | Agent行为树 | on_messages_stream、行为树 | Agent基类/实现 |
| 5 | 测试用例开发 | pytest、集成测试 | 测试用例、报告 |
| 6 | 文档同步 | 自动化文档 | 用户/开发文档 |

---
本计划为SAFE多智能体SOP系统的工程实施蓝图，后续可根据实际进展和需求动态细化与调整。 