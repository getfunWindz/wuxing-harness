import json
import pathlib

from wuxing.suite_eval import eval_route_quality, load_112_tasks


def test_load_112_tasks():
    tasks = load_112_tasks()
    assert len(tasks) >= 100

def test_eval_route_quality_structure():
    tasks = load_112_tasks()
    report = eval_route_quality(tasks)
    assert "total" in report
    assert "domain_dist" in report      # {plan: n, execute: n, ...}
    assert "verify_coverage" in report   # 含 verify 的任务比例
    assert "three_chain_rate" in report  # 任务级 plan+execute+verify 齐全率
    assert report["total"] == len(tasks)

def test_suite_cli_runs():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "wuxing.suite_eval", "--json"],
                       capture_output=True, text=True, check=False,
                       cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert r.returncode == 0, r.stderr
    data = json.loads(r.stdout)
    assert data["total"] >= 100

def test_eval_multi_suite():
    from wuxing.suite_eval import load_github_tasks
    report = eval_route_quality(load_112_tasks() + load_github_tasks())
    assert report["total"] >= 300
    assert "domain_dist" in report
