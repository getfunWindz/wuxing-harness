"""状态机规格（P0-4 · 评估行动项）：四层状态词汇 + 迁移合法表（单一事实源）。

层级与职责：
  - workspace（壳 · manager）：idle ⇄ running —— 每工作区一个活动任务/命令操作；
  - run（任务运行 · TaskResult/_Run.status）：running/pending → 终态（壳层再加 error/rolled_back）；
  - unit（单元结果 · UnitResult.status）：ok/rejected 终态；failed/needs_confirm/needs_answer/cancelled 可重跑；
  - ticket（票据 · tickets.STATUSES）：proposed → ready → running → done/failed；终态可重置回 ready。

纪律：本模块是状态词汇与**强约束迁移**（票据/单元重跑/工作区互斥）的单一来源；
已修缺陷（F1 票据断点回写 / F2 publish 状态机 / REAL-14 确认清理时序 /
W5.1 挂起可见 / W5.2 工作区互斥）作为不变量由 `wuxing/tests/test_state_machine.py`
与既有回归共同守卫（映射见 docs/WUXING_状态机与迁移表_2026-09-26.md）。
票据迁移纪律（Q3 决策 b）：`tickets.update` 为低层原语（不校验）；约束由操作层
（publish/reset/回写）承担，守卫测试 `test_operation_layer_transitions_stay_in_table`。
"""
from __future__ import annotations

# ---- workspace（壳：EngineManager） ----
WORKSPACE_STATES = ("idle", "running")

# ---- unit（UnitResult.status） ----
# E2-5（A10）：needs_answer = 提问挂起（内容级信息补充；与 needs_confirm 语义不同）
UNIT_STATES = ("ok", "failed", "needs_confirm", "needs_answer", "cancelled",
               "rejected")
UNIT_TERMINAL = ("ok", "rejected")                 # 终态：resume/确认续跑时跳过
UNIT_RETRIABLE = ("failed", "needs_confirm", "needs_answer", "cancelled")  # 可重跑（受 attempts 上限约束）


def can_reschedule_unit(status: str) -> bool:
    """单元结果状态是否允许再次调度（resume/确认续跑）。"""
    return str(status or "") in UNIT_RETRIABLE


# ---- ticket（tickets.STATUSES） ----
TICKET_STATUSES = ("proposed", "ready", "running", "done", "failed", "cancelled")
# 强约束迁移表：publish=proposed→ready；编排=ready→running；回写=running→done/failed；
# reset=done/failed/cancelled→ready（ready→ready 幂等）。
TICKET_TRANSITIONS = {
    "proposed": {"ready"},
    "ready": {"ready", "running"},
    "running": {"done", "failed"},
    "done": {"ready"},
    "failed": {"ready"},
    "cancelled": {"ready"},
}


def can_transition_ticket(src: str, dst: str) -> bool:
    """票据迁移合法性（publish/reset/回写共用口径）。"""
    return dst in TICKET_TRANSITIONS.get(str(src or ""), set())


# ---- run（TaskResult.status / _Run.status） ----
# 引擎聚合（_task_status）产出的状态；壳层另有 running/error/rolled_back。
RUN_STATES = ("running", "pending", "done", "failed", "partial", "cancelled",
              "needs_design", "error", "rolled_back")
RUN_NONTERMINAL = ("running", "pending")


def is_run_terminal(status: str) -> bool:
    s = str(status or "")
    return s in RUN_STATES and s not in RUN_NONTERMINAL
