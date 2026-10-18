"""G8-M2：路径级锁铺开——多实例并发写不丢/不坏。

覆盖：trace / provenance / design_state / manifest（Workspace）；tickets 见
`test_tickets_claim.py`（M1）。
"""
import json
import threading


def _run_threads(fn, n=30):
    threads = [threading.Thread(target=fn, args=(i,)) for i in range(n)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()


def test_trace_two_instances_concurrent_appends(tmp_path):
    from wuxing.trace import TraceLogger
    p = tmp_path / "trace.jsonl"
    a, b = TraceLogger(p), TraceLogger(p)

    def worker(i):
        (a if i % 2 else b).log("t", "", "", i=i)

    _run_threads(worker, 40)
    lines = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
             if x.strip()]
    assert len(lines) == 40
    assert len({ln["i"] for ln in lines}) == 40


def test_provenance_two_instances_concurrent_records(tmp_path):
    from wuxing.provenance import ProvenanceLedger
    p = tmp_path / "prov.jsonl"
    a, b = ProvenanceLedger(p), ProvenanceLedger(p)

    def worker(i):
        (a if i % 2 else b).record(f"u{i}", task_text="t")

    _run_threads(worker, 40)
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()
            if x.strip()]
    assert len(rows) == 40


def test_design_state_concurrent_saves_merge(tmp_path):
    from wuxing import design_state

    def worker(i):
        design_state.save(tmp_path, {f"k{i}": i})

    _run_threads(worker, 20)
    st = json.loads((tmp_path / ".wuxing" / "design-state.json")
                    .read_text(encoding="utf-8"))
    for i in range(20):
        assert st.get(f"k{i}") == i


def test_manifest_two_workspaces_concurrent(tmp_path):
    from wuxing.protocols import Artifact
    from wuxing.workspace import Workspace
    root = tmp_path.resolve()  # 避免 Windows 短名/长名混用（_safe_path 判定）
    w1, w2 = Workspace(root), Workspace(root)

    def worker(i):
        ws = w1 if i % 2 else w2
        ws.write_artifact(Artifact(path=f"art/a{i}.txt", kind="result"),
                          f"c{i}")

    _run_threads(worker, 20)
    items = w1.manifest()
    assert len({a.path for a in items}) == 20


def test_map_doc_concurrent_append_decisions(tmp_path):
    from wuxing import map_doc

    def worker(i):
        map_doc.append_decision(tmp_path, text=f"决策{i}")

    _run_threads(worker, 20)
    data = map_doc.read(tmp_path) or {}
    ids = [d.get("id") for d in map_doc.parse_decisions(
        data.get("decisions") or [])]
    assert len(ids) == 20
    assert len(set(ids)) == 20  # D-n 无重复分配


def test_filelock_windows_prefix_variant_same_lock(tmp_path):
    """M2 实测教训：`\\?\\` 扩展前缀变体必须映射到同一把锁。"""
    import os
    import sys

    import pytest

    from wuxing.filelock import lock_for
    if sys.platform != "win32":
        pytest.skip("Windows 特有路径前缀")
    p = tmp_path / "x.json"
    extended = "\\\\?\\" + os.path.abspath(str(p))
    assert lock_for(p) is lock_for(extended)
