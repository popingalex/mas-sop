"""任务类型相关定义。"""

from typing import Literal

TaskType = Literal["QUICK", "SEARCH", "AMBIGUOUS", "TASK"]
"""任务类型定义。

QUICK: 可以快速完成的简单任务
SEARCH: 需要搜索信息的任务
AMBIGUOUS: 需要澄清的模糊任务
TASK: 需要按照 SOP 执行的任务
""" 