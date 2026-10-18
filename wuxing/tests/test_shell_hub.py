"""TDD：EventHub（壳 P1 · B1）——seq/epoch/环形缓冲/背压（并发健壮契约）。

设计 §4.2：单锁分配全局全序 seq；环形缓冲重放（缺口 → gap 标记）；
订阅者有界队列（溢出即断开——生产者永不被阻塞）；epoch 标识实例。
"""
import threading
import time

from wuxing.shell.web.hub import CLOSED, EventHub


def test_seq_monotonic_unique_under_concurrency():
    hub = EventHub()
    sub, replay, gap = hub.subscribe()
    assert replay == [] and gap is False
    n_threads, per = 8, 50
    barrier = threading.Barrier(n_threads)

    def emit_worker(tid):
        barrier.wait()
        for i in range(per):
            hub.emit("unit_done", workspace_id="ws", run_id="r",
                     data={"tid": tid, "i": i})

    ts = [threading.Thread(target=emit_worker, args=(t,))
          for t in range(n_threads)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    events = []
    while True:
        ev = sub.get(timeout=0.05)
        if ev is None:
            break
        events.append(ev)
    total = n_threads * per
    assert len(events) == total, f"事件不得丢失（{len(events)}/{total}）"
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, total + 1)), "seq 必须唯一且单调连续"
    assert all(e["v"] == 1 for e in events)
    assert all(e["epoch"] == hub.info()["epoch"] for e in events)


def test_epoch_changes_per_hub_instance():
    a, b = EventHub(), EventHub()
    assert a.info()["epoch"] != b.info()["epoch"]
    a.emit("x")
    assert a.info()["last_seq"] == 1 and b.info()["last_seq"] == 0


def test_ring_replay_and_gap():
    hub = EventHub(ring_size=8)
    for i in range(10):
        hub.emit("e", data={"i": i})
    sub, replay, gap = hub.subscribe(since=5)
    assert not gap
    assert [e["seq"] for e in replay] == [6, 7, 8, 9, 10]
    sub2, replay2, gap2 = hub.subscribe(since=1)
    assert gap2 is True, "缓冲覆盖不足必须标记 gap（resync_required）"
    assert replay2 == [], "gap 时不重放（由客户端重拉快照）"
    hub.unsubscribe(sub)
    hub.unsubscribe(sub2)


def test_backpressure_drops_slow_subscriber_without_blocking():
    hub = EventHub(subscriber_queue=4)
    sub, _, _ = hub.subscribe()
    start = time.monotonic()
    for i in range(50):
        hub.emit("e", data={"i": i})
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, "生产者不得被慢订阅者阻塞"
    assert sub.dropped is True, "溢出必须标记并断开该订阅者"
    drained = 0
    while True:
        ev = sub.get(timeout=0.05)
        if ev is CLOSED:
            break
        assert ev is not None
        drained += 1
        assert drained <= 100, "断开后不得继续累积"
    assert drained <= 4, f"断开后队列上限不得突破（实际 {drained}）"


def test_since_beyond_last_seq_no_replay_no_gap():
    hub = EventHub()
    hub.emit("e")
    _sub, replay, gap = hub.subscribe(since=10)
    assert replay == [] and gap is False


def test_journal_writes_and_rotates(tmp_path):
    """事件日志：落盘 events.jsonl；超上限轮转（单备份；审计/调试用）。"""
    import json as _json
    hub = EventHub(journal_path=tmp_path / "events.jsonl",
                   journal_max_bytes=256)
    for i in range(30):
        hub.emit("e", data={"i": i, "pad": "x" * 40})
    current = tmp_path / "events.jsonl"
    rotated = tmp_path / "events.jsonl.1"
    assert current.exists(), "事件日志必须写入"
    assert rotated.exists(), "超上限必须轮转（单备份）"
    lines = [ln for ln in current.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    assert lines, "轮转后当前文件仍有事件"
    assert _json.loads(lines[-1])["type"] == "e"


def test_journal_write_failure_is_silent(tmp_path):
    """写入失败静默（嗅测不阻断——事件照常扇出）。"""
    blocker = tmp_path / "blocker"
    blocker.write_text("x", encoding="utf-8")
    hub = EventHub(journal_path=blocker / "ev.jsonl")
    ev = hub.emit("e")  # 不得抛错
    assert ev["seq"] == 1
