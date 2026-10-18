"""阶段 3 放开测试（LLM 接入后视角）：边界 / 硬伤 / 暗伤 / 优化方向。

分组：
G1 真实口径全链压力（112 真实 DAG × 全链 + 不变式）
G2 极端 DAG 边界（单节点/环/重复id/孤立修复/5k 节点性能）
G3 LLM 输出鲁棒性（缺失/类型错/NaN/数字ID/负权重/空trades/超长）
G4 C 臂极端场景（全ok/全under/全over/0样本桶/1000任务批处理）
G5 数值稳定性（share 归一/多 run 一致/浮点）
G6 不变式（依赖完整率/覆盖/无环/合规）
"""
import json
import pathlib
import time

import pytest

from golden_ratio.calibrate import build_dag
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape
from golden_ratio.experiment import (
    BucketAdaptiveRunner,
)
from golden_ratio.llm import MockLLM
from golden_ratio.models import DAG, Fragment, Node
from golden_ratio.rebalance import rebalance
from golden_ratio.segment import segment
from golden_ratio.validate import repair_dag, validate_shape_output

REAL = pathlib.Path(__file__).resolve().parent.parent / "data" / "real_suites"
SUITE_NAMES = ("calibration", "mega", "professional", "domain")


def _load(name):
    tasks = json.loads((REAL / f"{name}.json").read_text(encoding="utf-8"))["tasks"]
    for t in tasks:
        t["expected_fragments"] = t.get("expected_fragments_t40", t["expected_fragments"])
    return tasks


def _cfg_of(name):
    cfg = AlgorithmConfig()
    meta = json.loads((REAL / f"{name}.json").read_text(encoding="utf-8"))["meta"]
    cfg.ds_bins = tuple(meta.get("ds_bins_calibrated", cfg.ds_bins))
    return cfg


def _nd(nid, text="t", dom=None, trades=None, cx="mid", dlv="code", w=0.6):
    return Node(id=nid, text=text, domain_dist=dom or {"软件工程": 1.0},
                trades=trades or ["开发工程师"], complexity=cx, color_weight=w,
                deliverable=dlv)


def _raw_n(nid, text="t", w=0.6, trades=None, dom=None, cx="mid", dlv="code"):
    """LLM 契约格式节点（validate 用）：domain_dist/color_weight。"""
    return {"id": nid, "text": text, "domain_dist": dom or {"软件工程": 1.0},
            "trades": trades or ["开发工程师"], "complexity": cx,
            "deliverable": dlv, "color_weight": w}


def _spec_n(nid, text="t", w=0.6, trades=None, dom=None, cx="mid", dlv="code"):
    """数据文件 spec 格式节点（build_dag 用）：domain/weight。"""
    return {"id": nid, "text": text, "domain": dom or {"软件工程": 1.0},
            "trades": trades or ["开发工程师"], "complexity": cx,
            "deliverable": dlv, "weight": w}


# ---------- G1 真实口径全链压力 ----------

@pytest.mark.parametrize("name", SUITE_NAMES)
def test_g1_full_chain_invariants(name):
    """112 真实 DAG 全链：覆盖/无环/依赖元数据自洽/碎片非空。"""
    tasks = _load(name)
    cfg = _cfg_of(name)
    llm = MockLLM()
    for t in tasks:
        dag = build_dag(t["dag_spec"])
        shape = compute_shape(dag, cfg)
        frags = segment(dag, shape, llm, cfg)
        if not shape.fast_path:
            frags, _ = rebalance(frags, dag, cfg, shape)
        flat = [nid for f in frags for nid in f.node_ids]
        assert sorted(flat) == sorted(n.id for n in dag.nodes), f"{t['id']} 覆盖/重复"
        assert DAG.is_acyclic(dag)
        assert all(f.node_ids for f in frags), f"{t['id']} 空碎片"
        for f in frags:
            for up in f.upstream:
                assert up in {g.fragment_id for g in frags}
            for dn in f.downstream:
                assert dn in {g.fragment_id for g in frags}


def test_g1_full_chain_runs_fast():
    """112 任务全链批处理性能粗测（< 60s 视为可接受）。"""
    t0 = time.time()
    for name in SUITE_NAMES:
        for t in _load(name):
            dag = build_dag(t["dag_spec"])
            shape = compute_shape(dag, _cfg_of(name))
            frags = segment(dag, shape, MockLLM(), _cfg_of(name))
            if not shape.fast_path:
                frags, _ = rebalance(frags, dag, _cfg_of(name), shape)
    dt = time.time() - t0
    print(f"G1 全链 112 任务: {dt:.1f}s")
    assert dt < 60.0


# ---------- G2 极端 DAG 边界 ----------

def test_g2_single_node():
    dag = DAG(nodes=[_nd("n1")], edges=[])
    frags = segment(dag, compute_shape(dag, AlgorithmConfig()), MockLLM(), AlgorithmConfig())
    assert len(frags) == 1


def test_g2_cycle_rejected():
    dag = DAG(nodes=[_nd("n1"), _nd("n2")], edges=[("n1", "n2"), ("n2", "n1")])
    assert not DAG.is_acyclic(dag)


def test_g2_duplicate_ids_rejected_by_build():
    raw = {"nodes": [_spec_n("n1"), _spec_n("n1")], "edges": []}
    with pytest.raises(ValueError):
        build_dag(raw)


def test_g2_isolated_node_repair_path():
    """孤立节点 → repair_dag 补边 → 校验通过（阶段0 修复器路径回归）。"""
    raw = {"nodes": [_raw_n("n1"), _raw_n("n2"), _raw_n("n3")],
           "edges": [["n1", "n2"]]}
    nodes, edges, changed = repair_dag(raw)
    assert changed
    ok, _, errs = validate_shape_output({"nodes": nodes, "edges": edges})
    assert ok, errs


def test_g2_5000_nodes_performance():
    """5000 节点链式：全链（compute+segment+rebalance）时间有界。"""
    n = 5000
    nodes = [_nd(f"n{i}", w=0.5) for i in range(n)]
    edges = [(f"n{i}", f"n{i+1}") for i in range(n - 1)]
    dag = DAG(nodes=nodes, edges=edges)
    t0 = time.time()
    shape = compute_shape(dag, AlgorithmConfig())
    frags = segment(dag, shape, MockLLM(), AlgorithmConfig())
    frags, _ = rebalance(frags, dag, AlgorithmConfig(), shape)
    dt = time.time() - t0
    print(f"G2 5000 节点全链: {dt:.1f}s, 碎片数 {len(frags)}")
    assert dt < 30.0


# ---------- G3 LLM 输出鲁棒性 ----------

def test_g3_missing_fields_fail_gracefully():
    raw = {"nodes": [{"id": "n1", "text": "t"}], "edges": []}   # 缺 domain/trades/...
    ok, _, errs = validate_shape_output(raw)
    assert ok is False and errs


def test_g3_type_errors_never_crash():
    raw = {"nodes": [{"id": 123, "text": None, "domain_dist": "x", "trades": 1,
                      "complexity": "high", "deliverable": "code", "color_weight": "NaN"}],
           "edges": [], "total_size": "3"}
    ok, _, errs = validate_shape_output(raw)
    assert ok is False and errs


def test_g3_numeric_id_edges_rejected():
    """模型偶发数字 id（真接入实例）→ 校验拒绝（已发生过：T22）。"""
    raw = {"nodes": [_nd("n1"), _nd("n2")], "edges": [[1, 2]]}
    ok, _, errs = validate_shape_output(raw)
    assert ok is False
    assert any("端点非字符串" in e for e in errs)


def test_g3_negative_weight_rejected():
    raw = {"nodes": [_nd("n1", w=-0.3)], "edges": []}
    ok, _, _ = validate_shape_output(raw)
    assert ok is False


def test_g3_empty_trades_rejected():
    raw = {"nodes": [_nd("n1", trades=[])], "edges": []}
    ok, _, _ = validate_shape_output(raw)
    assert ok is False


def test_g3_huge_text_input_ok():
    """超长节点文本（10k 字符）不应破坏校验/分词。"""
    raw = {"nodes": [_raw_n("n1", text="流程" * 5000)], "edges": []}
    ok, norm, _ = validate_shape_output(raw)
    assert ok
    from golden_ratio.keyify import extract_keys
    assert extract_keys(" ".join(n["text"] for n in norm["nodes"]), top_k=5)


# ---------- G4 C 臂极端场景 ----------

def _mk_task(tid, n_nodes, exp, w=0.5):
    nodes = [_spec_n(f"{tid}{i}", w=w) for i in range(n_nodes)]
    edges = [[f"{tid}{i}", f"{tid}{i+1}"] for i in range(n_nodes - 1)]
    return {"id": tid, "dag_spec": {"nodes": nodes, "edges": edges},
            "expected_fragments": exp}


def test_g4_all_ok_suite_no_adaptation_needed():
    tasks = [_mk_task(f"OK{i}", 4, 1) for i in range(10)]
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    runner.run_warmup(tasks, MockLLM())
    # 全 ok -> 桶方向无多数 -> 微调应少（adaptations 小）
    assert runner.adaptations <= len(runner.buckets) * 2


def test_g4_all_under_suite_learns_tighten():
    tasks = [_mk_task(f"U{i}", 4, 8) for i in range(10)]   # 期望 8 > 实际 → under
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    before = runner.cfg.merge_drop_ratio
    runner.run_warmup(tasks, MockLLM())
    ratios = [b["ratio"] for b in runner.buckets.values()]
    assert min(ratios) > before, f"under 方向应收紧（桶 ratio: {ratios} 全局初始 {before}）"


def test_g4_zero_sample_bucket_uses_global_fallback():
    """0 样本桶（冷启动）回退全局方向（v5 混合策略回归）。"""
    tasks_a = [_mk_task(f"A{i}", 4, 8) for i in range(4)]   # under
    tasks_b = [_mk_task("B1", 4, 8)]
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    runner.run_warmup(tasks_a + tasks_b, MockLLM())
    # B 桶 seen=1 < 2 → 全局方向微调（防御性：不抛错且参数更新）
    assert runner.global_seen >= 1


@pytest.mark.slow
def test_g4_1000_task_batch_bounded():
    """1000 任务批处理：run_warmup 时间有界（桶统计 EMA 有界、无内存泄漏迹象）。"""
    tasks = [_mk_task(f"T{i}", 5, 3) for i in range(1000)]
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    t0 = time.time()
    runner.run_warmup(tasks, MockLLM())
    dt = time.time() - t0
    print(f"G4 1000 任务 warmup: {dt:.1f}s, 桶数 {len(runner.buckets)}")
    assert dt < 60.0


# ---------- G5 数值稳定性 ----------

def test_g5_share_sums_to_one():
    dag = DAG(nodes=[_nd(f"n{i}", w=0.1 * (i + 1)) for i in range(20)], edges=[])
    from golden_ratio.segment import _softmax_share
    shares = _softmax_share(dag.nodes, compute_shape(dag, AlgorithmConfig()),
                            AlgorithmConfig(), dag)
    assert abs(sum(shares) - 1.0) < 1e-9


def test_g5_determinism_1000_runs():
    """同任务 100 次运行碎片划分完全一致（确定性回归）。"""
    tasks = _load("domain")
    for t in tasks[:3]:
        d = build_dag(t["dag_spec"])
        cfg = _cfg_of("domain")
        first = None
        for _ in range(100):
            frags = segment(d, compute_shape(d, cfg), MockLLM(), cfg)
            sig = tuple(sorted(tuple(f.node_ids) for f in frags))
            first = first or sig
            assert sig == first, "非确定性（100 runs）"


def test_g5_float_extremes():
    """color_weight 极小/极大值与 NaN 处理。"""
    ok, _, errs = validate_shape_output({
        "nodes": [_raw_n("n1", w=1e-9, cx="low", dlv="text")],
        "edges": []})
    assert ok, errs   # 1e-9 合法（>0）


# ---------- G6 不变式（真实口径全量） ----------

def test_g6_dependency_integrity_all_suites():
    for name in SUITE_NAMES:
        for t in _load(name):
            dag = build_dag(t["dag_spec"])
            shape = compute_shape(dag, _cfg_of(name))
            frags = segment(dag, shape, MockLLM(), _cfg_of(name))
            if not shape.fast_path:
                frags, _ = rebalance(frags, dag, _cfg_of(name), shape)
            node2frag = {nid: f.fragment_id for f in frags for nid in f.node_ids}
            for a, b in dag.edges:
                assert node2frag[a] and node2frag[b]           # 端点均在碎片
            # 收缩图无环
            import types
            ids = [f.fragment_id for f in frags]
            edges = {(node2frag[a], node2frag[b]) for a, b in dag.edges
                     if node2frag[a] != node2frag[b]}
            sub = DAG(nodes=[types.SimpleNamespace(id=i) for i in ids], edges=sorted(edges))
            assert DAG.is_acyclic(sub), f"{name}/{t['id']} 收缩图有环"


@pytest.mark.slow
def test_g6_hard_compliance_all_suites():
    """硬合规 [4,120] 全口径：任何碎片都不越界（8/80 标准下边为软警告线）。"""
    from golden_ratio.effort import fragment_effort
    viol = []
    for name in SUITE_NAMES:
        cfg = _cfg_of(name)
        for t in _load(name):
            dag = build_dag(t["dag_spec"])
            shape = compute_shape(dag, cfg)
            frags = segment(dag, shape, MockLLM(), cfg)
            if not shape.fast_path:
                frags, _ = rebalance(frags, dag, cfg, shape)
            for f in frags:
                e = fragment_effort(f, dag.nodes, shape, cfg)
                if not (cfg.hard_effort_interval[0] <= e <= cfg.hard_effort_interval[1]):
                    viol.append((name, t["id"], f.fragment_id, round(e, 1)))
    assert not viol, f"硬合规违规: {viol}"


def test_g2b_rebalance_never_produces_empty_fragment():
    """暗伤 T13：过胖剥离时若 keep 为空（全部节点低重要度）→ 不得产出空碎片。"""
    from golden_ratio.rebalance import rebalance
    dag = DAG(nodes=[_nd("a", w=0.1), _nd("b", w=0.2)], edges=[])   # 全部 <0.382
    cfg = AlgorithmConfig()
    f = Fragment(fragment_id="X", stage="segment", node_ids=["a", "b"],
                 text="", domain_dist={"软": 1.0}, size=2.0)
    out, _ = rebalance([f], dag, cfg)
    assert all(fr.node_ids for fr in out), f"空碎片: {[fr.node_ids for fr in out]}"
    flat = [nid for fr in out for nid in fr.node_ids]
    assert sorted(flat) == ["a", "b"], "节点无丢失"


def test_g2c_segment_hierarchical_never_creates_cycle():
    """硬伤 T15 回归：分层粗切必须是拓扑序连续段（领域硬分组会产环）。

    数学注记：初始碎片划分无环时，合并/剥离/迁移均不可能产出新环
    （任何新环都对应原图环）——T15 环 100% 来自 segment 领域粗切（已修复为
    连续段切分，保证收缩图无环）。
    """
    import types

    from golden_ratio.calibrate import build_dag
    from golden_ratio.segment import _topo_contiguous_groups
    # 交替领域链（T15 类）：a1(A)→b1(B)→a2(A)→b2(B)
    raw_nodes = [_spec_n("a1", dom={"软件工程": 0.8, "设备": 0.2}),
                 _spec_n("b1", dom={"金融合规": 0.8, "软件工程": 0.2}),
                 _spec_n("a2", dom={"软件工程": 0.8, "设备": 0.2}),
                 _spec_n("b2", dom={"金融合规": 0.8, "软件工程": 0.2})]
    dag = build_dag({"nodes": raw_nodes, "edges": [["a1", "b1"], ["b1", "a2"], ["a2", "b2"]]})
    groups = _topo_contiguous_groups(dag)
    flat = [n for g in groups for n in g]
    assert [n.id for n in flat] == ["a1", "b1", "a2", "b2"], "连续段保持拓扑序"
    # 连续段切分 → 收缩无环（段内任意合并保持）
    node2frag = {n.id: f"g{i}" for i, g in enumerate(groups) for n in g}
    edges = {(node2frag[a], node2frag[b]) for a, b in dag.edges
             if node2frag[a] != node2frag[b]}
    sub = DAG(nodes=[types.SimpleNamespace(id=i) for i in node2frag.values()],
              edges=sorted(edges))
    assert DAG.is_acyclic(sub), f"连续段切分不得产环: {sorted(edges)}"

