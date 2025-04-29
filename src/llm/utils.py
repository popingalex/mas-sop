"""LLM 消息处理相关的工具函数。"""

from typing import Union, Dict, List, Any, Optional
import json
import ast
from autogen_agentchat.base import TaskResult

def get_last_message_content(task_result: TaskResult) -> Optional[str]:
    if (hasattr(task_result, 'messages') and 
        task_result.messages and 
        len(task_result.messages) > 0):
        last_message = task_result.messages[-1]
        return last_message.to_text()
    return None

def maybe_structured(content: str) -> Union[str, Dict[str, Any], List[Any]]:
    try:
        # 先尝试用 ast.literal_eval，它更安全且支持更多 Python 字面量
        return ast.literal_eval(content)
    except (ValueError, SyntaxError):
        try:
            # 再尝试用 json.loads
            return json.loads(content)
        except json.JSONDecodeError:
            # 都失败了就返回原始字符串
            return content 