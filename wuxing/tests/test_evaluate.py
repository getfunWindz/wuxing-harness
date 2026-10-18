"""TDD · L1-2/3：评测集加载校验 + 指标引擎（trace 驱动——知识库评测标准落地）。"""
import pathlib
import tempfile

import pytest

from wuxing.engine import Engine
from wuxing.eval_set import eval_set_summary, load_eval_tasks
from wuxing.evaluate import compute_metrics_from_trace, run_eval


def test_default_eval_set_complete():
    """L1-2：默认评测集存在、20 条、字段齐全（元数据化——可引用的评测集）。"""
    tasks = load_eval_tasks()
    assert len(tasks) == 20
    need = {"id", "task_text", "suite", "difficulty", "expected_kinds",
            "acceptance_notes", "source"}
    for t in tasks:
        assert need <= set(t), f"缺字段：{t.get('id')}"


def test_loader_rejects_missing_fields(tmp_path):
    """L1-2：缺字段 → ValueError（元数据不完整的任务不得入评测集）。"""
    p = tmp_path / "bad.json"
    p.write_text('{"version": "v1", "tasks": [{"id": "x", "task_text": "t"}]}',
                 encoding="utf-8")
    with pytest.raises(ValueError):
        load_eval_tasks(p)


def test_eval_set_summary():
    """L1-2：套件/难度分布摘要（评测集健康状况）。"""
    tasks = load_eval_tasks()
    s = eval_set_summary(tasks)
    assert s["total"] == 20
    assert s["suites"] == {
        "calibration_tasks": 4, "mega_tasks": 4, "professional_tasks": 4,
        "domain_tasks": 4, "github_tasks": 4}
    assert s["difficulties"].get("unknown", 0) == 4  # github 无人工难度


class _ProbeLlm:
    """第一轮成功工具调用，第二轮阻塞工具（白名单外 prove），第三轮收口。
    预置 usage 真值（Mock 无 usage——指标降级容忍）。"""

    def __init__(self):
        self.calls = 0
        self.usage_history = []

    def name(self):
        return "probe"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.calls += 1
        self.usage_history.append({"input": 100, "output": 10,
                                   "cache_read": 0, "cache_write": 0})
        if self.calls == 1:
            return ToolCallResult(text="", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "p.md", "kind": "plan", "content": "x"}}])
        if self.calls == 2:
            return ToolCallResult(text="", tool_calls=[
                {"name": "prove", "arguments": {"a": "b"}}])  # 白名单外→blocked
        return "方案：完整执行计划"


def _mk_engine(tmp):
    wd = pathlib.Path(tmp)
    eng = Engine(workdir=wd, llm=_ProbeLlm(), auto_confirm=True)
    eng.shape_cache.put("写一份季度报告", {
        "nodes": [{"id": "n1", "text": "撰写报告", "domain": {"写作": 0.9},
                   "trades": [], "complexity": "low", "deliverable": "text",
                   "weight": 0.5}],
        "edges": []})
    return eng


def test_metrics_keys_complete():
    """L1-3：单任务跑完 → 指标键齐全（完成率/工具正确率/步骤效率/重试率/缓存）。"""
    td = tempfile.mkdtemp()
    eng = _mk_engine(td)
    res = eng.run_task("写一份季度报告")
    rows = eng.trace.load()
    m = compute_metrics_from_trace(rows, res.units)
    for k in ("task_status", "unit_ok_rate", "tool_correctness", "tools_total",
              "retry_calls", "steps_per_unit", "llm_calls"):
        assert k in m, f"缺指标键：{k}"


def test_tool_correctness_counts_blocked():
    """L1-3：白名单外工具 → tool_correctness.blocked 计数（工具正确率原料）。"""
    td = tempfile.mkdtemp()
    eng = _mk_engine(td)
    res = eng.run_task("写一份季度报告")
    rows = eng.trace.load()
    m = compute_metrics_from_trace(rows, res.units)
    tools = m["tool_correctness"]
    assert tools["blocked"] >= 1, "prove 工具必须计为 blocked"
    assert tools["ok"] >= 1, "write_artifact 应计为 ok"


def test_run_eval_end_to_end():
    """L1-3：run_eval 统一入口——评测集子集跑出完整指标 JSON 结构。"""
    from wuxing.eval_set import load_eval_tasks
    tasks = load_eval_tasks()[:2]
    report = run_eval(tasks, llm=_ProbeLlm)
    assert report["n_tasks"] == 2
    assert "metrics" in report
    assert report["metrics"]["done_rate"] >= 0.0
    assert len(report["tasks"]) == 2


def test_cache_metrics_in_report():
    """C-1：评测报告必须含缓存指标（命中目标 90/95/99.5 的量化依据）。"""
    from wuxing.evaluate import _cache_metrics
    m = _cache_metrics({"input": 1000, "output": 100, "cache_read": 800,
                        "cache_write": 0})
    assert m["cache_read_ratio"] == 0.8, "服务端缓存读占比（目标管线）"
    assert m["input_tokens"] == 1000
    assert m["cache_saved_cost"] >= 0.0  # 节约估算（参考单价）

    m0 = _cache_metrics({})
    assert m0["cache_read_ratio"] == 0.0, "缺 usage 时零值（不崩溃）"


def test_run_eval_report_includes_cache():
    """C-1：run_eval 报告聚合缓存段（reply/shape 命中率 + 服务端占比）。"""
    from wuxing.eval_set import load_eval_tasks
    from wuxing.evaluate import run_eval
    report = run_eval(load_eval_tasks()[:2], llm=_ProbeLlm)
    cache = report["cache"]
    assert "avg_cache_read_ratio" in cache and "avg_reply_hit_rate" in cache \
        and "avg_shape_hit_rate" in cache, \
        "聚合报告必须含缓存命中率（目标监控）"


def test_cache_metrics_task_internal_scope():
    """T1：缓存口径守卫——cache_read_ratio 必须是**任务内复用**口径（用户裁决
    2026-09-07）：per-task usage 独立计算（跨任务不串扰——服务端前缀跨任务
    物理不可达，混算会虚高/虚低）。"""
    from wuxing.evaluate import _cache_metrics
    # 任务 A：大输入高命中；任务 B：小输入——分别计算（独立口径）
    a = _cache_metrics({"input": 100_000, "cache_read": 90_000})
    b = _cache_metrics({"input": 10_000, "cache_read": 2_000})
    assert a["cache_read_ratio"] == 0.9, "任务 A 独立口径（90%）"
    assert b["cache_read_ratio"] == 0.2, "任务 B 独立口径（20%——不因 A 混合虚高）"
    # 混合（错误口径）≠ 任一真实值——守卫：必须按任务隔离计算
    mixed = _cache_metrics({"input": 110_000, "cache_read": 92_000})
    assert mixed["cache_read_ratio"] != a["cache_read_ratio"] or \
        mixed["cache_read_ratio"] != b["cache_read_ratio"], \
        "混合口径可能掩盖差异——指标必须任务级"


def test_run_eval_reports_scope_field():
    """T1：评测输出必须声明缓存口径（cache_scope=task-internal）——防会话更迭
    对口径语义理解漂移（README 级留痕的机制化落地）。"""
    from wuxing.evaluate import run_eval
    report = run_eval([{"id": "T1", "task_text": "编写一个函数",
                        "suite": "unit", "difficulty": "low",
                        "expected_kinds": ["result"],
                        "acceptance_notes": "x", "source": "test"}])
    assert report.get("cache_scope") == "task-internal", \
        "评测输出必须显式声明口径（任务内复用——用户裁决）"


def test_prefix_break_detection_aggregated():
    """T5：前缀潜坏检测——later_round_misses（非首轮 miss 应为 0——毒化/
    前缀破坏异常）聚合为评测诊断信号：任何任务出现 >0 即标记。"""
    from wuxing.evaluate import prefix_break_tasks
    units = [
        # 单元 1：首轮 miss 1（正常——新任务）+ 后续轮 miss 0
        {"metrics": {"cache_breakdown": {"first_round_misses": 1,
                                         "later_round_misses": 0}}},
        # 单元 2：后续轮 miss 2（异常——前缀破坏/毒化残留）
        {"metrics": {"cache_breakdown": {"first_round_misses": 1,
                                         "later_round_misses": 2}}},
    ]
    bad = prefix_break_tasks(units)
    assert bad == 1, "后续轮 miss>0 的单元必须被检出（前缀潜坏信号）"


def test_run_eval_prefix_break_report_field():
    """T5：评测输出必须含前缀潜坏信号（cache_prefix_breaks）——CI/诊断可读。"""
    from wuxing.evaluate import run_eval
    report = run_eval([{"id": "T1", "task_text": "编写一个函数",
                        "suite": "unit", "difficulty": "low",
                        "expected_kinds": ["result"],
                        "acceptance_notes": "x", "source": "test"}])
    assert "cache_prefix_breaks" in report.get("metrics", {}), \
        "评测指标必须含前缀潜坏计数（缓存回归可检测）"


def test_cli_persists_report():
    """G1：evaluate CLI 必须把评测报告持久化到文件（评测产物可追溯）——
    stdout 管道截断即丢失（trace/指标是评测证据——不可再生）。"""
    import json
    import os
    import pathlib
    import subprocess
    import sys
    import tempfile
    out = pathlib.Path(tempfile.mkdtemp()) / "eval_out.json"
    r = subprocess.run(
        [sys.executable, "-m", "wuxing.evaluate", "--n", "1",
         "--tasks", str(pathlib.Path("eval/tasks.v1.json").resolve()),
         "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", timeout=300, check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    # 退出码正常 + 产物存在且可解析
    assert r.returncode == 0, r.stderr[-500:]
    assert out.exists(), "评测报告必须落盘（--out 指定路径）"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data.get("version") == "v1"
    assert data["items"]["n_tasks"] == 1


def test_cli_select_ids():
    """G2：CLI --ids 部分重跑（断连/分批续跑）——指定任务集合执行。"""
    import json
    import os
    import pathlib
    import subprocess
    import sys
    import tempfile
    out = pathlib.Path(tempfile.mkdtemp()) / "eval_ids.json"
    r = subprocess.run(
        [sys.executable, "-m", "wuxing.evaluate", "--ids", "cal-T17,cal-T13",
         "--tasks", str(pathlib.Path("eval/tasks.v1.json").resolve()),
         "--out", str(out)],
        capture_output=True, text=True, encoding="utf-8", timeout=300, check=False,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"})
    assert r.returncode == 0, r.stderr[-300:]
    data = json.loads(out.read_text(encoding="utf-8"))
    got = {t["id"] for t in data["items"]["tasks"]}
    assert got == {"cal-T17", "cal-T13"}, f"ids 选择必须精确（实际 {got}）"


def test_cli_help_marks_capability_test():
    """Task6：命名口径——evaluate CLI 必须标注「能力测试」（用户裁决：能力测试
    vs 真实测试——防会话更迭术语漂移）。"""
    import os
    import subprocess
    import sys
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run([sys.executable, "-m", "wuxing.evaluate", "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60, env=env, check=False)
    assert r.returncode == 0
    assert "能力测试" in (r.stdout or ""), \
        f"evaluate help 必须标注能力测试：{(r.stdout or '')[:300]}"


def test_failure_attribution_classification():
    """Task8：失败归因自动化——provider_error/no_llm_call/contract_never_passed 分类。"""
    from wuxing.evaluate import compute_failure_attribution
    from wuxing.protocols import UnitResult

    units = [
        UnitResult(unit_id="U1", domain_id="execute", status="failed"),
        UnitResult(unit_id="U2", domain_id="verify", status="failed"),
        UnitResult(unit_id="U3", domain_id="execute", status="failed"),
        UnitResult(unit_id="U4", domain_id="plan", status="ok"),  # 非失败不计
    ]
    rows = [
        {"event": "unit_started", "unit_id": "U1", "domain": "execute"},
        {"event": "llm_call", "unit_id": "U1"},
        {"event": "contract_check", "unit_id": "U1", "passed": False},
        {"event": "unit_done", "unit_id": "U1", "status": "failed",
         "provider_error": True},
        {"event": "unit_started", "unit_id": "U2", "domain": "verify"},
        {"event": "contract_check", "unit_id": "U2", "passed": False},
        {"event": "unit_done", "unit_id": "U2", "status": "failed"},
        {"event": "unit_started", "unit_id": "U3", "domain": "execute"},
        {"event": "llm_call", "unit_id": "U3"},
        {"event": "contract_check", "unit_id": "U3", "passed": False},
        {"event": "unit_done", "unit_id": "U3", "status": "failed"},
    ]
    att = compute_failure_attribution(units, rows)
    assert att["provider_error"] == 1
    assert att["no_llm_call"] == 1
    assert att["contract_never_passed"] == 1
    assert att["by_domain"]["execute"] == 2
    assert att["by_domain"]["verify"] == 1


def test_cache_metrics_official_ratio():
    """DeepSeek 官方口径：命中率 = hit/(hit+miss)——字段齐全时以官方字段为准
    （input=hit+miss 时两口径等价；不一致时官方字段优先——直接问询 API）。"""
    from wuxing.evaluate import _cache_metrics
    m = _cache_metrics({"input": 1000, "cache_read": 800, "cache_miss": 200})
    assert m["cache_read_ratio"] == 0.8, f"官方口径 hit/(hit+miss)：{m}"
    # 不一致场景（input 与实际分类不符）→ 官方字段优先
    m2 = _cache_metrics({"input": 1000, "cache_read": 800, "cache_miss": 300})
    assert m2["cache_read_ratio"] == round(800 / 1100, 4),         f"官方字段优先（hit/(hit+miss)）：{m2}"
    # 无 miss 字段（非 DeepSeek）→ 回退 hit/input（兼容口径）
    m3 = _cache_metrics({"input": 1000, "cache_read": 800})
    assert m3["cache_read_ratio"] == 0.8


def test_retry_attempts_counted_once_and_classified_by_final_attempt():
    """S1：自动重试轮不重复计样本；分类取最后一次尝试。

    场景：F-1 首轮 provider 失败 → 重试成功（units 终态 ok）→ 不计失败；
    F-2 首轮 provider 失败 → 重试后预算耗尽（units 终态 failed）→ 计一次，
    且按终轮事件分类（不误归因 provider）。
    """
    from wuxing.evaluate import compute_failure_attribution
    from wuxing.protocols import UnitResult

    units = [
        UnitResult(unit_id="F-1", domain_id="plan", status="ok"),
        UnitResult(unit_id="F-2", domain_id="execute", status="failed"),
    ]
    rows = [
        {"event": "unit_started", "unit_id": "F-1", "domain": "plan"},
        {"event": "unit_done", "unit_id": "F-1", "status": "failed",
         "provider_error": True},
        {"event": "unit_done", "unit_id": "F-1", "status": "ok"},
        {"event": "unit_started", "unit_id": "F-2", "domain": "execute"},
        {"event": "unit_done", "unit_id": "F-2", "status": "failed",
         "provider_error": True},
        {"event": "unit_done", "unit_id": "F-2", "status": "failed"},
        {"event": "llm_call", "unit_id": "F-2"},
    ]
    out = compute_failure_attribution(units, rows)
    assert out["provider_error"] == 0  # 终轮非 provider——不误归因
    assert out["other"] == 1           # F-2 计一次（重试轮不重复计）
    assert out["by_domain"]["execute"] == 1
