"""C4：缓存对照拆解——合成 trace 行驱动（分域/分单元）。

口径（用户裁决 2026-10-02）：**缓存命中率 = CH = 最近一次有效请求的命中率**
（主口径，替换 2026-09-30 的 token 级 Σ/Σ）；累计 Σ/Σ 保留为旁系对照。
档位 ≥70% 优秀 / ≥80% 梦幻线（用户裁决 2026-09-12）。
"""
import pathlib

from wuxing.cache_report import band_of, cache_breakdown, load_llm_calls


def _call(domain, inp, read, unit="u1"):
    return {"event": "llm_call", "domain": domain, "unit_id": unit,
            "input": inp, "cache_read": read, "output": 10}


def test_overall_token_weighted_ratio_and_band():
    calls = [_call("execute", 1000, 700), _call("execute", 1000, 900)]
    r = cache_breakdown(calls)
    assert r["input_tokens"] == 2000 and r["cache_read_tokens"] == 1600
    assert abs(r["ratio"] - 0.8) < 1e-9
    assert r["band"] == "dream"


def test_group_by_domain():
    calls = [_call("plan", 1000, 700), _call("execute", 1000, 500),
             _call("verify", 1000, 850)]
    r = cache_breakdown(calls)
    assert set(r["groups"]) == {"plan", "execute", "verify"}
    assert r["groups"]["verify"]["band"] == "dream"
    assert r["groups"]["execute"]["band"] == "below"
    assert r["groups"]["plan"]["band"] == "good"


def test_zero_input_skipped_and_missing_fields_tolerated():
    calls = [_call("execute", 0, 0), {}, {"domain": "x"}]
    r = cache_breakdown(calls)
    assert r["calls"] == 0 and r["ratio"] is None and r["band"] == ""


def test_group_by_unit():
    calls = [_call("execute", 100, 80, unit="F-1"),
             _call("execute", 100, 50, unit="F-2")]
    r = cache_breakdown(calls, group_by="unit_id")
    assert r["groups"]["F-1"]["ratio"] == 0.8
    assert r["groups"]["F-2"]["band"] == "below"


def test_band_of():
    assert band_of(None) == ""
    assert band_of(0.69) == "below"
    assert band_of(0.7) == "good"
    assert band_of(0.8) == "dream"
    assert band_of(0.95) == "dream"


def test_load_llm_calls_filters_and_tolerates_corruption(tmp_path):
    p = tmp_path / "trace.jsonl"
    p.write_text(
        '{"event": "unit_started", "unit_id": "u1"}\n'
        '{"event": "llm_call", "domain": "plan", "input": 100, "cache_read": 70}\n'
        '{broken json}\n'
        '{"event": "llm_call", "domain": "execute"}\n',
        encoding="utf-8")
    calls = load_llm_calls(p)
    assert len(calls) == 2
    assert calls[0]["domain"] == "plan"


def test_load_missing_file_returns_empty(tmp_path):
    assert load_llm_calls(pathlib.Path(tmp_path) / "nope.jsonl") == []


def test_prompt_volume_single_count_no_double_count():
    """pi 同义口径（用户裁决 2026-09-30）：命中率 = 命中 / 完整 prompt 量。

    WUXING 适配器已把 input 归一为完整 prompt 量（含命中/写入）；
    pi 字段语义 input=未缓存——等价式在 WUXING 侧即 cache_read/input，
    不得写成 cache_read/(input+cache_read+cache_write)（会重复计命中）。
    """
    calls = [{"event": "llm_call", "domain": "execute", "unit_id": "u1",
              "input": 1100, "cache_read": 400, "cache_write": 100}]
    r = cache_breakdown(calls)
    assert r["prompt_tokens"] == 1100
    assert abs(r["ratio"] - 400 / 1100) < 1e-9


def test_pi_formula_equivalent_via_uncached_split():
    """与 pi 展示式 cacheRead/(input+cacheRead+cacheWrite) 等价（数值）。"""
    calls = [{"event": "llm_call", "domain": "execute", "unit_id": "u1",
              "input": 1100, "cache_read": 400, "cache_write": 100}]
    r = cache_breakdown(calls)
    uncached = 1100 - 400 - 100          # pi 的 input 字段（未缓存部分）
    assert abs(r["ratio"] - 400 / (uncached + 400 + 100)) < 1e-9
    assert r["groups"]["execute"]["prompt_tokens"] == 1100


def test_latest_request_ch_is_primary():
    """CH 口径（用户裁决 2026-10-02）：最近一次有效请求的命中率为主口径。"""
    calls = [_call("execute", 1000, 900), _call("execute", 1000, 400)]
    r = cache_breakdown(calls)
    assert r["latest"] is not None
    assert abs(r["latest"]["ratio"] - 0.4) < 1e-9
    assert r["latest"]["band"] == "below"
    # 累计（Σ/Σ）保留为旁系
    assert abs(r["ratio"] - 0.65) < 1e-9


def test_latest_skips_zero_input():
    """零输入调用不计入「最近一次有效请求」。"""
    calls = [_call("execute", 1000, 800), _call("execute", 0, 0)]
    r = cache_breakdown(calls)
    assert r["latest"] is not None
    assert abs(r["latest"]["ratio"] - 0.8) < 1e-9


def test_latest_none_without_valid_calls():
    r = cache_breakdown([_call("execute", 0, 0), {}])
    assert r["latest"] is None


def test_latest_per_group():
    """分组拆解同样给出组内最近一次请求命中率（CH）。"""
    calls = [_call("plan", 1000, 200), _call("execute", 1000, 500),
             _call("plan", 1000, 850), _call("execute", 1000, 700)]
    r = cache_breakdown(calls)
    assert abs(r["groups"]["plan"]["latest"]["ratio"] - 0.85) < 1e-9
    assert abs(r["groups"]["execute"]["latest"]["ratio"] - 0.7) < 1e-9


def test_ch_split_from_trace_with_aux():
    """E0-6：trace 三分——首/续按 unit 分组，aux_kind 行进辅助桶。"""
    calls = [
        {"event": "llm_call", "unit_id": "F-1", "round": 1,
         "input": 1000, "cache_read": 100},
        {"event": "llm_call", "unit_id": "F-1", "round": 2,
         "input": 1200, "cache_read": 1100},
        {"event": "llm_call", "aux_kind": "shape",
         "input": 400, "cache_read": 200},
    ]
    cs = cache_breakdown(calls)["ch_split"]
    assert cs["first"]["calls"] == 1 and cs["first"]["ratio"] == 0.1
    assert cs["continuation"]["calls"] == 1
    assert cs["auxiliary"]["calls"] == 1
    assert cs["auxiliary"]["kinds"] == {"shape": 1}
    assert cs["miss_reasons"] == {"new_session": 1, "auxiliary": 1}


def test_ch_split_first_per_run_when_multiple_files(tmp_path):
    """真跑发现（E0-3）：多 trace 合并时首调用须按（run, unit）分组
    ——unit_id（如 F-1）跨任务/run 复用，跨文件去重会把后续 run 的首调用
    误归为延续。"""
    import json as _json

    from wuxing.cache_report import load_llm_calls
    f1 = tmp_path / "t1" / "trace.jsonl"
    f2 = tmp_path / "t2" / "trace.jsonl"
    for p, read in ((f1, 100), (f2, 300)):
        p.parent.mkdir(parents=True)
        p.write_text(_json.dumps(
            {"event": "llm_call", "unit_id": "F-1", "round": 1,
             "input": 1000, "cache_read": read}), encoding="utf-8")
    calls = load_llm_calls(f1) + load_llm_calls(f2)
    cs = cache_breakdown(calls)["ch_split"]
    assert cs["first"]["calls"] == 2        # 两个 run 各自的首调用
    assert cs["continuation"] is None


def test_main_latest_excludes_aux():
    """D1 口径：主展示（latest/分组/总计数）只看单元调用；辅助入 ch_split。"""
    calls = [
        {"unit_id": "F-1", "input": 1000, "cache_read": 800},
        {"aux_kind": "skill_review", "input": 200, "cache_read": 0},
    ]
    r = cache_breakdown(calls)
    assert abs(r["latest"]["ratio"] - 0.8) < 1e-9
    assert r["calls"] == 1
    assert r["ch_split"]["auxiliary"]["calls"] == 1


def test_ch_split_zero_input_skipped_and_no_aux():
    calls = [
        {"unit_id": "F-2", "input": 500, "cache_read": 400},
        {"unit_id": "F-2", "input": 600, "cache_read": 600},
        {"unit_id": "F-1", "input": 0, "cache_read": 0},
    ]
    cs = cache_breakdown(calls)["ch_split"]
    assert cs["first"]["calls"] == 1 and cs["first"]["ratio"] == 0.8
    assert cs["continuation"]["calls"] == 1
    assert cs["auxiliary"] is None
    assert cs["miss_reasons"] == {}
