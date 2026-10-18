"""TDD：精确测试流程——单轮运行器 / 冻结 / 评审输入 / judge / 报告（B Task 3-6；原称准测试）。"""


def _base_task() -> dict:
    return {
        "id": "acc-t1",
        "title": "示例任务",
        "public_prompt": "写一个 hello 程序并说明用法",
        "hidden_rubric": {
            "version": "v1",
            "items": [{"id": "R1", "desc": "可运行程序", "weight": 3,
                       "checks": ["文件存在"]}],
            "pass_line": 0.6,
        },
        "evidence_checklist": ["主文件存在"],
    }


def test_run_accuracy_task_single_turn_mock(tmp_path):
    """单轮运行：仅 public_prompt；rubric 绝不落工作区（防泄漏红线）。"""
    from wuxing.accuracy import run_accuracy_task

    out = run_accuracy_task(_base_task(), tmp_path, llm=None)
    assert out["task_id"] == "acc-t1"
    assert out["status"], out
    assert "duration_s" in out and isinstance(out["metrics"], dict)
    assert (tmp_path / "task_state.json").exists(), "引擎状态必须落盘"
    # 防泄漏：工作区任何文件不得含 rubric 字段/条目
    for p in tmp_path.rglob("*"):
        if p.is_file():
            txt = p.read_text(encoding="utf-8", errors="replace")
            assert "hidden_rubric" not in txt and "pass_line" not in txt, p


def test_freeze_snapshot_detects_later_changes(tmp_path):
    """冻结快照：hash 清单 + 内容定格——此后工作区变化可检测（顺序红线）。"""
    from wuxing.accuracy import freeze_snapshot

    (tmp_path / "a.txt").write_text("v1", encoding="utf-8")
    snap = freeze_snapshot(tmp_path)
    assert snap["files"][0]["path"] == "a.txt"
    assert snap["contents"]["a.txt"] == "v1"
    h1 = snap["files"][0]["sha256"]
    (tmp_path / "a.txt").write_text("v2", encoding="utf-8")
    snap2 = freeze_snapshot(tmp_path)
    assert snap2["files"][0]["sha256"] != h1, "冻结后修改必须可检测"
    assert snap["contents"]["a.txt"] == "v1", "冻结快照内容不随工作区变化"


def test_build_judge_payload_blind_and_bounded(tmp_path):
    """评审输入：盲评（无状态/自评/模型字段）+ 总量受限 + rubric 原样释放。"""
    from wuxing.accuracy import build_judge_payload, freeze_snapshot, mechanical_checkup

    task = _base_task()
    (tmp_path / "main.py").write_text("print('hi')", encoding="utf-8")
    (tmp_path / "big.txt").write_text("x" * 50000, encoding="utf-8")
    checkup = mechanical_checkup(tmp_path)
    snap = freeze_snapshot(tmp_path)
    pl = build_judge_payload(task, checkup, snap, max_file_chars=1000,
                             max_total_chars=5000)
    assert pl["public_prompt"] == task["public_prompt"]
    assert pl["rubric"] == task["hidden_rubric"]
    assert set(pl) == {"public_prompt", "rubric", "mechanical", "files"}, set(pl)
    assert all(len(f["excerpt"]) <= 1000 for f in pl["files"])
    assert sum(len(f["excerpt"]) for f in pl["files"]) <= 5000


def _payload() -> dict:
    task = _base_task()
    return {"public_prompt": task["public_prompt"],
            "rubric": task["hidden_rubric"],
            "mechanical": {"files": []}, "files": []}


def test_judge_payload_parses_scores_and_versioned_prompt():
    """Judge B：结构化 JSON 解析 + 本地加权总分 + 版本化 prompt。"""
    import json as _json

    from wuxing.accuracy import JUDGE_PROMPT_VERSION, judge_payload
    from wuxing.llm.tool_results import ToolCallResult
    good = _json.dumps({"items": [{"id": "R1", "verdict": "pass",
                                    "score": 1.0, "evidence": "文件存在",
                                    "reason": "满足"}], "total": 0.9})

    class P:
        def name(self):
            return "fake-judge"

        def chat(self, messages, tools=None):
            assert JUDGE_PROMPT_VERSION in messages[0]["content"]
            return ToolCallResult(text="```json\n" + good + "\n```")

    out = judge_payload(_payload(), P())
    assert out["items"][0]["id"] == "R1"
    assert out["total"] == 1.0, "总分必须本地加权计算（不由 judge 自报主导）"
    assert out["pass"] is True
    assert out["meta"]["version"] == JUDGE_PROMPT_VERSION


def test_judge_payload_retries_then_fails():
    import pytest

    from wuxing.accuracy import judge_payload

    class Bad:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "bad"

        def chat(self, messages, tools=None):
            self.calls += 1
            return "无 JSON"

    p = Bad()
    with pytest.raises(ValueError):
        judge_payload(_payload(), p)
    assert p.calls == 2, "必须重试一次"


def test_judge_payload_rejects_incomplete_coverage():
    import json as _json

    import pytest

    from wuxing.accuracy import judge_payload

    class P:
        def name(self):
            return "fake"

        def chat(self, messages, tools=None):
            return _json.dumps({"items": [], "total": 1.0})

    with pytest.raises(ValueError, match="judge"):
        judge_payload(_payload(), P())


def _fake_result() -> dict:
    task = _base_task()
    return {
        "task": task,
        "run": {"task_id": "acc-t1", "status": "done", "duration_s": 2.5,
                "metrics": {"usage": {"input": 100, "output": 10,
                                       "cache_read": 60, "cache_write": 0}},
                "artifacts": []},
        "checkup": {"files": [], "total_files": 3, "compressed_markers": [],
                    "py_compile": {"checked": 1, "errors": []},
                    "run_probes": [], "tests_probe": None},
        "verdict": {"items": [{"id": "R1", "verdict": "pass", "score": 1.0,
                               "evidence": "e", "reason": "r"}],
                    "total": 1.0, "pass": True,
                    "meta": {"version": "judge-v1", "model": "fake"}},
    }


def test_write_report_contains_all_sections(tmp_path):
    from wuxing.accuracy import write_report

    p = write_report(tmp_path / "rep.md", _fake_result())
    txt = p.read_text(encoding="utf-8")
    for k in ("精确测试报告", "acc-t1", "机械体检", "B 分", "R1", "总分",
              "C 记录", "60.0%"):
        assert k in txt, k
    assert "✅ 通过" in txt


def test_gather_pipeline_end_to_end_mock(tmp_path):
    """流水线：运行 → 体检 → 冻结 → 评审输入（无 judge 时 verdict=None）。"""
    from wuxing.accuracy import gather_pipeline

    result = gather_pipeline(_base_task(), tmp_path, llm=None,
                             judge_provider=None)
    assert result["run"]["status"]
    assert result["verdict"] is None
    assert result["checkup"]["total_files"] >= 1
    assert set(result["snapshot"]) == {"files", "contents", "total_files"}


def test_gather_pipeline_with_fake_judge(tmp_path):
    import json as _json

    from wuxing.accuracy import gather_pipeline

    class P:
        def name(self):
            return "fake"

        def chat(self, messages, tools=None):
            return _json.dumps({"items": [{"id": "R1", "verdict": "partial",
                                            "score": 0.5, "evidence": "e",
                                            "reason": "r"}]})

    result = gather_pipeline(_base_task(), tmp_path, llm=None, judge_provider=P())
    assert result["verdict"]["total"] == 0.5
    assert result["verdict"]["pass"] is False, "0.5 < pass_line 0.6"
