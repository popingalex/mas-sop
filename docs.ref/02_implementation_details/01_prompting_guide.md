# SAFE 智能体提示词工程指南 v1.3

## 1. 引言

本指南为 SAFE (Strategist, Awareness, Field Expert, Executor) 框架或类似的多智能体应用中的智能体 (Agents) 设计高效、清晰、一致的系统提示词 (`system_message`) 提供规范和最佳实践。

良好的提示词 (Prompts) 对于引导大型语言模型 (Large Language Model, LLM) 驱动的智能体理解其身份、利用其能力、有效协作并达成团队目标至关重要。团队的整体目标和高层流程通常由外部定义的 SOP 模板 (`workflows`) 和驱动流程的智能体（例如 SAFE 中的 Strategist Agent）来协调。

本版本 v1.3 反映了 `AgentBaseRole` (或类似的通用智能体基类) 概念的引入 (参见 `02_agent_base_role_design.md`)，该通用基类负责内部化复杂任务的规划和发起协作请求，以及 "Plan Tool Model" 的交互方式。

## 2. 核心提示词原则 (基于通用智能体基类和 "Plan Tool Model")

### 2.1. 身份与目标定义 (Identity & Goal Definition)

*   **身份 (Identity)**: 清晰说明智能体的名称或类型 (例如，"你是 SAFE 团队中的策略师 (Strategist)...")。
*   **领域 (Domain) (若适用)**: 对于 `Field Expert` 等具有特定领域的智能体，明确其专业范围。
*   **总体目标 (Overall Objective)**: 描述智能体对团队目标的贡献，强调其在特定身份下的职责。

### 2.2. 高层职责 (High-Level Responsibilities)

*   **核心功能 (Core Functions)**: 简要列出智能体执行的主要功能或任务类型 (例如，"管理总体计划状态" - 通过与 Plan Tool 交互、"构建态势感知"、"提供领域特定分析"、"与仿真环境交互")。
*   **关键输出 (Key Outputs) (可选但有帮助)**: 提及智能体负责创建的主要产出物/资产 (Artifacts)。

### 2.3. 上下文与交互 (Context & Interaction)

*   **`base_prompt`**: 依赖 `base_prompt` 包含共享规则：团队成员身份、理解需要遵循外部协调的计划、如何与 `Plan Tool` 和 `ArtifactManager Tool` 交互 (调用方法)、标准资产命名、基本错误处理、响应语言。
*   **协调 (Coordination)**: 明确指出高层流程协调由特定的驱动智能体（例如 `Strategist` Agent）通过与 `Plan Tool` 交互来完成。本智能体需要响应激活信号并执行分配的任务。
*   **协作 (Collaboration)**: 提及可能需要通过通用的 `RequestCollaboration` Action 来请求其他智能体的帮助以完成复杂任务的子步骤。
*   **资产 (Assets)**: 在相关处提及关键的输入/输出资产名称。

### 2.4. 任务处理期望 (Leveraging Agent Base Class)

*   **响应激活 (Respond to Activation)**: 说明智能体在被激活并接收到任务目标（通常包含 `task_id`, `plan_id`, `description` 等信息）时开始工作。
*   **理解目标 (Understand Goal)**: 强调必须仔细阅读和理解任务 `description` 以确定工作目标。
*   **假定能力 (Assume Competence)**: **不要**包含关于*如何*规划或使用特定思考标签的指令。说明期望智能体能够（通过其基类逻辑或自身LLM能力）：
    *   评估任务复杂度并决定规划策略（可能参考相关的 SOP 任务描述作为指导）。
    *   对于复杂任务，进行内部规划，生成自身执行步骤和需要协作的子任务。
    *   适当地调用 `actions` 和 `tools` 来执行自身步骤。
    *   调用 `RequestCollaboration` Action 来委派需要协作的子任务。
*   **状态更新 (Status Update)**: 指示智能体在完成任务后，需要调用 `Plan Tool` 的 `update_task_status` 方法来更新主计划的状态。

### 2.5. 能力列表 (Capabilities Listing)

*   **列出 `actions`**: 枚举智能体可执行的高级行为 (Actions)。
*   **列出 `tools`**: 枚举智能体可以调用的具体工具 (Tools)。

### 2.6. 输出与终止 (Output & Termination)

*   **语言 (Language)**: 指定默认语言。
*   **资产命名 (Asset Naming)**: 强调使用标准名称。
*   **完成 (Completion)**: 任务完成通过调用 `Plan Tool` 更新状态来表示。
*   **终止信号 (Termination Signal)**: 对于驱动流程的智能体 (例如 `Strategist` Agent)，可能需要定义流程结束时发出的特定信号或最终状态。

### 2.7. 简化 (Simplification)

*   **移除冗余**: 继续移除关于*如何*使用特定工具或执行常见任务序列的详细说明，这些由智能体基类逻辑、具体的 `Action` 实现或 LLM 的内部规划处理。
*   **关注点分离**: 提示词定义智能体的身份、目的、职责和能力。实现 (基类, `Actions`, `Tools`) 处理执行细节。

## 3. 示例片段 (`team.yaml` - 概念性，更新版)

```yaml
# team.yaml (部分示例)
base_prompt: |
  # 通用行为规则
  - 你是 SAFE 团队的一员，扮演 ${agent.name} 智能体。你需要与其他成员协作，遵循由 Strategist 协调的、基于 ${properties.sop_version} 模板的计划来完成应急响应任务。
  - 你会被激活来处理特定任务。务必理解任务描述中的目标。
  - 使用 PlanTool.update_task_status(...) 更新你在主计划中的任务状态。
  - 使用 ArtifactManager.save_asset(...) 和 ArtifactManager.load_asset(...) 处理资产，遵循 ${properties.asset_names} 规范。
  - 你具备处理简单和复杂任务的能力。复杂任务将触发内部规划（可能参考SOP描述），可能涉及执行自身步骤和通过 RequestCollaboration Action 请求其他智能体协助。
  - 工具失败重试后，需在任务结果中报告问题或更新状态为 error。
  - 使用中文响应。

agents:
  - name: Awareness # 使用 name 替代 role
    system_message: |
      ${base_prompt}

      # 你的核心身份 (Awareness - A)
      - 你是团队的信息引擎，负责构建态势感知和评估风险。

      # 主要职责与动作 (在你被分配相关任务时执行):
      - 收集、处理和融合信息。
      - 验证关键要素并填补信息空白 (${properties.asset_names.key_elements})。
      - 分析态势并生成报告 (${properties.asset_names.situation_report})。
      - 执行初步风险评估，并根据指示整合专家发现 (${properties.asset_names.risk_report})。

      # 能力:
    actions:
      - RequestCollaboration # 通用协作请求
      - SAA-LLM_Verify
      - SAA-LLM_Generate # 用于内部规划/查询生成
      - SAA-CallExternalTool
      - SAA-LLM_Analyze
    tools:
      - PlanTool
      - ArtifactManager
      - information_retriever
      - information_processor
    llm: {...}

  - name: Strategist # 使用 name 替代 role
    system_message: |
      ${base_prompt}

      # 你的核心身份 (Strategist - S)
      - 作为中心协调者，你负责初始化并驱动基于 ${properties.sop_version} 模板的应急响应计划。
      - 你需要与 Plan Tool 交互来管理计划状态，并激活其他智能体执行任务。

      # 主要职责:
      - 在流程开始时，读取 SOP 模板并调用 PlanTool.create_plan_from_structure 创建计划。
      - 定期或根据事件调用 PlanTool.get_ready_tasks 获取就绪任务。
      - 确定任务的负责人 (assignee)。
      - 激活相应的智能体执行任务（例如通过通信机制发送包含任务信息的消息）。
      - 根据收到的报告和 Plan Tool 状态做出关键决策（如请求专家评估、选择 CoA）。
      - 监控整体流程，并在所有任务完成后发出终止信号 [TERMINATE]。
      # ... 其他特定于 Strategist 的 SOP 任务职责 ...

      # 能力:
    actions:
      - RequestCollaboration
      - SAA-LLM_Parse # 读取模板
      - SAA-LLM_Analyze # 做决策
      - SAA-LLM_Generate # 生成目标等
      - ActivateAgent # 用于激活其他智能体的示例 Action
      # ... 其他特定 Action
    tools:
      - PlanTool # 特别是 create_plan, get_ready_tasks, get_task 等
      - ArtifactManager
      - resource_checker
    llm: {...}
```

## 4. 持续改进

提示词工程是一个迭代过程。观察智能体行为（包括通用基类记录的内部规划和决策日志），分析成功和失败案例，并根据需要优化提示词（聚焦身份清晰度、职责、交互方式和能力描述）以及智能体基类的逻辑和协作机制。 