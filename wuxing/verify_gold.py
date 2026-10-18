"""C3（第二轮计划 §2 · 评估 P1）：verify 金标校准——判定抽取 + 一致率统计。

背景：verify 输出为「参考性评分 + 全面审查触发」（用户裁决 2026-09-12），
不承担机械性改正。金标校准用「已知应通过/应失败」的样本检验 verify 判定与
金标的一致率，量化 verify 可信度（评测九步之「金标」缺口）。

金标声明（`eval/real/tasks.json` 任务可选字段）：
    "verify_gold": {"expect": "pass"|"fail", "note": "..."}

判定口径（诚实、机械）：
  - 优先用单元结果：任一 `verdict_fail` 或 failed/rejected 单元 → fail；
  - **回退路径**（无结构化条目/单元）：按整体状态——done → pass；
    failed/partial → fail；cancelled/error 等不可判 → 空串（不计入分母）。
"""
import logging

logger = logging.getLogger(__name__)

_FAIL_UNIT_STATUSES = ("failed", "rejected")
_VERDICTS = ("pass", "fail")


def extract_verdict(units=None, status: str = "") -> str:
    """从单元结果（优先）或整体状态抽取 verify 口径判定（不可判 → ""）。"""
    us = list(units or ())
    if us:
        if any(getattr(u, "verdict_fail", False) for u in us):
            return "fail"
        if any(str(getattr(u, "status", "")) in _FAIL_UNIT_STATUSES for u in us):
            return "fail"
        return "pass"
    s = str(status or "")
    if s == "done":
        return "pass"
    if s in ("failed", "partial"):
        return "fail"
    return ""  # 不可判（cancelled/error/running/空）——不计入分母


def gold_agreement(task, units=None, *, status: str = "") -> dict | None:
    """单任务金标一致（无金标声明/声明非法 → None——不造假）。"""
    if not isinstance(task, dict):
        return None
    gold = task.get("verify_gold")
    if not isinstance(gold, dict) or gold.get("expect") not in _VERDICTS:
        return None
    actual = extract_verdict(units, status=status)
    return {"task_id": str(task.get("id", "")),
            "expect": str(gold["expect"]), "actual": actual,
            "agree": actual == gold["expect"],
            "note": str(gold.get("note", ""))}


def agreement_summary(rows) -> dict:
    """一致率汇总：decided 为分母；不可判（actual=""）单列（诚实口径）。"""
    items = [r for r in (rows or ()) if r]
    decided = [r for r in items if r.get("actual") in _VERDICTS]
    agreed = sum(1 for r in decided if r["agree"])
    return {"gold_total": len(items), "decided": len(decided),
            "agreed": agreed,
            "rate": (agreed / len(decided)) if decided else None,
            "undecided": len(items) - len(decided),
            "items": items}
