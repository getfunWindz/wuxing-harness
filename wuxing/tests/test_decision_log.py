"""#2 T-5：决策历史（trace 审计对还原）。"""
import json

from wuxing import decision_log


def _write(tmp_path, rows):
    d = tmp_path / ".wuxing"
    d.mkdir(exist_ok=True)
    (d / "trace.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")


def test_confirm_pairing_and_pending(tmp_path):
    _write(tmp_path, [
        {"ts": 1.0, "event": "confirm_asked", "unit_id": "U-1",
         "domain": "verify", "surface": "unit_confirm"},
        {"ts": 2.0, "event": "confirm_decided", "unit_id": "U-1",
         "domain": "verify", "decision": "reject", "reason": "理由A"},
        {"ts": 3.0, "event": "confirm_asked", "unit_id": "U-2",
         "domain": "user", "surface": "unit_confirm"},
    ])
    got = decision_log.load_decisions(tmp_path)
    assert got["problems"] == []
    es = {e["object"]: e for e in got["entries"]}
    assert es["U-1"]["status"] == "rejected"
    assert es["U-1"]["reason"] == "理由A"
    assert es["U-1"]["kind"] == "confirm"
    assert es["U-2"]["status"] == "pending", "未决必须保留且不假装已决"


def test_question_and_browser(tmp_path):
    _write(tmp_path, [
        {"ts": 1.0, "event": "question_asked", "unit_id": "U-1",
         "domain": "execute", "question_id": "q-1", "kind": ""},
        {"ts": 2.0, "event": "question_answered", "unit_id": "U-1",
         "question_id": "q-1", "answer": "选 A", "source": "option"},
        {"ts": 3.0, "event": "browser_access_decided", "unit_id": "",
         "domain": "", "address": "127.0.0.1:3000", "approved": True,
         "kind": "loopback", "note": ""},
    ])
    got = decision_log.load_decisions(tmp_path)
    kinds = sorted(e["kind"] for e in got["entries"])
    assert kinds == ["browser_access", "question"]
    q = next(e for e in got["entries"] if e["kind"] == "question")
    assert q["status"] == "answered" and q["reason"] == "选 A"
    b = next(e for e in got["entries"] if e["kind"] == "browser_access")
    assert b["status"] == "approved" and b["object"] == "127.0.0.1:3000"


def test_missing_and_corrupt_fail_closed(tmp_path):
    got = decision_log.load_decisions(tmp_path)          # 缺文件
    assert got["entries"] == [] and got["problems"] == []
    d = tmp_path / ".wuxing"
    d.mkdir(exist_ok=True)
    (d / "trace.jsonl").write_text("{bad\n" + json.dumps(
        {"ts": 1.0, "event": "confirm_asked", "unit_id": "U-9"}) + "\n",
        encoding="utf-8")
    got = decision_log.load_decisions(tmp_path)          # 损坏行跳过、好行保留
    assert [e["object"] for e in got["entries"]] == ["U-9"]
    assert got["entries"][0]["status"] == "pending"


def test_sorted_desc_and_limit(tmp_path):
    rows = [{"ts": float(i), "event": "browser_access_decided",
             "unit_id": "", "address": f"10.0.0.{i}", "approved": True}
            for i in range(1, 6)]
    _write(tmp_path, rows)
    got = decision_log.load_decisions(tmp_path, limit=3)
    assert [e["object"] for e in got["entries"]] == \
        ["10.0.0.5", "10.0.0.4", "10.0.0.3"]
