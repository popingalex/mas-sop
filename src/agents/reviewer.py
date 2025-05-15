import json
from typing import Any, Dict

class Reviewer:
    def __init__(self, model_client, plan_manager, artifact_manager=None):
        self.model_client = model_client
        self.plan_manager = plan_manager
        self.artifact_manager = artifact_manager

    async def run(self, plan_id: str) -> Dict[str, Any]:
        """
        结构化输出计划执行总结，返回JSON对象。
        """
        plan = self.plan_manager.get_plan(plan_id)
        # 这里可以根据实际业务补充更多上下文信息
        prompt = f"""
你是一个专业的SOP Reviewer，请根据计划ID为 {plan_id} 的执行过程，输出结构化总结。
严格按照如下JSON格式输出：
{{
  "plan_id": "计划ID",
  "summary": "对整个计划执行过程的简要总结",
  "key_findings": ["主要发现1", "主要发现2"],
  "improvements": ["可改进点1", "可改进点2"],
  "lessons_learned": ["经验教训1", "经验教训2"]
}}
如无内容可填请用空字符串或空数组，不要省略字段。
"""
        # 假设model_client有一个async方法generate，返回LLM输出
        response = await self.model_client.generate(prompt)
        try:
            result = json.loads(response)
        except Exception:
            result = {
                "plan_id": plan_id,
                "summary": "",
                "key_findings": [],
                "improvements": [],
                "lessons_learned": []
            }
        return result 