"""G8-M1：票据认领原语（claim/unclaim/release + 事件重建 + 路径级锁）。

设计：`docs/WUXING_认领制与并行会话_G8_设计_2026-09-26.md`。
"""
import json
import threading
import typing

import pytest

from wuxing import tickets


def _events(workdir):
    p = workdir / ".wuxing" / "tickets.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
            if x.strip()]


def test_filelock_same_path_shared(tmp_path):
    from wuxing.filelock import lock_for
    a = lock_for(tmp_path / "x.jsonl")
    b = lock_for(tmp_path / "x.jsonl")
    c = lock_for(tmp_path / "y.jsonl")
    assert a is b
    assert a is not c


def test_claim_unclaim_lifecycle(tmp_path):
    t = tickets.create(tmp_path, title="甲")
    tid = t["id"]
    claimed = tickets.claim(tmp_path, tid, by="sess-a")
    assert claimed["claimed_by"] == "sess-a"
    assert claimed["claimed_at"]
    # 事件重建（新读）
    assert tickets.find(tmp_path, tid)["claimed_by"] == "sess-a"
    # 同人幂等
    again = tickets.claim(tmp_path, tid, by="sess-a")
    assert again["claimed_by"] == "sess-a"
    # 释放
    tickets.unclaim(tmp_path, tid, by="sess-a", reason="manual")
    assert not tickets.find(tmp_path, tid).get("claimed_by")
    events = [r["event"] for r in _events(tmp_path)]
    assert "claimed" in events and "unclaimed" in events
    assert events.count("claimed") == 1  # 幂等不重复写


def test_claim_conflict_with_holder(tmp_path):
    t = tickets.create(tmp_path, title="甲")
    tickets.claim(tmp_path, t["id"], by="sess-a")
    with pytest.raises(tickets.TicketClaimedError) as ei:
        tickets.claim(tmp_path, t["id"], by="sess-b")
    assert "sess-a" in str(ei.value)
    assert ei.value.holder == "sess-a"


def test_claim_unknown_returns_none(tmp_path):
    assert tickets.claim(tmp_path, "T-99", by="s") is None
    assert tickets.unclaim(tmp_path, "T-99", by="s") is None


def test_claim_terminal_rejected(tmp_path):
    t = tickets.create(tmp_path, title="甲")
    tickets.update(tmp_path, t["id"], {"status": "done"})
    with pytest.raises(ValueError):
        tickets.claim(tmp_path, t["id"], by="s")


def test_terminal_update_releases_claim(tmp_path):
    t = tickets.create(tmp_path, title="甲")
    tickets.claim(tmp_path, t["id"], by="sess-a")
    tickets.update(tmp_path, t["id"], {"status": "running"})
    assert tickets.find(tmp_path, t["id"])["claimed_by"] == "sess-a"
    tickets.update(tmp_path, t["id"], {"status": "done"})
    cur = tickets.find(tmp_path, t["id"])
    assert not cur.get("claimed_by")
    events = [r["event"] for r in _events(tmp_path)]
    assert "released" in events


def test_append_locked_no_lost_events(tmp_path):
    t = tickets.create(tmp_path, title="甲")
    tid = t["id"]

    def worker(i):
        tickets.update(tmp_path, tid, {"error": f"e{i}"})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    events = [r for r in _events(tmp_path) if r["event"] == "updated"]
    assert len(events) == 20


# ---------- Task 2：就绪集与认领视图 ----------

def test_ready_ids_excludes_claimed_terminal_and_unmet_deps(tmp_path):
    a = tickets.create(tmp_path, title="甲")
    b = tickets.create(tmp_path, title="乙", deps=[a["id"]])
    c = tickets.create(tmp_path, title="丙")
    tickets.publish(tmp_path)  # 全部 proposed → ready
    # b 依赖 a 未 done → 不就绪
    assert set(tickets.ready_ids(tmp_path)) == {a["id"], c["id"]}
    tickets.update(tmp_path, a["id"], {"status": "done"})
    ids = set(tickets.ready_ids(tmp_path))
    assert b["id"] in ids and c["id"] in ids
    # 认领 → 移出就绪集
    tickets.claim(tmp_path, c["id"], by="sess-a")
    assert c["id"] not in set(tickets.ready_ids(tmp_path))
    # 终态 → 移出
    tickets.unclaim(tmp_path, c["id"], by="sess-a")
    tickets.update(tmp_path, c["id"], {"status": "cancelled"})
    ids2 = set(tickets.ready_ids(tmp_path))
    assert c["id"] not in ids2 and b["id"] in ids2


def test_claims_and_note(tmp_path):
    t = tickets.create(tmp_path, title="甲")
    tickets.publish(tmp_path)
    tickets.claim(tmp_path, t["id"], by="sess-a")
    claims = tickets.claims(tmp_path)
    assert len(claims) == 1
    assert claims[0]["id"] == t["id"]
    assert claims[0]["by"] == "sess-a"
    assert isinstance(claims[0]["age_s"], (int, float))
    note = tickets.claims_note(tmp_path, stale_after_s=0)
    assert "[票据认领]" in note
    assert t["id"] in note and "sess-a" in note
    assert "可能陈旧" in note
    assert "确认" in note
    # 无认领 → 空注记
    tickets.unclaim(tmp_path, t["id"], by="sess-a")
    assert tickets.claims_note(tmp_path) == ""


# ---------- Task 3：引擎接线 ----------

class _StubLlm:
    """按调用序返回预设回复的 stub（记录 messages；原生 tools）。"""
    replies: typing.ClassVar[list] = []

    def __init__(self):
        self.messages_seen: list = []

    def name(self): return "claims-stub"

    def spec(self): return "claims-stub"

    def supports_native_tools(self): return True

    def chat(self, messages, tools=None):
        self.messages_seen.append([dict(m) for m in messages])
        from wuxing.llm.tool_results import ToolCallResult
        text = self.replies.pop(0) if self.replies else "完成声明：已完成"
        return ToolCallResult(text=text, tool_calls=[])


def _theroad_engine(workdir):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.session_modes import save as save_mode
    save_mode(workdir, "conversation-w.jsonl", "theroad", "")
    llm = _StubLlm()
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=workdir,
                 llm=llm, auto_confirm=True)
    return eng, llm


def test_design_round_injects_claims_note(tmp_path):
    eng, llm = _theroad_engine(tmp_path)
    t = tickets.create(tmp_path, title="甲")
    tickets.publish(tmp_path)
    tickets.claim(tmp_path, t["id"], by="sess-a")
    _StubLlm.replies = ["已完成侦察。\n【事实】\n- 无\n"]
    from wuxing.conversation import ConversationState
    conv = ConversationState(tmp_path / ".wuxing" / "conversation-w.jsonl")
    eng.run_task("继续设计", conversation=conv)
    blob = "\n".join(str(m.get("content", ""))
                     for batch in llm.messages_seen for m in batch)
    assert "[票据认领]" in blob and t["id"] in blob


def test_engine_execution_claims_and_skips_others(tmp_path):
    eng, _llm = _theroad_engine(tmp_path)
    from wuxing import design_state, spec_doc
    from wuxing.map_doc import write_sections
    write_sections(tmp_path, destination="目标", route="- [ ] 实现")
    e = spec_doc.write(tmp_path, title="规格", sections={"problem": "p"})
    design_state.save(tmp_path, {"spec_slug": e["slug"], "spec_path": e["path"]})
    a = tickets.create(tmp_path, title="甲", acceptance=["可用"])
    b = tickets.create(tmp_path, title="乙", acceptance=["可用"])
    tickets.publish(tmp_path)
    tickets.claim(tmp_path, a["id"], by="sess-other")
    _StubLlm.replies = ["完成声明：已完成"] * 10
    from wuxing.conversation import ConversationState
    conv = ConversationState(tmp_path / ".wuxing" / "conversation-w.jsonl")
    res = eng.run_task("交给执行", on_event=[].append, conversation=conv)
    # 跳过他人认领票（报告注记）
    assert "[认领守卫]" in res.report
    assert a["id"] in res.report
    # b 被执行并回写终态
    tb = tickets.find(tmp_path, b["id"])
    assert tb["status"] in ("done", "failed")
    assert "F-T2" in {f["fragment_id"] for f in res.fragments}
    # 认领历史：本会话认领过（随后终态自动释放）
    rows = _events(tmp_path)
    claimed_by = {r.get("by") for r in rows if r.get("event") == "claimed"}
    assert "conversation-w.jsonl" in claimed_by
    assert any(r["event"] == "released" for r in rows)
    # a 仍被他人认领（未被动过）
    assert tickets.find(tmp_path, a["id"])["claimed_by"] == "sess-other"


def test_unclaim_ticket_tool_and_domain_contract(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.domains.defaults import DESIGN_DOMAIN
    from wuxing.engine import Engine
    assert "unclaim_ticket" in DESIGN_DOMAIN.tool_whitelist
    notes = "".join(DESIGN_DOMAIN.quality_notes)
    assert "[票据认领]" in notes and "unclaim_ticket" in notes
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path)
    assert "unclaim_ticket" in eng.tools._tools
    t = tickets.create(tmp_path, title="甲")
    tickets.publish(tmp_path)
    tickets.claim(tmp_path, t["id"], by="sess-a")
    res = eng.tools._tools["unclaim_ticket"].execute(id=t["id"], reason="陈旧")
    assert res.status == "ok"
    assert not tickets.find(tmp_path, t["id"]).get("claimed_by")


def test_unclaim_ticket_tool_absent_in_isolated(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(cfg=EngineConfig(use_real_shape=False), workdir=tmp_path,
                 isolated=True)
    assert "unclaim_ticket" not in eng.tools._tools


# ---------- Task M2：批量认领 ----------

def test_claim_many_atomic_on_conflict(tmp_path):
    a = tickets.create(tmp_path, title="甲")
    b = tickets.create(tmp_path, title="乙")
    tickets.publish(tmp_path)
    tickets.claim(tmp_path, a["id"], by="sess-a")
    with pytest.raises(tickets.TicketClaimedError):
        tickets.claim_many(tmp_path, [b["id"], a["id"]], by="sess-b")
    # 原子：预检失败不留半认领（b 仍无主）
    assert not tickets.find(tmp_path, b["id"]).get("claimed_by")


def test_claim_many_force_transfer(tmp_path):
    a = tickets.create(tmp_path, title="甲")
    tickets.publish(tmp_path)
    tickets.claim(tmp_path, a["id"], by="sess-a")
    out = tickets.claim_many(tmp_path, [a["id"]], by="sess-b", force=True)
    assert out[0]["claimed_by"] == "sess-b"
    rows = _events(tmp_path)
    assert any(r["event"] == "unclaimed" and r.get("reason") == "override"
               for r in rows)


def test_annotate_claims_stale(tmp_path):
    t = tickets.create(tmp_path, title="甲")
    tickets.publish(tmp_path)
    tickets.claim(tmp_path, t["id"], by="sess-a")
    rows = tickets.annotate_claims(tickets.load(tmp_path),
                                   active_holders={"sess-b"})
    assert rows[0]["stale"] is True
    assert isinstance(rows[0]["claimed_age_s"], float)
    rows2 = tickets.annotate_claims(tickets.load(tmp_path),
                                    active_holders={"sess-a"})
    assert rows2[0]["stale"] is False
