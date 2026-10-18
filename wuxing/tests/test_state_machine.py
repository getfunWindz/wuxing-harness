"""TDD（P0-4 · 状态机形式化）：状态词汇/迁移表 + 已修缺陷不变量守卫。

覆盖映射（缺陷 → 不变量 → 用例）：
  F1 票据断点回写：verdict_fail→failed；cancelled/needs_confirm 不回写（保持 running）
  F2 publish 状态机：仅 proposed→ready；终态不可被 publish 重置
  REAL-14/W5.1/W5.2：见既有回归（test_shell_manager/test_resume），本模块只测词汇与表
"""
import types


def test_status_vocab_same_source():
    """状态词汇单一来源：票据常量与实现一致；各层状态互不越界。"""
    from wuxing import state_machine as sm
    from wuxing import tickets
    assert tuple(tickets.STATUSES) == sm.TICKET_STATUSES
    assert set(sm.UNIT_RETRIABLE).isdisjoint(sm.UNIT_TERMINAL)
    assert set(sm.UNIT_TERMINAL) | set(sm.UNIT_RETRIABLE) == set(sm.UNIT_STATES)
    assert set(sm.RUN_NONTERMINAL) <= set(sm.RUN_STATES)


def test_ticket_transition_table():
    """F2 不变量：publish 仅 proposed→ready；reset 仅终态→ready；running 不可重置。"""
    from wuxing.state_machine import can_transition_ticket as ok
    assert ok("proposed", "ready")
    assert not ok("proposed", "running")      # 未发布不得直接执行
    assert ok("ready", "running")
    assert ok("running", "done") and ok("running", "failed")
    for st in ("done", "failed", "cancelled"):
        assert ok(st, "ready")                # reset 重跑
        assert not ok(st, "running")          # 终态不得直接执行
    assert not ok("running", "ready")         # 执行中禁止重置
    assert not ok("failed", "done")           # 回写只经 running


def test_unit_reschedule_rules():
    """单元层：ok/rejected 终态不再调度；failed/needs_confirm/cancelled 可重跑。"""
    from wuxing.state_machine import can_reschedule_unit as ok
    assert not ok("ok") and not ok("rejected")
    assert ok("failed") and ok("needs_confirm") and ok("cancelled")
    assert not ok("")


def test_task_status_aggregation_membership_and_rules():
    """run 聚合规则（F1/W5.1 基础不变量）：结果 ∈ RUN_STATES 且语义正确。"""
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    from wuxing.state_machine import RUN_STATES

    def U(uid, dom, st, vf=False):
        return UnitResult(unit_id=uid, domain_id=dom, status=st, verdict_fail=vf)

    cases = [
        ([U("F-1", "verify", "ok"), U("F-2", "execute", "failed")], "done"),   # 验收通过=done（降级）
        ([U("F-1", "verify", "ok", vf=True)], "failed"),                       # F1：verdict_fail→failed
        ([U("F-1", "verify", "needs_confirm")], "pending"),                    # W5.1：挂起→pending
        ([U("F-1", "execute", "cancelled")], "cancelled"),                     # 取消优先
        ([U("F-1", "execute", "rejected")], "failed"),                         # 驳回→failed
        ([U("F-1", "execute", "ok"), U("F-2", "execute", "failed")], "partial"),  # 无 verify 回落
        ([U("F-1", "execute", "ok")], "done"),
    ]
    for units, expect in cases:
        got = Engine._task_status(units)
        assert got == expect, (units, got, expect)
        assert got in RUN_STATES


def test_writeback_ticket_transitions_follow_table(tmp_path):
    """F1 不变量：票据回写迁移必须在表内；非终态（cancelled/needs_confirm）不回写。"""
    from wuxing import tickets
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    t1 = tickets.create(tmp_path, title="A")
    t2 = tickets.create(tmp_path, title="B")
    t3 = tickets.create(tmp_path, title="C")
    tickets.update(tmp_path, t1["id"], {"status": "running"})
    tickets.update(tmp_path, t2["id"], {"status": "running"})
    tickets.update(tmp_path, t3["id"], {"status": "running"})

    def U(uid, st, vf=False):
        return UnitResult(unit_id=uid, domain_id="verify" if uid.endswith("-v")
                          else "execute", status=st, verdict_fail=vf)

    ns = types.SimpleNamespace(workdir=tmp_path)
    changed = Engine._writeback_tickets(ns, [
        U("F-T1", "ok"), U("F-T1-v", "ok"),                    # → done
        U("F-T2", "ok"), U("F-T2-v", "ok", vf=True),           # → failed（verdict_fail）
        U("F-T3", "cancelled"), U("F-T3-v", "needs_confirm"),  # → 不回写（保持 running）
    ])
    st = {t["id"]: t["status"] for t in tickets.load(tmp_path)}
    assert st == {"T-1": "done", "T-2": "failed", "T-3": "running"}
    assert dict(changed) == {"T-1": "done", "T-2": "failed"}


def test_update_is_low_level_primitive(tmp_path):
    """Q3=b 契约：update 不做迁移校验（白名单字段直写）；纪律在操作层。

    说明性断言：表外目标不被 update 拦截——若未来改为选项 a（接线校验），
    本测试即红灯，需同步决策记录与调用点。
    """
    from wuxing import tickets
    t = tickets.create(tmp_path, title="A")
    out = tickets.update(tmp_path, t["id"], {"status": "done"})
    assert out["status"] == "done"


def test_operation_layer_transitions_stay_in_table(tmp_path, monkeypatch):
    """Q3 守卫（决策 b）：操作层产生的迁移必须落在强约束表内。

    update 为低层原语（不校验）；纪律由 publish/reset/回写承担——本测试
    驱动真实流程并以 spy 记录每次 update 的 (src, dst)，逐边断言合法。
    """
    from wuxing import tickets
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    from wuxing.state_machine import can_transition_ticket

    edges = []
    real_update = tickets.update

    def spy(workdir, tid, patch):
        src = str((tickets.find(workdir, tid) or {}).get("status") or "")
        res = real_update(workdir, tid, patch)
        dst = str((res or {}).get("status") or "")
        if src and dst:
            edges.append((src, dst))
        return res

    monkeypatch.setattr(tickets, "update", spy)

    t = tickets.create(tmp_path, title="A")
    tickets.publish(tmp_path)                                  # proposed → ready
    tickets.update(tmp_path, t["id"], {"status": "running"})  # 编排入执行
    ns = types.SimpleNamespace(workdir=tmp_path)
    Engine._writeback_tickets(ns, [
        UnitResult(unit_id="F-T1", domain_id="execute", status="ok"),
        UnitResult(unit_id="F-T1-v", domain_id="verify", status="ok"),
    ])                                                          # running → done
    tickets.reset(tmp_path, [t["id"]])                         # done → ready
    tickets.reset(tmp_path, [t["id"]])                         # ready → ready（幂等）
    assert edges, "未捕获任何迁移"
    for src, dst in edges:
        assert can_transition_ticket(src, dst), f"表外迁移：{src}→{dst}"
    for edge in (("proposed", "ready"), ("ready", "running"),
                 ("running", "done"), ("done", "ready")):
        assert edge in edges, edge
