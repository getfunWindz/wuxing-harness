"""TDD · L1-5：CI 回归防护——mock 管道评测指标与基线一致（知识库「回归防护」）。

mock 引擎确定性：同一评测集子集 → 同一指标（回归 = 改动破坏指标即失败）。
此测试守住管道级基线（真模型评测受 LLM 冻结约束——半自动线 CLI + 留档）。
"""
import json
import pathlib

from wuxing.eval_set import load_eval_tasks
from wuxing.evaluate import run_eval

BASELINE_PATH = pathlib.Path(__file__).resolve().parent / ".." / ".." / "eval" \
    / "baseline.json"


def test_baseline_file_exists():
    """基线存在（L1-4 生成的 mock 管道基线——改动后可对比）。"""
    assert BASELINE_PATH.exists(), "基线缺失：运行 python -m wuxing.evaluate --llm mock --n 5 > eval/baseline.json"


def test_mock_eval_matches_baseline():
    """回归防护：mock 跑基线子集 → 关键指标与 baseline.json 一致。

    若 harness 改动导致管道指标变化（如收敛逻辑/工具协议/契约）→ 本测试失败
    → 显式提示：更新基线（确认改进）或修复（确认回归）。
    """
    base = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    items = base.get("items", {})
    n = items.get("n_tasks", 5)
    tasks = load_eval_tasks()[:n]
    report = run_eval(tasks)
    now, want = report["metrics"], items.get("metrics", {})
    for k in ("done_rate", "tool_error_rate", "avg_steps_per_unit", "retry_calls",
              "verdict_fails"):
        assert abs(now.get(k, 0) - want.get(k, 0)) < 1e-6, \
            f"指标回归：{k} now={now.get(k)} baseline={want.get(k)}——" \
            f"更新基线（确认改进）或修复回归"
