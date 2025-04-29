from typing import Dict, List, Optional, Any, Union
from autogen_agentchat.agents import AssistantAgent
from src.tools.plan.manager import PlanManager, Plan, Step, Note, PlanStatus, StepStatus
import json

class PlanManagingAgent(AssistantAgent):
    """基于 LLM 的计划管理代理，负责理解用户意图并管理计划。"""

    def __init__(self, name: str, plan_manager: PlanManager, **kwargs):
        """初始化计划管理代理。

        Args:
            name: 代理名称
            plan_manager: 计划管理器实例
            **kwargs: 传递给父类的其他参数
        """
        system_message = """你是一个智能的计划管理助手，负责帮助用户创建和管理计划。你需要：

1. 理解用户的自然语言指令
2. 分析计划的结构和依赖关系
3. 提供智能的计划管理建议
4. 确保计划的完整性和一致性

你可以：
1. 创建新计划和步骤
2. 更新计划和步骤的状态
3. 添加和管理笔记
4. 处理计划之间的父子关系
5. 分析计划执行情况并提供建议

请确保：
1. 理解用户意图并提供准确的响应
2. 验证所有操作的合理性
3. 维护计划状态的一致性
4. 提供清晰的操作反馈和建议"""

        super().__init__(
            name=name,
            system_message=system_message,
            **kwargs
        )
        self.plan_manager = plan_manager

    async def _analyze_request(self, request: str) -> Dict[str, Any]:
        """使用 LLM 分析用户请求，提取关键信息和意图。"""
        prompt = f"""请分析以下用户请求，提取关键信息：

{request}

请以 JSON 格式返回以下信息：
1. intent: 用户意图 (create_plan, update_status, add_step, get_plan, list_plans, delete_plan 等)
2. parameters: 相关参数
3. context: 上下文信息
4. suggestions: 建议的后续操作

只返回 JSON 格式的结果。"""
        
        response = await self.llm.create(prompt)
        return json.loads(response)

    async def _validate_operation(self, operation: str, params: Dict[str, Any]) -> Dict[str, Any]:
        """使用 LLM 验证操作的合理性。"""
        prompt = f"""请验证以下操作的合理性：

操作：{operation}
参数：{json.dumps(params, ensure_ascii=False, indent=2)}

请分析：
1. 参数是否完整
2. 操作是否合理
3. 是否存在潜在风险
4. 是否需要额外的上下文信息

请以 JSON 格式返回验证结果。"""
        
        response = await self.llm.create(prompt)
        return json.loads(response)

    async def _analyze_plan_structure(self, plan_data: Dict[str, Any]) -> Dict[str, Any]:
        """使用 LLM 分析计划结构。"""
        prompt = f"""请分析以下计划的结构：

计划数据：{json.dumps(plan_data, ensure_ascii=False, indent=2)}

请提供：
1. 计划结构是否合理
2. 是否需要添加额外步骤
3. 步骤之间的依赖关系是否正确
4. 对计划的改进建议
5. 潜在的风险点

请以 JSON 格式返回分析结果。"""
        
        response = await self.llm.create(prompt)
        return json.loads(response)

    async def handle_request(self, request: str) -> Dict[str, Any]:
        """处理用户的自然语言请求。"""
        # 1. 分析请求
        analysis = await self._analyze_request(request)
        
        # 2. 验证操作
        validation = await self._validate_operation(
            analysis["intent"],
            analysis["parameters"]
        )
        
        if not validation["is_valid"]:
            return {
                "status": "error",
                "message": validation["reason"],
                "suggestions": validation["suggestions"]
            }
        
        # 3. 执行相应操作
        try:
            # 根据意图调用相应的 plan_manager 方法
            method = getattr(self.plan_manager, analysis["intent"])
            result = method(**analysis["parameters"])
            
            # 4. 如果是创建或更新操作，进行额外的结构分析
            if analysis["intent"] in ["create_plan", "update_plan_status", "add_step"]:
                structure_analysis = await self._analyze_plan_structure(result["data"])
                result["suggestions"] = structure_analysis.get("suggestions", [])
                result["analysis"] = {
                    "dependencies": structure_analysis.get("dependencies", []),
                    "risks": structure_analysis.get("risks", []),
                    "improvements": structure_analysis.get("improvements", [])
                }
            
            return result
            
        except AttributeError:
            return {
                "status": "error",
                "message": f"未知的操作意图: {analysis['intent']}"
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e),
                "suggestions": analysis.get("suggestions", [])
            }

    async def create_plan(
        self,
        title: str,
        reporter: str,
        steps_data: Optional[List[Step]] = None,
        parent_step_id: Optional[str] = None,
        plan_id_str: Optional[str] = None
    ) -> Dict[str, Any]:
        """创建新计划。"""
        # 1. 使用 LLM 分析计划结构
        analysis_prompt = f"""请分析以下计划的结构：

标题：{title}
步骤：{json.dumps(steps_data, ensure_ascii=False, indent=2) if steps_data else '无'}
父步骤ID：{parent_step_id or '无'}

请提供：
1. 计划结构是否合理
2. 是否需要添加额外步骤
3. 步骤之间的依赖关系是否正确
4. 对计划的改进建议

请以 JSON 格式返回分析结果。"""
        
        analysis = await self.llm.create(analysis_prompt)
        analysis_result = json.loads(analysis)
        
        if not analysis_result["is_valid"]:
            return {
                "status": "error",
                "message": analysis_result["reason"],
                "suggestions": analysis_result["suggestions"]
            }
        
        # 2. 如果分析通过，创建计划
        result = self.plan_manager.create_plan(
            title=title,
            reporter=reporter,
            steps_data=steps_data,
            parent_step_id=parent_step_id,
            plan_id_str=plan_id_str
        )
        
        # 3. 添加 LLM 的建议
        if result["status"] == "success":
            result["suggestions"] = analysis_result.get("suggestions", [])
            
        return result

    async def get_plan(self, plan_id_str: str) -> Dict[str, Any]:
        """获取计划详情。"""
        return self.plan_manager.get_plan(plan_id_str)

    async def list_plans(self) -> Dict[str, Any]:
        """列出所有计划。"""
        return self.plan_manager.list_plans()

    async def delete_plan(self, plan_id_str: str) -> Dict[str, Any]:
        """删除计划。"""
        return self.plan_manager.delete_plan(plan_id_str)

    async def update_plan_status(
        self,
        plan_id_str: str,
        status: PlanStatus
    ) -> Dict[str, Any]:
        """更新计划状态。"""
        return self.plan_manager.update_plan_status(
            plan_id_str=plan_id_str,
            status=status
        )

    async def add_step(
        self,
        plan_id_str: str,
        title: str,
        assignee: str,
        content: str = "",
        insert_after_step_index: Optional[int] = None
    ) -> Dict[str, Any]:
        """添加新步骤。"""
        return self.plan_manager.add_step(
            plan_id_str=plan_id_str,
            title=title,
            assignee=assignee,
            content=content,
            insert_after_step_index=insert_after_step_index
        )

    async def update_step(
        self,
        plan_id_str: str,
        step_index: int,
        update_data: Step
    ) -> Dict[str, Any]:
        """更新步骤信息。"""
        return self.plan_manager.update_step(
            plan_id_str=plan_id_str,
            step_index=step_index,
            update_data=update_data
        )

    async def add_note_to_step(
        self,
        plan_id_str: str,
        step_index: int,
        content: str,
        author: str
    ) -> Dict[str, Any]:
        """添加步骤笔记。"""
        return self.plan_manager.add_note_to_step(
            plan_id_str=plan_id_str,
            step_index=step_index,
            content=content,
            author=author
        ) 