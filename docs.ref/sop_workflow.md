# SAFE SOP 多智能体系统实现原理与工作流（新版）

## 1. 引言

本文档阐述 SAFE (Simulation and Agent Framework for Emergencies) 框架中，基于标准化操作规程 (SOP) 的多智能体团队的最新实现原理和工作流程。新版架构统一了执行者智能体（SOPAgent），引入了 QuickThink 机制，并将原 NexusAgent 更名为 SOPManager，使系统结构更简洁、职责更清晰、扩展性更强。

## 2. 系统总体架构与设计哲学

### 2.1 统一的中心化流程图架构（Hub-and-Spoke `GraphFlow` Model）

- **中心节点（SOPManager）**：唯一的流程协调者，负责 SOP 计划的创建、推进、任务分派和流程终止。
- **执行节点（SOPAgent）**：统一的任务执行者，具备任务理解、快速思考（QuickThink）、自我分解、计划执行等能力。**所有角色（如 Strategist、Awareness、FieldExpert、Executor 等）均为 SOPAgent 的实例，具体角色由配置文件驱动，框架代码对角色类型保持无感知。**
- **终止节点（StopAgent）**：流程终点。
- **消息驱动与路由**：所有 Agent 间协作通过异步消息传递和 GraphFlow 路由实现，流程控制权集中于 SOPManager。

### 2.2 配置驱动设计

- 团队定义、Agent 配置、SOP 工作流模板、GraphFlow 路由规则等均由配置文件（如 `config.yaml`）驱动。
- 通过调整配置文件即可灵活适配不同 SOP 流程、团队构成和 Agent 行为，无需修改核心代码。
- **每个执行角色（如 Strategist、Awareness 等）都只是 SOPAgent 的一个实例，角色名称和分工完全由配置文件决定，框架代码不感知具体角色类型。**

## 3. 核心组件与机制

### 3.1 智能体（Agents）

#### 3.1.1 SOPManager（原 NexusAgent）
- **职责**：
  - 接收用户任务，调用 Judge 工具判断任务类型。
  - 选择/创建 SOP 计划，推进计划步骤。
  - 分派任务给 SOPAgent。
  - 跟踪任务进度，判断流程结束。
- **分派任务实现要点**：
  - 分派消息必须带全 plan_id、plan_title、step_id、step_name、task_id、task_name、description 等所有定位信息。
  - 分派逻辑为"逐个分派所有未完成 task"，每次推进都查找所有 step 下的第一个未完成 task。
  - 不能只分派 step 下第一个 task，也不能只看 step.status，否则会导致后续 task 未被自动推进。
- **工具注册**：仅注册 PlanManager 相关工具。
- **交互**：只与 SOPAgent、StopAgent 进行消息交互。

#### 3.1.2 SOPAgent（统一执行者，吸收原 LeafAgent 功能）
- **职责**：
  - 接收任务，调用 QuickThink 进行任务类型判断和前置分析。
  - 若为复杂任务可自我分解，调用 Plan/Artifact 工具。
  - 执行任务，产出结果，反馈给 SOPManager。
- **QuickThink 机制**：
  - SOPAgent 内部实现 quick_think 方法，在 on_messages_stream 首先调用。
  - QuickThink 可调用 Judge 工具、分析任务、决定是否需要分解/计划。
- **工具注册**：注册 Judge、Plan、Artifact 等工具。
- **所有执行角色（如 Strategist、Awareness、FieldExpert、Executor 等）均为 SOPAgent 的实例，角色名称和分工由配置文件决定，框架代码不感知具体角色类型。**

#### 3.1.3 StopAgent
- **职责**：流程终点，标记流程成功结束。

### 3.2 计划管理与资产管理

- **PlanManager**：以工具集形式供 SOPManager/SOPAgent 调用，实现计划的创建、查询、步骤推进与状态更新。计划工具能唯一定位到具体的 plan/step/task。
- **ArtifactManager**：管理和共享流程中产生的结构化信息资产，提升信息流转效率。

### 3.3 工具注册与调用

- **SOPAgent**：注册 Judge（任务类型判断）、Plan（计划管理）、Artifact（资产管理）等工具。
- **SOPManager**：注册 PlanManager 相关工具。
- 工具名与调用方式需保持一致，避免命名混乱。

## 4. 主要流程与 QuickThink 机制

### 4.1 SOPManager 主流程
1. 接收用户任务。
2. 调用 Judge 工具判断任务类型。
3. 若为 PLAN 类型，选择/创建 SOP 计划，推进计划步骤。
4. 分派任务给 SOPAgent。**分派时带全 plan/step/task 的所有 id 和关键信息，逐个分派所有未完成 task。**
5. 跟踪任务进度，所有步骤和任务完成后通知 StopAgent。

### 4.2 SOPAgent 执行流程
1. 接收任务，首先调用 quick_think 进行任务类型判断和前置分析。
2. 若任务复杂可自我分解，调用 Plan/Artifact 工具。
3. 执行任务，产出结果。
4. 反馈结果给 SOPManager。

### 4.3 QuickThink 机制
- SOPAgent 内部 quick_think 方法可调用 Judge 工具，分析任务类型。
- 根据分析结果决定是否需要分解任务、生成子计划或直接执行。
- 提升任务处理的智能性和灵活性。

## 5. 配置驱动的灵活性

- SOP 流程定义、Agent 行为、团队构成均可通过配置文件灵活调整。
- 支持多种 SOP 模板、不同团队规模和角色组合。
- **所有执行角色均为 SOPAgent 实例，角色名称和分工由配置文件决定，框架代码不感知具体角色类型。**

## 6. 代码实现要点

- **SOPAgent**：统一执行者，定义在 `src/agents/sop_agent.py`，实现 quick_think、工具注册、任务执行等核心逻辑。
- **SOPManager**：流程协调者，定义在 `src/agents/sop_manager.py`，负责计划编排与任务分派。
- **GraphFlow**：流程图与路由逻辑，定义在 `src/workflows/graphflow.py`。
- **PlanManager/ArtifactManager**：工具集，定义在 `src/tools/plan/manager.py`、`src/tools/artifact_manager.py`。
- **配置解析**：定义在 `src/config/parser.py`。

## 7. 结构图（建议补充）

```
用户
  │
  ▼
SOPManager（流程协调）
  │
  ├───► SOPAgent（任务执行/QuickThink/自我分解）
  │
  └───► StopAgent（流程终点）
```

## 8. 当前状态说明

- 已实现function_call链路自动推进，SOPManager分派任务时带全plan/step/task所有id，计划工具能唯一定位任务。
- 但推进逻辑需遍历所有step下所有未完成task，不能只看step.status，否则会导致部分task未被自动分派和更新。
- QuickThink机制已集成，SOPAgent可在任务前置分析和分解中调用Judge工具。
- 配置驱动的多模板/多团队适配能力初步具备。
- 日志与可观测性已覆盖主要流程。

## 9. 未完成工作

- SOPManager推进逻辑需彻底遍历所有未完成task，确保所有任务都能被自动分派和更新。
- QuickThink与任务分解的自动化能力待完善，需支持更复杂的任务自我分解和子计划生成。
- 配置驱动的多模板/多团队适配能力待进一步增强，支持更灵活的团队结构和SOP流程。
- 日志与可观测性细节优化，便于大规模调试和流程追踪。
- 计划/任务状态变更的回溯与异常处理机制待补充。
