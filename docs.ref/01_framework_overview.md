# SAFE 框架概览

## 1. 引言

本文档旨在解释基于标准操作规程 (Standard Operating Procedures, SOP) 设计的多智能体系统 (Multi-Agent System, MAS) 团队配置文件（以 `team.yaml` 示例为基础）的结构和含义。其核心目的是阐述一个多智能体框架如何利用此配置，使得智能体团队能够按照预定义的 SOP 逻辑进行结构化、高效的协作。

采用这种配置模式的核心优势在于：

*   **流程规范化 (Process Standardization)**: 将核心协作流程模板化，确保行动有章可循。
*   **职责清晰化 (Clear Responsibilities)**: 明确各智能体 (Agent) 在 SOP 模板中的主要任务分配。
*   **动态与静态结合 (Dynamic & Static Blend)**: 固化整体 SOP 流程模板，同时赋予智能体 (通过通用基类，如 `AgentBaseRole`) 在执行复杂任务时进行动态内部规划和协作请求的灵活性。
*   **可解释性与可维护性 (Interpretability & Maintainability)**: 配置化的流程模板便于理解、评估和迭代。

## 2. 配置结构概览 (示例: `team.yaml`)

一个典型的基于 SOP 的团队配置文件 (`team.yaml`) 包含以下关键部分：

*   **基本信息 (Basic Info)**: `name`, `description`, `max_turns` 等，定义团队标识。
*   **`workflows`**: **核心部分**，定义了团队协作所依据的 SOP 流程模板。
*   **`base_prompt`**: 为所有智能体提供通用的行为准则和关键指令（例如如何与 Tools 交互）。
*   **`agents`**: 详细定义每个团队成员（智能体）：标识符 (`name`)、能力 (`actions` 和 `tools`)，以及特定的行为指令 (`system_message`)。
*   **`properties`**: 包含团队级别的元数据 (Metadata)，如 SOP 版本、标准资产名称等。

## 3. 理解 `workflows`：SOP 流程模板

`workflows` 部分定义了协作的骨架，作为一个结构化的模板。

*   **全局工作流模板 (Global Workflow Template) (`is_global: true`)**: 框架或初始化智能体（例如 `Strategist` Agent）应识别标记为 `is_global: true` 的工作流作为默认的 SOP 模板。
*   **步骤 (Steps)**: 定义了 SOP 的主要阶段。
*   **任务 (Tasks)**: 每个步骤下包含的具体任务单元。
    *   `task_id`, `name`: 任务标识和名称。
    *   `assignee`: 指定了**默认负责**执行此任务的智能体标识符 (`name`)。驱动流程的智能体将使用此信息来激活正确的智能体。
    *   `description`: **极其关键**。详细描述了任务的目标和关键要求。这是智能体（尤其是其基类）理解其工作内容并进行内部规划（可能结合此描述作为指导）的核心输入。

**`workflows` 的作用**: 它本身**不是**一个直接执行的计划，而是一个**结构化模板**。某个指定的智能体（如 `Strategist` Agent）会在流程开始时读取这个模板，并调用 `Plan Tool` 的方法 (例如 `create_plan_from_structure`)，将这个模板实例化为一个具体的计划状态，存储在 `Plan Tool` 中。

## 4. 核心工具交互 (`Plan Tool`, `ArtifactManager Tool`)

框架提供了关键的通用工具来支持协作：

*   **`Plan Tool`**: 一个**被动的状态管理工具**。它存储由 SOP 模板实例化的计划状态（任务、状态等）。智能体通过调用其 API 来查询任务信息 (`get_task`, `get_ready_tasks`) 和更新任务状态 (`update_task_status`)。
*   **`ArtifactManager Tool`**: 一个**通用的资产存储工具**，智能体通过调用其 API (`save_asset`, `load_asset`) 来共享和管理信息资产。

## 5. 与智能体基类 (如 `AgentBaseRole`) 的关系

*   通用智能体基类 (`AgentBaseRole`) 提供了智能体执行任务的核心逻辑。
*   它依赖于从外部获取任务目标（通常是来自 `Plan Tool` 的任务 `description`）。
*   它利用任务 `description` 和可能的 SOP 上下文进行内部规划决策和执行。
*   它在任务完成后调用 `Plan Tool` 更新状态。
*   它可以调用 `ArtifactManager Tool` 处理资产。
*   它可以调用通用的 `RequestCollaboration` Action 来委派子任务。

## 6. 框架如何利用配置驱动团队工作 (基于 "Plan Tool Model")

一个遵循 "Plan Tool Model" 的框架利用配置的方式如下：

1.  **加载配置 (Load Config)**: 解析配置文件 (如 `team.yaml`)。
2.  **实例化组件 (Instantiate Components)**: 创建 `Plan Tool`、`ArtifactManager Tool` 等通用工具实例。根据 `agents` 列表，结合 `base_prompt` 和各自的 `system_message`，创建所有智能体实例 (继承自通用基类)，并赋予其定义的 `actions` 和 `tools`。
3.  **初始化流程 (Initiate Process)**: 某个指定的初始化智能体（例如 `Strategist` Agent）被激活。
4.  **创建计划实例 (Create Plan Instance)**:
    *   该初始化智能体读取配置文件中 `is_global: true` 的 `workflows` 模板。
    *   调用 `Plan Tool` 的 `create_plan_from_structure` 方法，将模板数据传入，创建并存储初始计划状态。
5.  **驱动执行循环 (Drive Execution Loop)**:
    *   驱动智能体（例如 `Strategist` Agent）调用 `Plan Tool` 的 `get_ready_tasks` 获取当前就绪的任务列表。
    *   对于每个就绪任务，驱动智能体确定其 `assignee` (目标智能体名称)。
    *   驱动智能体通过**通信机制**（例如发送结构化消息）**激活**对应的 `assignee` 智能体，并将任务目标信息（如 `task_id`, `plan_id`, `description` 和可能的 SOP 上下文）传递给它。
6.  **任务执行与协作 (Task Execution & Collaboration)**:
    *   被激活的智能体 (基于通用基类) 接收任务目标。
    *   执行其内部的任务处理逻辑（如 `AgentBaseRole` 设计文档所述），包括规划策略决策、内部规划（可能参考 SOP 描述）、执行自身步骤、调用 `ArtifactManager Tool`、调用 `RequestCollaboration` Action 委派子任务。
    *   任务完成后，调用 `Plan Tool` 的 `update_task_status`。
7.  **循环与结束 (Loop & Termination)**: 驱动智能体持续查询 `Plan Tool`，激活后续任务，直到 `Plan Tool` 指示整个计划完成，或收到终止信号。

这种方法将高层流程的结构（SOP 模板）与流程的执行驱动（特定智能体）分离，同时赋予所有智能体通用的动态规划和协作能力。 