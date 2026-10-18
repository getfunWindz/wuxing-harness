"""delegate 工具（3c：DSH subagent 模式 × WUXING 生态——关口-子智能体缺失环节）。

行为：{goal, domain?} → 受控子 Runner 单 loop（独立会话上下文——Q3 双层混合）
    → ToolResult(ok, content=摘要 + artifacts 路径)（文件=真理：跨界只走产物）

护栏（独特生态，不照搬 DSH）：
  深度 2：delegate 在子 Runner 工具集自动剔除（防递归爆炸）
  预算继承：子任务预算 min(4, 父剩余)——子任务调用数计入父单元（总成本有界）
  不经过 DAG：子任务=单 loop 摘要（DAG 级子智能体为远期"动态再分解"构想）

溯源（3c 决策 C）：子任务与父单元共用 provenance 链（parent 链接）。
"""

import logging
import threading

from wuxing.protocols import Tool, ToolResult

logger = logging.getLogger(__name__)


class DelegateTool(Tool):
    """子任务委托（挂 execute/plan 域白名单——用户决策 A）。

    runner 由 Engine 注入（延迟装配——工具构造时引擎未完全就绪）；
    ledger 为溯源链（与父 Runner 共用）。
    """
    def __init__(self, delegate_runner_factory=None, ledger=None,
                 parent_unit_id: str = "", deliverable_kinds=None):
        self._factory = delegate_runner_factory  # (goal, domain) -> Runner
        self._ledger = ledger
        self._parent_unit_id = parent_unit_id  # 溯源父子链（Engine 装配时注入）
        self._deliverable_kinds = deliverable_kinds  # D1：域→交付物类型回调
        # L0-3（审查 B1/R2-A2）：深度计数 + 锁移入本实例——
        # 检查与递增同一临界区（原子），异常也释放（try/finally）。
        # 此前计数在 engine（无锁：P16 并发竞态；无 finally：异常泄漏）。
        self._depth = 0
        self._depth_lock = threading.Lock()
        # E3-2（P1/H3）：Subagent 事件发射器（runner 调用前注入；缺省零行为）
        self._emit_event = None

    # 分级放行（2026-09-11 设计）：委托工具内部会跑子 Runner 工具——不占全局额度
    reentrant = True

    def _emit(self, event) -> None:
        """E3-2（P1）：Subagent 事件发射（未注入/失败 → 零阻断）。"""
        if self._emit_event is None:
            return
        try:
            self._emit_event(event)
        except Exception as exc:
            logger.debug("Subagent 事件发射失败（不阻断）：%s", exc)

    def name(self): return "delegate"
    def description(self): return ("将子目标委托给受控子智能体执行（独立会话，产物入库）；"
                                   "read_only=True 时为只读勘察（不派发写/执行类工具）")
    def input_schema(self): return {"type": "object", "properties": {
        "goal": {"type": "string"}, "domain": {"type": "string"},
        "read_only": {"type": "boolean"}},
        "required": ["goal"]}

    def permission(self):
        return {"read": True, "write": True, "execute": True,
                "network": False, "destructive": False}

    def execute(self, goal="", domain=None, read_only=False, **kw):
        if not goal:
            return ToolResult(status="error", tool_name=self.name(),
                              error="delegate: goal 必填")
        if self._factory is None:
            return ToolResult(status="error", tool_name=self.name(),
                              error="delegate: 未装配委托工厂（引擎上下文缺失）")
        with self._depth_lock:
            if self._depth >= 2:
                return ToolResult(status="error", tool_name=self.name(),
                                  error="delegate: 委托被拒绝（深度/预算护栏）")
            self._depth += 1
        try:
            # E3-1/R4（CU2）：只读派生——仅在 True 时透传（旧两参工厂兼容）
            fab = (self._factory(goal, domain, read_only=True)
                   if read_only else self._factory(goal, domain))
            if fab is None:
                return ToolResult(status="error", tool_name=self.name(),
                                  error="delegate: 委托被拒绝（深度/预算护栏）")
            runner, _release = fab
            # D1：子任务交付物语义注入（按目标域机械映射——同主碎片 L4 修复）
            _dlv = []
            if self._deliverable_kinds is not None:
                try:
                    _dlv = list(self._deliverable_kinds(runner._delegate_domain))
                except Exception:
                    _dlv = []
            # E3-2（P1/H3）：子代理起止事件（发射器缺省 None → 零行为）
            from wuxing.events import SubagentStarted, SubagentStopped
            _sub_domain = str(getattr(runner, "_delegate_domain", "") or "")
            self._emit(SubagentStarted(parent_unit_id=str(self._parent_unit_id),
                                       goal=str(goal or ""),
                                       domain=_sub_domain))
            _sub_status = "error"
            _sub_artifacts = 0
            try:
                res = runner.run_unit(f"delegate-{goal[:12]}", runner._delegate_domain, {
                    "goal": goal,
                    "task": goal,
                    "fragment_key": goal,
                    "deliverables": _dlv,
                })
                _sub_status = str(getattr(res, "status", "") or "")
                _sub_artifacts = len(list(getattr(res, "artifacts", None) or []))
            finally:
                self._emit(SubagentStopped(
                    parent_unit_id=str(self._parent_unit_id),
                    goal=str(goal or ""), domain=_sub_domain,
                    status=_sub_status, artifacts=_sub_artifacts))
            artifacts = [a.path for a in res.artifacts]
            # 溯源：子任务记录（parent = 发起单元）
            if self._ledger is not None:
                self._ledger.record(
                    unit_id=f"delegate-{goal[:12]}", parent_id=self._parent_unit_id,
                    task_text=goal, goal=goal, domain=runner._delegate_domain,
                    model=getattr(runner, "_delegate_model", ""), status=res.status,
                    artifacts=artifacts)
            summary = (f"[delegate] {goal[:40]}... -> {res.status}"
                       + (f" | 产物: {', '.join(artifacts)}" if artifacts else "")
                       + (f" | 错误: {res.error}" if res.error else ""))
            result = ToolResult(status="ok" if res.status == "ok" else "error",
                                content=summary, tool_name=self.name())
            result.child_calls = getattr(runner, "_calls", 0)  # 预算继承计数
            return result
        finally:
            with self._depth_lock:
                self._depth -= 1
