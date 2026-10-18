"""溯源链（3c 决策 C——git 参考：内容 hash + 父子链 + append-only reflog）。"""
import pathlib
import tempfile

from wuxing.provenance import ProvenanceLedger, task_hash


def test_task_hash_stable():
    assert task_hash("写一篇请假邮件") == task_hash("写一篇请假邮件")
    assert task_hash("写一篇请假邮件") != task_hash("写一篇请假邮件 3 天")


def test_ledger_append_and_load():
    p = pathlib.Path(tempfile.mkdtemp()) / ".wuxing" / "provenance.jsonl"
    led = ProvenanceLedger(p)
    led.record(unit_id="F-1", parent_id="F-0", task_text="t", goal="g",
               domain="plan", model="deepseek:deepseek-chat", status="ok",
               artifacts=["plan.md"])
    led.record(unit_id="F-2", parent_id="F-1", task_text="t2", goal="g2",
               domain="execute", model="deepseek:deepseek-chat", status="failed",
               artifacts=[])
    rows = led.load()
    assert len(rows) == 2  # append-only
    assert rows[0]["parent_id"] == "F-0"  # 父子链
    assert rows[1]["status"] == "failed"
    assert "task_hash" in rows[0]


def test_ledger_corrupted_returns_empty():
    """损坏容错（韧性护栏惯例）：损坏 → 空列表不崩溃。"""
    p = pathlib.Path(tempfile.mkdtemp()) / "l.jsonl"
    p.write_text("{not json }\n", encoding="utf-8")
    assert ProvenanceLedger(p).load() == []
