# CURSOR_README

## 2024-06 SwarmGroup自治SOP多智能体方案开发记录

### 背景与目标
- 目标：用SwarmGroup（基于handoff message的完全图）替换原GraphFlow，实现SAFE SOP多智能体团队的任务自治。
- 只包含团队成员Agent（config.yaml定义），Starter和Reviewer单独运行。
- 计划、任务分配、资产管理、日志等均通过现有工具实现。

### 主要架构
- Starter：负责模板匹配、计划创建，运行完毕后将计划ID/上下文传递给SwarmGroup。
- SwarmGroup：只包含团队成员Agent，成员间完全图handoff，任务完成后handoff给下一个未完成任务的Assignee。
- FunctionalTermination：判断计划是否全部完成，作为SwarmGroup终止条件。
- Reviewer/Terminator：SwarmGroup结束后单独运行，负责总结和复盘。

### 关键决策与约定
- SwarmGroup成员只包含团队成员Agent，不包含Starter/Reviewer/Manager。
- 任务分配、Assignee全部由config.yaml静态配置，后续如有动态子计划Assignee也来源于团队成员。
- 资产管理、日志格式按现有实现，无需额外配置。
- Reviewer输出格式暂无要求。

### FunctionalTermination设计细节
- 只依赖plan_manager和plan_id，与SwarmGroup解耦。
- Starter创建计划后获得plan_id。
- 创建FunctionalTermination时，传入一个判断计划是否完成的Callable（闭包中引用plan_manager和plan_id）。
- 该Callable逻辑：通过plan_manager.get_plan(plan_id)查询计划状态，若plan['status']=='done'则返回True，否则返回False。
- SwarmGroup构造时将FunctionalTermination作为termination_condition参数传入。
- SwarmGroup无需感知termination_condition的内部实现。

#### 伪代码示例：
```python
plan_id = plan_manager.create_plan(...)

async def plan_is_done(messages):
    plan = plan_manager.get_plan(plan_id)
    return plan and plan['status'] == 'done'

termination_condition = FunctionalTermination(plan_is_done)
swarm_group = Swarm(participants=..., termination_condition=termination_condition, ...)
```

### SwarmGroup组装与主流程设计说明
- 读取config.yaml，动态加载所有团队成员Agent（SOPAgent）。
- Starter创建计划，获得plan_id。
- 构造FunctionalTermination（闭包持有plan_manager和plan_id）。
- 组装SwarmGroup（participants为所有SOPAgent，termination_condition为FunctionalTermination）。
- 主流程：Starter（计划创建）→ SwarmGroup（任务执行）→ Reviewer（总结复盘）。

#### SwarmGroup组装实现路径
- 新建build_sop_swarm_group(team_config, model_client, plan_manager, plan_id)函数。
- 遍历team_config.agents，实例化所有SOPAgent，组成participants列表。
- 构造FunctionalTermination（如前述闭包）。
- 返回Swarm实例。

#### 主流程实现路径
- 启动时先运行Starter，创建计划，获得plan_id。
- 调用build_sop_swarm_group组装SwarmGroup。
- SwarmGroup.run_stream执行任务，自动handoff，直到所有任务完成。
- 结束后调用Reviewer输出总结。

#### 伪代码
```python
# 1. Starter创建计划
plan_id = starter.create_plan(...)

# 2. 组装SwarmGroup
swarm_group = build_sop_swarm_group(team_config, model_client, plan_manager, plan_id)

# 3. 执行SwarmGroup
await swarm_group.run_stream(...)

# 4. 复盘
reviewer.summarize(plan_id)
```

### Starter/Reviewer运行方式设计说明
- Starter和Reviewer均可直接通过`await agent.run(task=...)`方式运行，无需特殊流程控制。
- 如仅需提示词驱动，可直接用AssistantAgent；如需更复杂行为，可继承AssistantAgent实现。
- 运行方式与SwarmGroup解耦，主流程中直接串联调用。

### SOPStarter提示词优化说明
- 去除"你是SOPStarter"类无意义角色声明，专注于功能性和结构化输出。
- 明确要求输出严格的JSON格式，内容包括name、description、reason，便于后续自动处理和追溯。
- 提示词示例：
  """
  请根据用户输入的任务，在SOP模板清单中查找最合适的匹配项。
  严格按照如下JSON格式输出匹配结果：
  {
    "name": "匹配项的name",
    "description": "匹配项的描述",
    "reason": "你选择该模板的理由"
  }
  可选模板清单如下：
  {templates}
  """

### Reviewer提示词结构化设计说明
- Reviewer输出需结构化、专业，便于自动处理和追溯。
- 推荐输出如下JSON格式：
  """
  {
    "plan_id": "计划ID",
    "summary": "对整个计划执行过程的简要总结",
    "key_findings": ["主要发现1", "主要发现2"],
    "improvements": ["可改进点1", "可改进点2"],
    "lessons_learned": ["经验教训1", "经验教训2"]
  }
  """
- 可根据实际业务需求增减字段。
- 作为Reviewer的system_message或prompt，运行时传入plan_id，要求LLM严格输出结构化JSON。

### Swarm流程主流程集成实现说明
- 推荐run_swarm实现步骤：
  1. Starter实例化与运行，获取plan_id
  2. SwarmGroup组装与运行，自动任务流转
  3. Reviewer实例化与运行，输出结构化总结
- 参数最小化，主流程清晰，所有依赖对象在主流程内部创建和传递。
- 输出事件流可统一处理，便于日志和后续分析。

### 设计进展
- [x] 需求梳理与确认（2024-06-xx）
- [x] FunctionalTermination设计细节与实现路径确认
- [x] SwarmGroup组装与主流程设计说明
- [x] Starter/Reviewer运行方式设计说明
- [x] SOPStarter提示词优化说明
- [x] Reviewer提示词结构化设计说明
- [x] Swarm流程主流程集成实现说明
- [ ] build_sop_swarm_group组装SwarmGroup
- [ ] SOPAgent逻辑完善（handoff、任务状态、调试模式等）
- [ ] 主流程Starter→SwarmGroup→Reviewer串联
- [ ] 测试/调试脚本

### 后续可扩展点
- 支持动态子计划与Assignee动态分配
- Reviewer输出格式与资产结构化
- 日志与资产的统一查询与可视化

---
本文件持续更新，记录每一步关键决策与开发进展。如有新需求/变更，请同步补充。 