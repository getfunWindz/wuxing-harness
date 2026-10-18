"""TDD（P0-3 A）：真实测试批跑器——断言/汇总/CLI 干跑（不消耗 API）。"""


def test_check_files_missing_and_ok(tmp_path):
    from scripts.real_suite import check_files
    (tmp_path / "a.py").write_text("print(1)", encoding="utf-8")
    assert check_files(tmp_path, ["a.py"]) == {"ok": True, "missing": []}
    r = check_files(tmp_path, ["a.py", "b.py"])
    assert not r["ok"] and r["missing"] == ["b.py"]
    (tmp_path / "empty.py").write_text("", encoding="utf-8")
    assert not check_files(tmp_path, ["empty.py"])["ok"]


def test_check_pytest_pass_and_fail(tmp_path):
    from scripts.real_suite import check_pytest
    (tmp_path / "test_ok.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    r = check_pytest(tmp_path)
    assert r["ok"] and "passed" in r["tail"]
    (tmp_path / "test_bad.py").write_text(
        "def test_bad():\n    assert False\n", encoding="utf-8")
    assert not check_pytest(tmp_path)["ok"]


def test_check_tickets_all_done():
    from scripts.real_suite import check_tickets
    ok = check_tickets([{"id": "T-1", "status": "done"},
                        {"id": "T-2", "status": "done"}], "all_done")
    assert ok["ok"] and ok["statuses"] == {"T-1": "done", "T-2": "done"}
    bad = check_tickets([{"id": "T-1", "status": "failed"}], "all_done")
    assert not bad["ok"] and bad["not_done"] == {"T-1": "failed"}


def test_summarize_and_suite_loading():
    from scripts.real_suite import load_suite, summarize
    s = summarize([{"id": "a", "ok": True, "cost": 0.01, "duration_s": 1.5},
                   {"id": "b", "ok": False, "cost": None, "duration_s": 2.0}])
    assert s["passed"] == 1 and s["failed"] == ["b"]
    assert s["total_cost"] == 0.01
    suite = load_suite("eval/real/tasks.json")
    assert suite["version"] == "v1" and len(suite["tasks"]) >= 3


def test_dry_run_cli_subprocess():
    """CLI 干跑：默认不执行（防误花费），列出任务与断言。"""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "scripts.real_suite", "--list"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60, check=False)
    assert r.returncode == 0
    assert "dry-run" in r.stdout and "greet-cli" in r.stdout
    assert "--yes" in r.stdout


def test_check_pytest_declared_targets_gate(tmp_path):
    """E0-2/A2：声明测试门禁——模型追加测试失败不回灌任务失败。"""
    from scripts.real_suite import check_pytest
    (tmp_path / "test_declared.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8")
    (tmp_path / "test_extra.py").write_text(
        "def test_extra():\n    assert False\n", encoding="utf-8")
    assert check_pytest(tmp_path, ["test_declared.py"])["ok"] is True
    assert check_pytest(tmp_path)["ok"] is False  # 全工作区仍红（观察面输入）


def test_declared_tests_filtering():
    """E0-2/A2：声明测试文件筛选（basename test_* / *_test.py；保序）。"""
    from scripts.real_suite import _declared_tests
    files = ["dedup.py", "input.txt", "test_dedup.py",
             "x_test.py", "src/helper_test.py", "tests/test_io.py"]
    assert _declared_tests(files) == ["test_dedup.py", "x_test.py",
                                      "src/helper_test.py", "tests/test_io.py"]
    assert _declared_tests([]) == []
