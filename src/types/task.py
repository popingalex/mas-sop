"""任务类型相关定义。"""

from typing import Literal

# 使用 Literal 类型来定义有效的任务类型
TaskType = Literal["PLAN", "SIMPLE", "SEARCH", "UNCERTAIN"]

# 所有有效的任务类型列表，用于验证
VALID_TASK_TYPES: list[TaskType] = ["PLAN", "SIMPLE", "SEARCH", "UNCERTAIN"]

"""任务类型定义。

SIMPLE: 可以快速完成的简单任务
SEARCH: 需要搜索信息的任务
UNCERTAIN: 需要澄清的模糊任务
PLAN: 需要按照 SOP 执行的任务
""" 