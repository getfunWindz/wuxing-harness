"""C3：verify 金标校准——判定抽取 + 一致率统计（金标样本机制）。

金标声明（`eval/real/tasks.json` 可选字段）：``verify_gold: {"expect": "pass"|"fail"}``。
判定口径：优先用单元结果（`verdict_fail` / failed 单元）；无结构化条目（回退路径）
按整体状态判定；取消/错误等不可判 → 不计入分母（诚实口径）。
"""
from wuxing.verify_gold import agreement_summary, extract_verdict, gold_agreement


class _U:
    def __init__(self, status="ok", verdict_fail=False):
        self.status = status
        self.verdict_fail = verdict_fail


def test_extract_verdict_from_units():
    assert extract_verdict([_U("ok"), _U("ok")]) == "pass"
    assert extract_verdict([_U("ok"), _U("ok", verdict_fail=True)]) == "fail"
    assert extract_verdict([_U("failed"), _U("ok")]) == "fail"
    assert extract_verdict([_U("rejected")]) == "fail"


def test_extract_verdict_fallback_status():
    assert extract_verdict([], status="done") == "pass"
    assert extract_verdict([], status="failed") == "fail"
    assert extract_verdict([], status="partial") == "fail"
    assert extract_verdict([], status="cancelled") == ""
    assert extract_verdict([], status="error") == ""
    assert extract_verdict([], status="") == ""


def test_gold_agreement_basic():
    task = {"id": "t1", "verify_gold": {"expect": "pass", "note": "n"}}
    r = gold_agreement(task, [_U("ok")])
    assert r == {"task_id": "t1", "expect": "pass", "actual": "pass",
                 "agree": True, "note": "n"}
    r2 = gold_agreement(task, [_U("failed")])
    assert r2["agree"] is False and r2["actual"] == "fail"


def test_gold_agreement_without_gold():
    assert gold_agreement({"id": "t1"}, [_U("ok")]) is None
    assert gold_agreement({"id": "t1", "verify_gold": {"expect": "maybe"}}, []) is None


def test_gold_agreement_fallback_path_no_units():
    """回退路径（无结构化条目）：仅状态可判——一致率仍可算（C3 专项样本）。"""
    task = {"id": "t-notes", "verify_gold": {"expect": "pass"}}
    r = gold_agreement(task, [], status="done")
    assert r["actual"] == "pass" and r["agree"] is True


def test_agreement_summary_rate_and_undecided():
    rows = [
        {"task_id": "a", "expect": "pass", "actual": "pass", "agree": True},
        {"task_id": "b", "expect": "fail", "actual": "pass", "agree": False},
        {"task_id": "c", "expect": "pass", "actual": "", "agree": False},
        None,
    ]
    s = agreement_summary(rows)
    assert s["gold_total"] == 3
    assert s["decided"] == 2 and s["agreed"] == 1
    assert s["rate"] == 0.5
    assert s["undecided"] == 1
    assert agreement_summary([])["rate"] is None
