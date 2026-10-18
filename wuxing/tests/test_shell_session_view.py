"""TDD：工作区域读取聚合（轮次化/碎片会话/轨迹——只读消费工作区文件）。"""
import json
import pathlib

from wuxing.shell.web import session_view as sv


def _w(p: pathlib.Path, name: str, rows: list) -> None:
    p.mkdir(parents=True, exist_ok=True)
    (p / name).write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )


def test_task_hash8_matches_engine_shape():
    # 与 wuxing.provenance.task_hash 同口径（8 位 hex；跨模块一致性由本测试冻结）
    from wuxing.provenance import task_hash

    assert sv.task_hash8("生成变更摘要") == task_hash("生成变更摘要")
    assert len(sv.task_hash8("")) == 8


def test_read_jsonl_skips_broken_lines(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text('{"a":1}\nnot-json\n{"a":2}\n', encoding="utf-8")
    assert [r["a"] for r in sv.read_jsonl(p)] == [1, 2]
    assert sv.read_jsonl(tmp_path / "missing.jsonl") == []


def _seed_fixture(tmp_path):
    """一轮线性 + 一轮并行（P-a/P-b 区间重叠）+ 一轮同文本重复（ts 消歧）。"""
    wux = tmp_path / ".wuxing"
    conv = [
        {"round": 1, "user_text": "线性任务", "summary": "done", "ts": 100.0, "artifacts": []},
        {"round": 2, "user_text": "并行任务", "summary": "done", "ts": 200.0, "artifacts": []},
        {"round": 3, "user_text": "并行任务", "summary": "done", "ts": 300.0, "artifacts": []},
    ]
    prov = [
        {"unit_id": "L-1", "task_hash": sv.task_hash8("线性任务"), "goal": "线性", "domain": "execute",
         "status": "ok", "artifacts": [], "ts": 90.0},
        {"unit_id": "P-a", "task_hash": sv.task_hash8("并行任务"), "goal": "分支A", "domain": "execute",
         "status": "ok", "artifacts": [], "ts": 150.0},
        {"unit_id": "P-b", "task_hash": sv.task_hash8("并行任务"), "goal": "分支B", "domain": "plan",
         "status": "ok", "artifacts": [], "ts": 160.0},
        {"unit_id": "P-c", "task_hash": sv.task_hash8("并行任务"), "goal": "第二轮的分支", "domain": "execute",
         "status": "ok", "artifacts": [], "ts": 250.0},
    ]
    trace = [
        {"ts": 80.0, "event": "unit_started", "unit_id": "L-1", "domain": "execute"},
        {"ts": 90.0, "event": "unit_done", "unit_id": "L-1", "domain": "execute", "status": "ok"},
        {"ts": 140.0, "event": "unit_started", "unit_id": "P-a", "domain": "execute"},
        {"ts": 145.0, "event": "unit_started", "unit_id": "P-b", "domain": "plan"},
        {"ts": 155.0, "event": "unit_done", "unit_id": "P-a", "domain": "execute", "status": "ok"},
        {"ts": 175.0, "event": "unit_done", "unit_id": "P-b", "domain": "plan", "status": "ok"},
        {"ts": 250.0, "event": "unit_started", "unit_id": "P-c", "domain": "execute"},
        {"ts": 255.0, "event": "unit_done", "unit_id": "P-c", "domain": "execute", "status": "ok"},
    ]
    _w(wux, "conversation-1.jsonl", conv)
    _w(wux, "provenance.jsonl", prov)
    _w(wux, "trace.jsonl", trace)
    return tmp_path


def test_session_rounds_join_and_parallel(tmp_path):
    ws = _seed_fixture(tmp_path)
    d = sv.session_rounds(ws, "conversation-1.jsonl")
    assert [r["round"] for r in d["rounds"]] == [1, 2, 3]
    r1, r2, r3 = d["rounds"]
    assert [f["unit_id"] for f in r1["fragments"]] == ["L-1"]
    assert r1["parallel"] is False                      # 线性轮
    assert [f["unit_id"] for f in r2["fragments"]] == ["P-a", "P-b"]
    assert r2["parallel"] is True                       # 区间重叠
    assert all(f["parallel"] for f in r2["fragments"])
    assert r2["fragments"][0]["duration_ms"] == 15000   # 155-140
    assert [f["unit_id"] for f in r3["fragments"]] == ["P-c"]  # 同文本 ts 窗口消歧
    assert r3["parallel"] is False


def test_unit_session_groups_and_security(tmp_path):
    ws = _seed_fixture(tmp_path)
    wux = ws / ".wuxing" / "sessions"
    _w(wux, "P-a.jsonl", [
        {"round": 0, "state": "seed", "status": "", "ts": 140.0,
         "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "任务"}]},
        {"round": 1, "state": "thinking", "status": "", "ts": 150.0,
         "messages": [{"role": "user", "content": "输出文本"},
                      {"role": "user", "content": "[tool] write_artifact: ok"}]},
        {"round": 1, "state": "done", "status": "ok", "ts": 155.0, "messages": []},
    ])
    d = sv.unit_session(ws, "P-a")
    assert d["unit_id"] == "P-a"
    assert [g["state"] for g in d["groups"]] == ["seed", "thinking", "done"]
    assert d["groups"][1]["messages"][1]["content"].startswith("[tool]")
    # 安全：路径穿越与非法名拒绝
    assert sv.unit_session(ws, "../secrets") == {
        "unit_id": "", "files": [], "groups": [], "meta": {},
        "bound_rounds": []}


def test_trajectory_groups_rounds(tmp_path):
    ws = _seed_fixture(tmp_path)
    d = sv.trajectory(ws)
    assert [r["round"] for r in d["rounds"]] == [1, 2, 3]
    assert d["rounds"][1]["fragments"][0]["tool_calls"] == 0
    assert d["rounds"][1]["parallel"] is True
    assert d["rounds"][0]["session"] == "conversation-1.jsonl"


def test_session_rounds_skips_non_turn_rows(tmp_path):
    """旧形状（role/content）行不是轮次——不得渲染为空轮次。"""
    wux = tmp_path / ".wuxing"
    _w(wux, "conversation-legacy.jsonl", [
        {"role": "user", "content": "旧形状"},
        {"role": "assistant", "content": "已完成"},
    ])
    assert sv.session_rounds(tmp_path, "conversation-legacy.jsonl")["rounds"] == []


def test_unit_session_bound_rounds(tmp_path):
    """碎片会话后半程（2026-09-22）：unit-bindings join 会话轮次 → bound_rounds。"""
    ws = _seed_fixture(tmp_path)
    wux = ws / ".wuxing"
    lines = [
        json.dumps({"conversation": "conversation-1.jsonl", "unit_id": "P-a",
                    "round": 2, "ts": 210.0}, ensure_ascii=False),
        "not-json（坏行跳过）",
        json.dumps({"conversation": "conversation-1.jsonl", "unit_id": "P-b",
                    "round": 3, "ts": 310.0}, ensure_ascii=False),
        json.dumps({"conversation": "missing.jsonl", "unit_id": "P-a",
                    "round": 1, "ts": 1.0}, ensure_ascii=False),
        json.dumps({"conversation": "conversation-1.jsonl", "unit_id": "P-a",
                    "round": 99, "ts": 2.0}, ensure_ascii=False),
    ]
    (wux / "unit-bindings.jsonl").write_text("\n".join(lines) + "\n",
                                              encoding="utf-8")
    d = sv.unit_session(ws, "P-a")
    assert [b["round"] for b in d["bound_rounds"]] == [2]
    b = d["bound_rounds"][0]
    assert b["user_text"] == "并行任务" and b["summary"] == "done"
    assert b["ts"] == 200.0 and b["artifacts"] == []
    assert sv.unit_session(ws, "P-b")["bound_rounds"][0]["round"] == 3
    # 轨迹会话列表不得把绑定 sidecar 当会话（内部文件过滤）
    assert "unit-bindings.jsonl" not in sv.trajectory(ws)["sessions"]
