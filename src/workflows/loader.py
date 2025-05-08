import os
from typing import List, Dict, Any
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError
from pydantic import ValidationError
from .models import WorkflowTemplate
from loguru import logger
from src.types.plan_types import Plan, Step

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
        logger.debug(f"Raw data loaded from YAML. Top-level keys: {list(raw_data.keys()) if isinstance(raw_data, dict) else 'Not a dict'}")
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
        logger.success(f"成功加载并验证工作流模板: {template.workflow.name} (Team: {template.team_name}, Config Version: {template.version})")
        return template
    except ValidationError as ve:
        logger.error(f"工作流模板文件 '{filepath}' 内容验证失败: {ve}")
        raise
    except Exception as e:
         logger.error(f"加载工作流模板时发生未知错误: {e}")
         raise # Re-raise unexpected errors 

def extract_plan_from_workflow_template(template: "WorkflowTemplate") -> Plan:
    """
    从WorkflowTemplate对象提取SOP计划（Plan类型），每个任务一次一个人执行。
    Plan结构：
        id: workflow.name
        title: workflow.name
        description: workflow.description
        steps: List[Step]
    Step结构：
        index: int
        description: task.description
        status: "pending"
    """
    steps = []
    idx = 1
    for step in template.workflow.steps:
        for task in step.tasks:
            steps.append(Step(index=idx, description=task.description, status="pending"))
            idx += 1
    plan = Plan(
        id=template.workflow.name,
        title=template.workflow.name,
        description=template.workflow.description or "",
        steps=steps
    )
    return plan 