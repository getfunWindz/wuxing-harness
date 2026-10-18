"""上下文窗口解析（骨架分期 P1/F-4：自 engine.py 提取——消除反向互引）。

来源：`wuxing/engine.py`（2026-10-04 迁移，函数体逐字节保持）。
使用方：engine（任务级窗口）、runner（单元装配）、context_preview（预览口径）。
"""
import logging

logger = logging.getLogger(__name__)


def resolve_context_window(spec, table=None, default=None) -> int:
    """模型上下文窗口解析链（2026-09-11 设计）：

    provider/官方表命中 → 配置表 → 默认兜底（DeepSeek /models 不返回窗口——实测）。
    """
    official = {"deepseek-flash": 1_000_000, "deepseek-v4-pro": 1_000_000}
    name = ""
    if isinstance(spec, str):
        name = spec.split(":", 1)[-1]
    elif isinstance(spec, dict):
        name = str(spec.get("model", ""))
    merged = dict(official)
    merged.update(table or {})
    return int(merged.get(name, default if default is not None else 200_000))
