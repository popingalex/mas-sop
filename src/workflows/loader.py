from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from pydantic import ValidationError
from .models import WorkflowTemplate
from loguru import logger

def load_workflow_template(filepath: str) -> WorkflowTemplate:
    """加载并解析 YAML 格式的工作流模板文件。

    Args:
        filepath: YAML 模板文件的路径。

    Returns:
        经过验证的 WorkflowTemplate Pydantic 模型对象。

    Raises:
        FileNotFoundError: 如果文件不存在。
        YAMLError: 如果 YAML 解析失败。
        ValidationError: 如果文件内容不符合 WorkflowTemplate 模型。
        ValueError: 如果顶层结构不是字典。
    """
    yaml = YAML(typ='safe')
    logger.info(f"尝试从 '{filepath}' 加载工作流模板...")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_data = yaml.load(f)
    except FileNotFoundError:
        logger.error(f"工作流模板文件未找到: {filepath}")
        raise
    except YAMLError as e:
        logger.error(f"工作流模板文件 YAML 解析错误: {e}")
        raise

    if not isinstance(raw_data, dict):
        raise ValueError(f"工作流模板文件 '{filepath}' 的顶层必须是字典。")

    try:
        template = WorkflowTemplate.model_validate(raw_data)
        logger.success(f"成功加载并验证工作流模板: {template.name} v{template.version}")
        return template
    except ValidationError as ve:
        logger.error(f"工作流模板文件 '{filepath}' 内容验证失败: {ve}")
        raise
    except Exception as e:
         logger.error(f"加载工作流模板时发生未知错误: {e}")
         raise # Re-raise unexpected errors 