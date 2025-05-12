from typing import Optional, Any
from typing_extensions import NotRequired, TypedDict

class ResponseType(TypedDict):
    """标准工具响应类型。"""
    status: str # 'success' or 'error'
    message: str
    data: NotRequired[Any] # 可选字段，为None时可以不传

def success(message: str, data: Optional[Any] = None) -> ResponseType:
    """创建成功的响应。"""
    return ResponseType(status='success', message=message, data=data)

def error(message: str) -> ResponseType:
    """创建失败的响应。"""
    return ResponseType(status='error', message=message, data=None) 