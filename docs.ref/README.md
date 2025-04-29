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