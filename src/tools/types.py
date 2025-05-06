from typing_extensions import TypedDict
from typing import Any, Optional

class ResponseType(TypedDict):
    """标准工具响应类型。"""
    status: str # 'success' or 'error'
    message: str
    data: Optional[Any] # Can hold any data depending on the operation

def success(message: str, data: Optional[Any] = None) -> ResponseType:
    """创建成功的响应。"""
    return ResponseType(status='success', message=message, data=data)

def error(message: str) -> ResponseType:
    """创建失败的响应。"""
    return ResponseType(status='error', message=message, data=None) 