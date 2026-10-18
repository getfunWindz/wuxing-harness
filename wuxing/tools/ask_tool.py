"""E2-5（A10）提问工具（`ask_user`）：执行中向用户提问（挂起式 Phase 1）。

纪律（计划 `docs/plans/2026-10-03-wuxing-user-question.md` Q1/Q6/Q7）：
- 1-3 题；每题 title ≤200 字符 + 2-4 选项（首选项=推荐答案语义）+ 可选 multi；
- 挂起语义：返回 status="needs_answer"（runner 拦截 → 单元挂起 → 壳问题卡）；
- fail-closed：无答复不自动选推荐答案（engine/runner 侧保证）；
- 上限：每单元 ≤3 次（runner 计数拦截）；同批独占（runner 拦截）；
- 边界（Q2）：信息补充 ≠ 确认门（不改准入链）；设计域不注册（单通道）。
"""
from wuxing.protocols import Tool, ToolResult

MAX_QUESTIONS = 3
MAX_ASKS_PER_UNIT = 3   # 每单元提问上限（runner 拦截计数）
MIN_OPTIONS, MAX_OPTIONS = 2, 4
MAX_TITLE_CHARS = 200


class AskUserTool(Tool):
    """向用户提问（挂起等待答复；答案经 engine.answer_unit 注入后续跑）。"""

    def __init__(self):
        self.last_questions: list = []   # 最近一次规范化题面（runner 拦截时读取）

    def name(self):
        return "ask_user"

    def description(self):
        return ("向用户提问（遇歧义/关键决策且无法从上下文与文件中推断时使用）。"
                f"1-{MAX_QUESTIONS} 题，每题 title ≤{MAX_TITLE_CHARS} 字符 + "
                f"{MIN_OPTIONS}-{MAX_OPTIONS} 个选项（首选项=推荐答案）；"
                "用户可选选项或自由作答。提问后本单元挂起等待答复——"
                "**无答复不会自动采用推荐项**；每单元至多 3 次。"
                "信息补充用本工具；单元准入批准仍走确认门（两者不互替）。"
                "提问要用用户能看懂的话：说清「要决定什么 + 每个选项会带来什么结果」；"
                "不要用内部术语（碎片/域/单元/指纹）；语言跟随用户界面语言。")

    def input_schema(self):
        return {"type": "object",
                "properties": {"questions": {"type": "array",
                                             "items": {"type": "object"}}},
                "required": ["questions"]}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, questions=None, **kw):
        err = self._validate(questions)
        if err:
            return ToolResult(status="error", tool_name=self.name(), error=err)
        self.last_questions = [
            {"title": str(q.get("title")).strip(),
             "options": [str(o).strip() for o in (q.get("options") or [])],
             "multi": bool(q.get("multi", False))}
            for q in questions]
        parts = []
        for i, q in enumerate(self.last_questions):
            parts.append(f"问题{i + 1}：{q['title']}"
                         f"（选项：{' / '.join(q['options'])}）")
        return ToolResult(status="needs_answer", tool_name=self.name(),
                          content="；".join(parts))

    @staticmethod
    def _validate(questions) -> str:
        """loud 校验：返回错误文案（空串=合法）；不得静默接受非法题面。"""
        if not isinstance(questions, list):
            return "param: questions 必须为数组"
        if not (1 <= len(questions) <= MAX_QUESTIONS):
            return (f"questions 数量非法（{len(questions)}）"
                    f"——须 1-{MAX_QUESTIONS} 题")
        for i, q in enumerate(questions):
            if not isinstance(q, dict):
                return f"questions[{i}] 必须为对象"
            title = q.get("title")
            if not isinstance(title, str) or not title.strip():
                return f"questions[{i}].title 不能为空"
            if len(title) > MAX_TITLE_CHARS:
                return (f"questions[{i}].title 超长"
                        f"（{len(title)} > {MAX_TITLE_CHARS} 字符）")
            opts = q.get("options")
            if not isinstance(opts, list):
                return f"questions[{i}].options 必须为数组"
            if not (MIN_OPTIONS <= len(opts) <= MAX_OPTIONS):
                return (f"questions[{i}].options 数量非法（{len(opts)}）"
                        f"——须 {MIN_OPTIONS}-{MAX_OPTIONS} 项")
            for j, o in enumerate(opts):
                if not isinstance(o, str) or not o.strip():
                    return f"questions[{i}].options[{j}] 不能为空"
            multi = q.get("multi", False)
            if not isinstance(multi, bool):
                return f"questions[{i}].multi 须为布尔"
        return ""
