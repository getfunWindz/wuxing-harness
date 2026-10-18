"""TDD：A2 碎片消息三键裁剪（双指纹任一命中；不匹配跳过；确定性）。"""
import json

from wuxing.context_edits import apply_unit_edits
from wuxing.context_sources import content_fp, load_unit_edits


def _msgs():
    return [
        {"role": "system", "content": "S"},
        {"role": "user", "content": "任务：更新 docs/a.md"},
        {"role": "assistant", "content": "我已完成更新"},
        {"role": "tool", "content": "[tool] write_artifact: ok"},
    ]


def test_apply_by_fp_in_and_nearest_index():
    edits = [{"file": "f", "index": 1,
              "fp_in": content_fp("任务：更新 docs/a.md"),
              "fp_out": content_fp("我已完成更新"), "op": "omit", "content": ""}]
    out, skipped = apply_unit_edits(_msgs(), edits)
    assert [m["content"] for m in out] == [
        "S", "我已完成更新", "[tool] write_artifact: ok"]
    assert skipped == []


def test_apply_fp_out_alone_matches_output_message():
    edits = [{"file": "", "index": 2, "fp_in": "",
              "fp_out": content_fp("我已完成更新"),
              "op": "replace", "content": "已更新（改写）"}]
    out, skipped = apply_unit_edits(_msgs(), edits)
    assert out[2]["content"] == "已更新（改写）"
    assert skipped == []


def test_apply_skips_on_fingerprint_mismatch():
    edits = [{"file": "", "index": 1, "fp_in": content_fp("不存在"),
              "fp_out": content_fp("也不存在"), "op": "omit", "content": ""}]
    out, skipped = apply_unit_edits(_msgs(), edits)
    assert len(out) == 4 and len(skipped) == 1


def test_apply_nearest_index_wins_on_duplicate_content():
    msgs = [{"role": "user", "content": "dup"},
            {"role": "user", "content": "x"},
            {"role": "user", "content": "dup"}]
    edits = [{"file": "", "index": 2, "fp_in": content_fp("dup"),
              "fp_out": "", "op": "omit", "content": ""}]
    out, _ = apply_unit_edits(msgs, edits)
    assert [m["content"] for m in out] == ["dup", "x"]


def test_apply_does_not_mutate_input():
    msgs = _msgs()
    edits = [{"file": "", "index": 2, "fp_in": content_fp("我已完成更新"),
              "fp_out": "", "op": "replace", "content": "改写"}]
    apply_unit_edits(msgs, edits)
    assert msgs[2]["content"] == "我已完成更新"


def test_load_unit_edits_filters_and_latest_wins(tmp_path):
    side = tmp_path / ".wuxing" / "context-edits.jsonl"
    side.parent.mkdir(parents=True)
    side.write_text("\n".join([
        json.dumps({"conversation": "c.jsonl", "round": 1, "op": "omit", "ts": 1}),
        json.dumps({"kind": "unit", "unit": "P-a", "file": "f", "index": 1,
                    "fp_in": "a", "fp_out": "", "op": "omit", "ts": 2}),
        "not-json",
        json.dumps({"kind": "unit", "unit": "P-a", "file": "f", "index": 1,
                    "fp_in": "a", "fp_out": "", "op": "replace",
                    "content": "改写", "ts": 3}),
        json.dumps({"kind": "unit", "unit": "P-b", "file": "f", "index": 9,
                    "fp_in": "b", "fp_out": "", "op": "omit", "ts": 4}),
    ]) + "\n", encoding="utf-8")
    edits = load_unit_edits(tmp_path, "P-a")
    assert len(edits) == 1
    assert edits[0]["op"] == "replace" and edits[0]["content"] == "改写"
    assert [e["index"] for e in load_unit_edits(tmp_path, "P-b")] == [9]
    assert load_unit_edits(tmp_path, "Z-9") == []


class _FakeRunner:
    emit_event = None

    def __init__(self, sink):
        self.sink = sink
        self._messages = [{"role": "system", "content": "S"}]

    def run_unit(self, unit_id, domain_id, params, resume_session=None,
                 bypass_confirm=False, continue_from=None, cancel=None,
                 llm_candidate=0):
        from wuxing.protocols import UnitResult
        self.sink.append((unit_id, list(continue_from or [])))
        if continue_from:
            self._messages = list(continue_from) + [
                {"role": "user", "content": params["goal"]}]
        else:
            self._messages = [{"role": "system", "content": "S"},
                              {"role": "user", "content": params["goal"]}]
        return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")


def _orch(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.registry import DomainRegistry
    from wuxing.session_pool import SessionPool
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace
    ws = Workspace(tmp_path)
    cfg = EngineConfig()
    seen = []
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=SessionPool(retention_rounds=4),
                        trace=TraceLogger(ws.root / "trace.jsonl"))
    orch._make_runner = lambda: _FakeRunner(seen)
    return orch, seen, tmp_path / ".wuxing" / "context-edits.jsonl"


def _frag(uid, text):
    return {"fragment_id": uid, "domain": "execute", "deps": [],
            "text": text, "deliverables": []}


def test_orchestrator_applies_unit_edits_on_continue(tmp_path):
    orch, seen, side = _orch(tmp_path)
    orch.run([_frag("F-1", "更新 docs/a.md 内容")], "t1")
    assert seen[0][1] == []
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({
        "kind": "unit", "unit": "F-2", "file": "", "index": 1,
        "fp_in": content_fp("更新 docs/a.md 内容"), "fp_out": "",
        "op": "omit", "ts": 1}) + "\n", encoding="utf-8")
    orch.run([_frag("F-2", "继续 docs/b.md")], "t2")
    cont = seen[1][1]
    assert cont, "必须延续（键命中）"
    assert all(m["content"] != "更新 docs/a.md 内容" for m in cont), cont
    rows = orch.trace.load()
    assert any(r["event"] == "context_edit_applied" for r in rows), rows


def test_orchestrator_skips_edit_on_fingerprint_mismatch(tmp_path):
    orch, seen, side = _orch(tmp_path)
    orch.run([_frag("F-1", "更新 docs/a.md 内容")], "t1")
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({
        "kind": "unit", "unit": "F-2", "file": "", "index": 1,
        "fp_in": content_fp("完全不同的内容"), "fp_out": "",
        "op": "omit", "ts": 1}) + "\n", encoding="utf-8")
    orch.run([_frag("F-2", "继续 docs/b.md")], "t2")
    cont = seen[1][1]
    assert any(m["content"] == "更新 docs/a.md 内容" for m in cont), \
        "指纹不匹配不得误裁"
    rows = orch.trace.load()
    assert any(r["event"] == "context_edit_skipped" for r in rows), rows
