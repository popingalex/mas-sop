from enum import Enum

class ErrorMessages(str, Enum):
    """错误消息枚举。
    
    使用 str 作为基类可以直接使用枚举值作为字符串，无需额外调用 .value
    """
    # 通用错误
    INVALID_UUID = "提供的 {id_str} 不是有效的 UUID 格式"
    NOT_FOUND = "{resource} {id_str} 未找到"
    
    # 计划相关错误
    PLAN_EXISTS = "计划ID {plan_id} 已存在"
    PLAN_INVALID_PARENT_STEP = "无效的父步骤ID格式"
    PLAN_NO_STEPS = "计划不存在或没有步骤: {plan_id}"
    PLAN_INVALID_STATUS = "无效的状态 '{status}'. 允许的状态: {valid_statuses}"
    PLAN_STEP_INDEX_OUT_OF_RANGE = "无效的步骤索引 {index} (计划 {plan_id} 只有 {total} 个步骤)"
    PLAN_MISSING_REQUIRED = "缺少必填字段: {field}"
    
    # 制品相关错误
    ARTIFACT_FORMAT_UNSUPPORTED = "当前仅支持YAML格式，已忽略请求的'{format}'格式"
    ARTIFACT_NAME_REQUIRED = "必须提供 'name' 或 'description' 之一"
    ARTIFACT_NAME_INVALID = "无法确定制品名称"
    ARTIFACT_EXISTS = "制品 ID {artifact_id} 已存在"
    ARTIFACT_VALIDATION_ERROR = "制品验证失败：{error}"
    
    # 笔记相关错误
    NOTE_CONTENT_AUTHOR_REQUIRED = "笔记内容 (content) 和作者 (author) 不能为空"
    NOTE_VALIDATION_ERROR = "添加笔记失败：输入数据验证错误 - {error}"

    def format(self, **kwargs) -> str:
        """格式化错误消息。
        
        Args:
            **kwargs: 用于替换消息模板中的占位符的参数。
        
        Returns:
            格式化后的错误消息。
        
        Example:
            >>> ErrorMessages.INVALID_UUID.format(id_str="123")
            '提供的 123 不是有效的 UUID 格式'
        """
        return self.value.format(**kwargs) 