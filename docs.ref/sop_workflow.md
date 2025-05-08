# SAFE SOP 多智能体系统实现原理与工作流

## 1. 引言

本文档旨在阐述 SAFE (Simulation and Agent Framework for Emergencies) 框架中，基于标准化操作规程 (SOP) 的多智能体团队的具体实现原理和工作流程。它连接了高层架构设计与代码层面的实现思路，解释了系统如何结合大型语言模型 (LLM) 的能力与结构化的多智能体协作，来模拟应急响应规划过程。本文档是支撑相关研究论文的核心技术说明，重点剖析系统的架构设计、核心机制、运转原理及其在代码层面的映射。

## 2. 系统总体架构与设计哲学

SAFE 框架采用以协调者为中心、配置驱动的多智能体架构，旨在模拟结构化、流程化的应急响应团队协作模式。

### 2.1 中心化流程图架构 (Hub-and-Spoke `GraphFlow` Model)

系统的核心交互模式是通过 AutoGen 的 `GraphFlow` 构建的**中心化流程图（或称辐射型/Hub-and-Spoke）架构**。

-   **中心节点 (`NexusAgent`)**: `NexusAgent` 作为流程的绝对中心，是 SOP 流程的主要驱动者。其内部 LLM 负责决策，并通过消息和工具调用来协调其他 Agent。
-   **叶子节点 (`LeafAgent`, `StopAgent`)**: 各种 `LeafAgent`（任务执行者）和 `StopAgent`（流程终点）作为叶子节点，直接与 `NexusAgent` 进行交互。它们之间通常不直接通信，所有协调工作均通过 `NexusAgent`。
-   **消息驱动与路由**: Agent 间的协作通过异步消息传递实现。`GraphFlow` 根据预定义的边和动态条件（通常基于消息的来源、内容或类型）将消息从一个 Agent 路由到另一个 Agent，从而实现控制权的转移和流程的推进。
-   **优势**: 这种架构简化了 Agent 间的依赖关系，使得流程控制的决策逻辑集中在 `NexusAgent` 的 LLM 中，并通过 `GraphFlow` 的配置实现路由，便于理解、管理和扩展。

### 2.2 配置驱动设计

系统的行为在很大程度上由外部配置文件（主要是 `config.yaml`）指导，包括：
-   团队定义：包含哪些 Agent，每个 Agent 的角色、名称。
-   Agent 配置：每个 Agent 的提示词 (prompt)、可使用的工具列表 (特别是 `NexusAgent` 可用的 `PlanManager` 工具)、LLM 配置。
-   工作流/SOP 模板：`config.yaml` 中的 `workflow` 部分可以定义一个或多个 SOP 模板，包含推荐的步骤结构（描述、建议指派人等），作为 `NexusAgent` 的 LLM 创建计划时的重要参考。
-   GraphFlow 路由规则：在 `graphflow.py` 中定义，决定消息如何在 Agent 之间流转。

这种设计使得在不修改核心代码的情况下，可以通过调整配置文件来适应不同的SOP流程、团队构成和 Agent 行为。

## 3. 核心组件与机制

### 3.1 智能体 (Agents)

#### 3.1.1 Agent 基础行为: LLM 驱动的决策与行动 (LLM-Driven Decision and Action)

SAFE 框架中的 Agent（特别是 `NexusAgent` 和 `LeafAgent`）的核心是其内部的 LLM。Agent 的行为由 LLM 基于当前对话历史、自身状态、可用工具和系统提示 (system message) 来驱动：

-   **理解与推理**: LLM 分析接收到的消息和上下文信息。
-   **决策**: LLM 决定下一步的行动，这可能是：
    1.  **调用工具 (Tool Call)**: 生成一个调用特定工具（如 `PlanManager` 的方法）的请求，并附带必要的参数。
    2.  **生成消息 (Message Generation)**: 生成一个文本消息，用于与其他 Agent 通信或最终输出。
-   **执行与响应**: Agent 的 Python 代码框架负责解析 LLM 的决策，执行工具调用（如果请求了），并将工具结果或生成的文本消息传递出去（通常通过 `yield`）。

提示词工程 (Prompt Engineering) 对于引导 LLM 做出符合预期的决策至关重要。

#### 3.1.2 主要 Agent 角色

-   **`BaseSOPAgent`**: 所有特定功能 Agent 的基类。
-   **`NexusAgent` (中心协调者)**:
    -   **核心职责**: **LLM 驱动的 SOP 流程编排**。
        -   **QuickThink**: 接收初始任务，其 LLM 参考可用 SOP 模板 (来自 `TeamConfig`)，决策是否及如何创建一个 SOP 计划，并**生成对 `PlanManager.create_plan` 工具的调用**。
        -   **推进**: LLM **调用 `PlanManager.get_next_pending_step` 工具** 获取下一个待处理步骤。
        -   **分派**: LLM 根据上一步结果，**生成任务消息**发送给指定的 `LeafAgent`。
        -   **状态更新**: LLM 在收到 `LeafAgent` 完成消息后，**调用 `PlanManager.update_step` 工具** 更新步骤状态。
        -   **结束**: LLM 在判断所有步骤完成后（基于 `get_next_pending_step` 的结果），**生成结束消息**发送给 `StopAgent`。
    -   **交互**: 主要通过其 LLM **调用 `PlanManager` 工具集**，并**生成消息**与其他 Agent 通信。
-   **`LeafAgent` (任务执行者)**:
    -   **职责**: **LLM 驱动的具体 SOP 步骤执行**。接收来自 `NexusAgent` 的任务，利用其 LLM 理解任务、规划（可能分解子任务）、调用所需工具（信息查询、资产管理等），并最终**生成表示任务完成（或失败）的消息**。
    -   **交互**: 与 `NexusAgent` (收发任务/结果)，以及可能的其他业务工具或 `PlanManager` (查询上下文)。
-   **`StopAgent` (流程终点)**: 标记流程成功结束。
-   **`OutputAgent` (可选)**: 汇总输出。

### 3.2 计划管理工具集 (`PlanManager` as a Toolset)

`PlanManager` 不再是 `NexusAgent` 直接操作的内部引擎，而是作为一套**供 LLM 调用的工具函数 (Toolset)**，封装了 SOP 计划的存储、结构化表示和状态管理。

-   **SOP 表示**: 内部维护 `Plan` 和 `Step` 的数据结构（如 `TypedDict` 或 Pydantic 模型），包含 ID、标题、内容/描述、指派人、状态等字段。
-   **提供的工具 (Methods as Tools)**:
    -   `create_plan(title: str, reporter: str, steps_data: List[Step]) -> ResponseType`: 供 LLM 调用以创建新的 SOP 计划实例。**`steps_data` 参数由 LLM 根据任务和模板动态生成**。
    -   `get_plan(plan_id_str: str) -> ResponseType`: 供 LLM 查询计划详情。
    -   `get_next_pending_step(plan_id_str: str) -> ResponseType`: 供 LLM 查询下一个状态为 "not_started" 的步骤。
    -   `update_step(plan_id_str: str, step_index: int, update_data: Step) -> ResponseType`: 供 LLM 更新特定步骤的状态（如 "in_progress", "completed"）。**注意**: LLM 需要先通过 `get_plan` 或其他方式确定目标步骤的 `step_index`。
    -   `list_plans() -> ResponseType`: (可选) 供 LLM 查看当前所有计划。
    -   `delete_plan(plan_id_str: str) -> ResponseType`: (可选) 供 LLM 删除计划。
-   **关键交互**: `NexusAgent` 的 LLM 通过在其思考过程中**决定调用**这些工具，并解析返回的结果，来驱动 SOP 流程。

### 3.3 资产管理机制 (`ArtifactManager`)

-   **目的 (若实现)**: `ArtifactManager` (对应概念上的 Asset Hub) 旨在提供一个标准化的方式来管理和共享流程中产生的结构化信息资产（工件）。
-   **作用**: 使得 Agent 间（尤其是跨多个 SOP 步骤）的信息传递不完全依赖于自然语言消息，可以共享更复杂、更精确的数据对象，提高信息保真度和协作效率。`LeafAgent` 可以将重要产出物作为资产存入，后续的 `LeafAgent` 或 `NexusAgent` 可以按需检索。

### 3.4 Agent 工具调用 (Tool Call)

Agent 通过调用工具来扩展其能力并与外部环境或其他系统组件交互。核心工具类别包括：
-   **任务类型判断工具 (Task Type Judging Tool)**: 如 `judge_task_type_tool`，由一个专门的 `AssistantAgent` (名为 "Judger"，配置了特定的判断逻辑和提示)封装而成。`NexusAgent` 在处理新任务时调用此工具，以判断任务**本质上是否复杂到需要一个结构化计划 (PLAN) 来执行，或者它是否足够简单可以直接处理 (SIMPLE)**。该工具返回一个包含判断类型和原因的JSON字符串。如果判断为PLAN，`NexusAgent` 后续可能会利用其掌握的SOP模板来创建这个计划。
-   **计划管理工具 (Planning Tools)**: 即与 `PlanManager` 交互的接口，用于创建/查询/更新计划和步骤状态。这是 `NexusAgent` 和 `LeafAgent` 的核心工具。
-   **资产管理工具 (Asset Management Tools)**: 即与 `ArtifactManager` 交互的接口，用于创建/检索/更新信息资产。
-   **信息查询工具 (Information Query Tools)**: 用于从模拟信息库或其他数据源获取执行任务所需的信息。
-   *其他特定业务工具*: 根据应用场景可能需要的任何其他工具。

## 4. 整体运转原理：LLM驱动的工具使用流程

SAFE 框架的 SOP 执行能力现在更清晰地体现为 LLM 通过工具与 `PlanManager` 交互的流程：

1.  **启动与 QuickThink**:
    -   系统启动，`NexusAgent` 被激活并收到初始用户任务。
    -   `NexusAgent` 的 LLM (在 QuickThink 阶段) 被调用。**首先，`NexusAgent` 会调用 `judge_task_type_tool` 工具，将用户任务描述传递给它。**
    -   `judge_task_type_tool` 返回一个JSON字符串，指明任务类型（例如 "PLAN" 或 "SIMPLE"）和原因。
    -   `NexusAgent` 解析此JSON。
    -   **如果判断结果为 "PLAN"**:
        -   `NexusAgent` 的 LLM 继续其 QuickThink 流程，其上下文包含用户任务、判断结果。此时，`NexusAgent` **会查阅其配置中可用的 SOP Workflow 模板列表** (来自 `TeamConfig`)。
        -   LLM 决策：
            -   如果选择应用一个SOP模板，LLM **生成对 `PlanManager.create_plan` 工具的调用请求**，其中 `steps_data` 是 LLM 基于所选模板和当前任务定制的结果。
            -   如果LLM决定不使用预定义SOP模板而是直接创建计划（例如，任务独特或模板不适用），它仍会生成对`PlanManager.create_plan`的调用，但`steps_data`将完全由LLM根据任务构思。
        -   `NexusAgent` 执行 `create_plan` 工具调用，获取 `plan_id` 并更新自身状态。
    -   **如果判断结果为 "SIMPLE"**:
        -   `NexusAgent` 的 LLM 可能会尝试直接生成对用户请求的简单回应，或者指示流程结束/转交其他简单处理单元。
    -   **如果判断结果为其他类型（或工具出错）**:
        -   `NexusAgent` 根据具体情况处理，可能包括请求用户澄清、记录错误或终止流程。
2.  **SOP 推进循环 (LLM 主导)**:
    a.  LLM 接收到计划已创建的上下文（或上一步骤完成的上下文）。
    b.  LLM **决策调用 `PlanManager.get_next_pending_step` 工具**。
    c.  `NexusAgent` 执行工具调用，并将结果返回给 LLM。
    d.  **任务分派**: 如果工具返回了待处理步骤 (`next_step_data`)：
        -   LLM **解析 `next_step_data`** 获取任务信息和 `assignee`。
        -   (可选，LLM决策) LLM 可能**生成对 `PlanManager.update_step` 工具的调用**，将该步骤设为 "in_progress"。`NexusAgent` 执行此调用。
        -   LLM **生成包含任务指令的 `TextMessage`**，目标是 `assignee`。
        -   `NexusAgent` `yield` 此消息，由 `GraphFlow` 路由。
    e.  **流程结束判断**: 如果工具返回无待处理步骤：
        -   LLM **判断流程结束**。
        -   LLM **生成发送给 `StopAgent` 的结束消息** (`ALL_TASKS_DONE`)。
        -   `NexusAgent` `yield` 此消息。
3.  **处理 `LeafAgent` 回复 (LLM 主导)**:
    a.  `NexusAgent` 收到 `LeafAgent` 的回复消息。
    b.  LLM 被调用，上下文包含该回复。
    c.  LLM **解析回复** (判断任务是否完成)。
    d.  LLM **决策调用 `PlanManager.update_step` 工具**，将对应步骤标记为 "completed"。`NexusAgent` 执行此调用 (LLM 需要提供 `step_index`，可能需要先调用 `get_plan`)。
    e.  LLM 返回到步骤 2b，决定调用 `get_next_pending_step` 以继续流程。

这个 **"LLM分析上下文 -> LLM决策调用PlanManager工具或生成消息 -> NexusAgent执行LLM指令 -> 更新上下文 -> 循环"** 的模式，是当前设计的核心。

## 5. 配置驱动的灵活性

-   **SOP流程定义**: `config.yaml` 中的 `workflow` 字段允许用户灵活定义SOP的步骤、顺序和指派关系。
-   **Agent行为定制**: 通过修改各 `LeafAgent` 的提示词 (prompt) 和分配的工具，可以精细控制其在执行特定SOP步骤时的行为模式和专业能力。
-   **团队构成**: 可以方便地在配置文件中增删 `LeafAgent`，调整团队规模和角色组合。

## 6. 代码实现要点

-   核心Agent类 (如 `NexusAgent`, `LeafAgent`, `BaseSOPAgent`) 定义在 `src/agents/` 目录。
-   `GraphFlow` 的构建和路由逻辑主要在 `src/workflows/graphflow.py`。
-   `PlanManager` 的实现位于 `src/tools/plan/manager.py`。
-   配置文件解析逻辑在 `src/config/parser.py`。

## 7. 当前状态说明 (可选)

请注意，当前代码库可能处于**调试阶段**。为了验证核心流程的连通性，部分组件的行为可能被暂时简化 (例如，`LeafAgent` 可能直接回复 "任务完成" 而不执行复杂的思考、规划或工具调用)。本文档描述的是系统**最终的目标架构、完整原理和预期行为**，旨在为后续的详细实现和功能完善提供清晰的蓝图。 