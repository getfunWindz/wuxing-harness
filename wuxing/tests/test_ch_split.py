"""E0-6：CH 观测细分——三分（首调用/延续/辅助调用）+ miss 归因 + 辅助计账。

口径（计划 docs/plans/2026-10-03-wuxing-e06-ch-observation.md §0）：
- 首调用 = 单元第 1 次调用；延续 = 单元内其余；辅助 = 单元外（aux_kind）。
- miss 归因（likely cause 粗分）：辅助→auxiliary；首且 ratio<0.7→new_session；
  延续且 ratio<0.7→prefix_change；健康（≥0.7）不归因。
"""
from wuxing.usage_tracker import band_of, miss_reason, split_calls


def _u(inp, read):
    return {"input": inp, "output": 1, "cache_read": read, "cache_write": 0}


def test_band_and_miss_reason():
    assert band_of(0.8) == "dream" and band_of(0.7) == "good"
    assert band_of(0.5) == "below" and band_of(None) == ""
    assert miss_reason(_u(100, 0), is_first=True) == "new_session"
    assert miss_reason(_u(100, 80), is_first=True) is None      # 健康（FSC 延续命中）
    assert miss_reason(_u(100, 10), is_first=False) == "prefix_change"
    assert miss_reason(_u(100, 0), is_first=False, is_aux=True) == "auxiliary"
    assert miss_reason(_u(0, 0), is_first=True) is None          # input=0 不归因


def test_split_calls_first_continuation_and_reasons():
    r = split_calls([_u(100, 10), _u(200, 150), _u(300, 0)])
    assert r["first"]["calls"] == 1 and r["first"]["ratio"] == 0.1
    assert r["first"]["band"] == "below"
    assert r["continuation"]["calls"] == 2
    assert r["continuation"]["prompt_tokens"] == 500
    assert r["continuation"]["cache_read_tokens"] == 150
    assert r["miss_reasons"] == {"new_session": 1, "prefix_change": 1}


def test_split_calls_empty_and_tolerates_garbage():
    r = split_calls([])
    assert r["first"] is None and r["continuation"] is None
    assert r["miss_reasons"] == {}
    r2 = split_calls([None, "x", _u(100, 80)])  # 非 dict 行剔除
    assert r2["first"]["calls"] == 1


def test_runner_unit_metrics_has_ch_split():
    """Runner 单元 metrics 携带三分结构（usage 段差分驱动）。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    class SplitLlm:
        def __init__(self):
            self.usage_history = []

        def name(self):
            return "split"

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = SplitLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    from wuxing.usage_tracker import UsageTracker
    r._usage = UsageTracker(llm)             # run_unit 内的同款装配
    r._usage_snap = r._usage.snapshot()      # 差分起点（假 LLM 回退）
    llm.usage_history += [_u(100, 10), _u(200, 150)]
    cs = r._unit_metrics(llm)["ch_split"]
    assert cs["first"]["calls"] == 1 and cs["first"]["ratio"] == 0.1
    assert cs["continuation"]["calls"] == 1 and cs["continuation"]["ratio"] == 0.75
    assert cs["miss_reasons"] == {"new_session": 1}


def _fake_unit(metrics):
    return type("U", (), {"metrics": metrics})()


def test_aux_ledger_merges_into_metrics():
    """辅助账目（shape/评审/分支摘要）计入任务账目；三分汇总正确。"""
    import pathlib
    import tempfile

    from wuxing.engine import Engine
    e = Engine(workdir=pathlib.Path(tempfile.mkdtemp()))
    snap = e._task_start_snapshot()
    e._aux_calls = [{"kind": "shape", "calls": 1,
                     "usage": {"input": 100, "output": 5,
                               "cache_read": 50, "cache_write": 0},
                     "ts": 1.0}]
    units = [_fake_unit({
        "llm_calls": 2,
        "usage": {"input": 1000, "output": 10,
                  "cache_read": 700, "cache_write": 0},
        "ch_split": {
            "first": {"calls": 1, "prompt_tokens": 400,
                      "cache_read_tokens": 100,
                      "ratio": 0.25, "band": "below"},
            "continuation": {"calls": 1, "prompt_tokens": 600,
                             "cache_read_tokens": 600,
                             "ratio": 1.0, "band": "dream"},
            "miss_reasons": {"new_session": 1},
        },
    })]
    m = e._collect_metrics(units, snap)
    assert m["llm_calls"] == 3                      # 单元 2 + 辅助 1
    assert m["usage"]["input"] == 1100
    aux = m["ch_split"]["auxiliary"]
    assert aux["calls"] == 1 and aux["ratio"] == 0.5
    assert aux["kinds"] == {"shape": 1}
    assert m["ch_split"]["first"]["calls"] == 1
    assert m["ch_split"]["first"]["ratio"] == 0.25
    assert m["ch_split"]["continuation"]["ratio"] == 1.0
    assert m["ch_split"]["miss_reasons"] == {"new_session": 1,
                                              "auxiliary": 1}


def test_run_task_metrics_has_ch_split():
    """任务 metrics 携带三分结构（E0-6 引擎集成线）。"""
    import pathlib
    import tempfile

    from wuxing.engine import Engine
    m = Engine(workdir=pathlib.Path(tempfile.mkdtemp())).\
        run_task("写一封请假邮件").metrics
    cs = m["ch_split"]
    assert cs["first"] is None or cs["first"]["calls"] >= 1
    assert "auxiliary" in cs and "miss_reasons" in cs
