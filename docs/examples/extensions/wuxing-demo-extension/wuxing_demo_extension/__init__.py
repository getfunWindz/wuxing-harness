"""wuxing-demo-extension：WUXING 扩展示例包（entry-points 分发示范）。

演示三类注册面：
  1. 提示词段（execute 域）——告知模型本扩展提供的能力；
  2. 自定义工具（demo_text_stats：只读、workspace 包含性检查）；
  3. 事件钩子（TaskDone 只读观察 → api.log）。

纪律：扩展 = 进程内完全信任代码——只安装可信来源（同 harness 扩展语义）。
"""
from __future__ import annotations


def register(api):
    """入口点：pyproject [project.entry-points."wuxing.extensions"] → 本函数。

    装载器在 register() 成功返回后统一提交（事务性：中途抛错 = 零生效）。
    """
    workdir = api.workdir.resolve()

    # ── 1) 提示词段（execute 域）──
    api.add_prompt_segment(
        "已加载 wuxing-demo-extension：文本类统计请优先调用 demo_text_stats 工具。",
        domains=("execute",))

    # ── 2) 事件钩子（只读观察；返回值忽略）──
    def _observe(event):
        name = type(event).__name__
        detail = getattr(event, "status", "") or getattr(event, "unit_id", "")
        api.log(f"{name} {detail}".strip())

    api.on("TaskDone", _observe)

    # ── 3) 自定义工具（只读；workspace 包含性检查）──
    def _text_stats(path=""):
        p = (workdir / str(path)).resolve()
        if p != workdir and workdir not in p.parents:
            return {"error": f"outside workspace: {path}"}
        try:
            text = p.read_text(encoding="utf-8")
        except OSError as e:
            return {"error": f"{type(e).__name__}: {e}"}
        return {"path": str(path), "lines": len(text.splitlines()),
                "words": len(text.split()), "chars": len(text)}

    api.register_tool(
        name="demo_text_stats",
        description="统计工作区内文本文件的行数/词数/字符数（示例扩展工具，只读）",
        parameters={"type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"]},
        execute=_text_stats,
        domains=("execute",),
        permission={"read": True},
    )
