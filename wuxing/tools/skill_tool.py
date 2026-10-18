"""load_skill 工具（SK T2：碎片级被动调用——渐进披露第二层）。"""
from wuxing.protocols import Tool, ToolResult


class LoadSkillTool(Tool):
    def __init__(self, skills):
        self._skills = skills  # SkillRegistry（Engine 装配）

    def name(self):
        return "load_skill"

    def description(self):
        return "加载指定技能的完整内容（渐进披露详情层——按需使用）"

    def input_schema(self):
        # L2-2 修正：required 与 properties/execute 对齐（旧 schema required=["name"]
        # 与 skill_name 不一致——参数校验层暴露此不一致，手工校验曾掩盖）
        return {"type": "object", "properties": {
            "skill_name": {"type": "string"}}, "required": ["skill_name"]}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, skill_name="", **kw):
        if not skill_name:
            return ToolResult(status="error", tool_name=self.name(),
                              error="load_skill: skill_name 必填")
        if self._skills is None:
            return ToolResult(status="error", tool_name=self.name(),
                              error="load_skill: 技能注册表未装配")
        from wuxing.skill_state import is_disabled
        if is_disabled(skill_name):
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"load_skill: 技能已停用：{skill_name}")
        # E2-1（B5）：模型调用开关——仅用户技能不可由模型加载（fail-closed）
        try:
            info = (self._skills.index() or {}).get(skill_name)
        except Exception:
            info = None
        if info is not None and info.get("model_invocable", True) is False:
            return ToolResult(
                status="error", tool_name=self.name(),
                error=(f"load_skill: 技能不可由模型调用"
                       f"（model_invocable=false）：{skill_name}"))
        detail = self._skills.get_detail(skill_name)
        if detail is None:
            return ToolResult(status="error", tool_name=self.name(),
                              error=f"load_skill: 未找到技能 {skill_name}")
        content = detail["content"]
        if detail["scripts"]:
            content += f"\n\n（脚本：{', '.join(detail['scripts'])}——位于技能目录 scripts/）"
        # C2：收益台账（复用计数；观测不阻断）
        from wuxing.skill_ledger import record_event
        record_event(getattr(self._skills, "user_dir", None), "loaded",
                     skill_name, source="load_skill")
        return ToolResult(status="ok", content=content, tool_name=self.name())
