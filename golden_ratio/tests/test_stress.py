"""压力测试框架（报告 §6 方向 B 落地，TDD 先行）。

六维矩阵：超大规模 / 极端结构 / 参数极端 / 数据异常 / 故障注入 / 长时间稳定。
"""
import time

import pytest

from golden_ratio.config import AlgorithmConfig
from golden_ratio.experiment import _run_task
from golden_ratio.llm import MockLLM
from golden_ratio.models import DAG, Node


def node(nid, w=0.5, dlv="text", cx="low", dom=None, trades=None, effort_pts=None):
    return Node(id=nid, text=nid, domain_dist=dom or {"写作": 0.9},
                trades=trades or ["创作"], complexity=cx, color_weight=w,
                deliverable=dlv)


def gen_chain(n, w=0.5):
    """深链：n 个节点链式依赖。"""
    nodes = [node(f"n{i}", w=w) for i in range(n)]
    edges = [(f"n{i}", f"n{i+1}") for i in range(n - 1)]
    return DAG(nodes=nodes, edges=edges)


def gen_star(n, w=0.5):
    """星形扇出：中心节点连接 n-1 个叶子。"""
    nodes = [node(f"n{i}", w=w) for i in range(n)]
    edges = [("n0", f"n{i}") for i in range(1, n)]
    return DAG(nodes=nodes, edges=edges)


def gen_near_cycle(n):
    """近环：n 节点环去掉一条边（仍无环，但接近环结构）。"""
    nodes = [node(f"n{i}") for i in range(n)]
    edges = [(f"n{i}", f"n{i+1}") for i in range(n - 1)]
    return DAG(nodes=nodes, edges=edges)


def gen_isolated(n_clusters, per_cluster):
    """孤立节点群：多个小簇互不连通。"""
    nodes, edges = [], []
    base = 0
    for c in range(n_clusters):
        for i in range(per_cluster):
            nodes.append(node(f"n{base + i}"))
            if i > 0:
                edges.append((f"n{base + i - 1}", f"n{base + i}"))
        base += per_cluster
    return DAG(nodes=nodes, edges=edges)


# ============ 1. 超大规模 ============

def test_chain_1000_nodes_correct_and_fast():
    dag = gen_chain(1000)
    cfg = AlgorithmConfig()
    t0 = time.time()
    _, frags, _ = _run_task(dag, cfg, MockLLM())
    dt = time.time() - t0
    flat = [nid for f in frags for nid in f.node_ids]
    assert sorted(flat) == sorted(n.id for n in dag.nodes)   # 无丢失
    assert DAG.is_acyclic(dag)
    assert dt < 5.0, f"1000 节点耗时 {dt:.2f}s 超限"


def test_star_300_fanout():
    dag = gen_star(300)
    cfg = AlgorithmConfig()
    shape, frags, _ = _run_task(dag, cfg, MockLLM())
    flat = [nid for f in frags for nid in f.node_ids]
    assert len(flat) == 300
    assert shape.difficulty >= 1


def test_batch_500_tasks_fast():
    """500 个任务批量（每个 5~20 节点）总耗时上限。"""
    import random
    rng = random.Random(7)
    cfg = AlgorithmConfig()
    llm = MockLLM()
    t0 = time.time()
    for _ in range(500):
        n = rng.randint(5, 20)
        dag = gen_chain(n)
        _run_task(dag, cfg, llm)
    dt = time.time() - t0
    assert dt < 60.0, f"500 任务批量耗时 {dt:.1f}s 超限"


# ============ 2. 极端结构 ============

def test_isolated_clusters_no_crash():
    dag = gen_isolated(50, 3)          # 50 个孤立小簇
    cfg = AlgorithmConfig()
    _, frags, _ = _run_task(dag, cfg, MockLLM())
    flat = [nid for f in frags for nid in f.node_ids]
    assert len(flat) == 150            # 全部节点被覆盖


def test_near_cycle_1000():
    dag = gen_near_cycle(1000)
    cfg = AlgorithmConfig()
    assert DAG.is_acyclic(dag)
    _, frags, _ = _run_task(dag, cfg, MockLLM())
    assert len(frags) >= 1


# ============ 3. 参数极端 ============

def test_all_tiny_effort_nodes():
    """全部 <1h 节点：8/80 下限缩放应有效（不崩、有限碎片）。"""
    from golden_ratio.effort import effort_bounds
    cfg = AlgorithmConfig()
    lo, _ = effort_bounds(cfg, 0.5)
    assert lo < 8.0                      # 下限缩放
    dag = gen_chain(50)
    _, frags, _ = _run_task(dag, cfg, MockLLM())
    assert len(frags) >= 1


def test_giant_single_node_effort():
    """单节点工时 >100h（data high L5）：不得无限合并，且硬合规允许单块。"""
    cfg = AlgorithmConfig()
    from golden_ratio.effort import node_effort
    big = node("big", dlv="data", cx="high", dom={"数据": 0.9}, trades=["实现"])
    from golden_ratio.experiment import compliance_levels
    e = node_effort(big, None, cfg, level=5)
    assert 60 < e < 120                   # 单节点最大 62.4h（L5 data high）
    assert compliance_levels(e, cfg) == "standard"      # 62.4h 在 [8,80] 内
    assert compliance_levels(120.5, cfg) == "violation" # 超硬合规上限才违规


# ============ 4. 数据异常 ============

def test_duplicate_node_id_rejected():
    from golden_ratio.calibrate import build_dag
    spec = {"nodes": [{"id": "n1", "text": "a", "domain": {"写作": 0.9}, "trades": ["创作"],
                       "complexity": "low", "deliverable": "text", "weight": 0.5},
                      {"id": "n1", "text": "b", "domain": {"写作": 0.9}, "trades": ["创作"],
                       "complexity": "low", "deliverable": "text", "weight": 0.5}],
            "edges": []}
    with pytest.raises(ValueError):
        build_dag(spec)


def test_empty_domain_dist_handled():
    cfg = AlgorithmConfig()
    dag = DAG(nodes=[node("n1", dom={})], edges=[])
    from golden_ratio.difficulty import compute_shape
    s = compute_shape(dag, cfg)
    assert s.difficulty >= 1              # 空领域分布不崩（主领域缺失回退）


# ============ 5. 故障注入（真 LLM 前置） ============

def test_shape_task_retry_on_bad_output():
    """模拟 LLM 返回非法结构：形状化应重试（§3.1 约束）。"""
    from golden_ratio.shape import shape_task

    class BadLLM(MockLLM):
        def __init__(self):
            super().__init__()
            self.bad_calls = 0
        def shape_task(self, task_text):
            self.bad_calls += 1
            if self.bad_calls == 1:
                return {"nodes": [], "edges": [], "total_size": 0}   # 空 DAG
            return super().shape_task(task_text)

    dag, _ = shape_task("写一份季度报告", BadLLM())
    assert len(dag.nodes) == 3            # 重试后正常


# ============ 6. 长时间稳定性 ============

def test_1000_rounds_no_state_leak():
    """1000 轮重复运行：EMA 状态有界收敛，结果稳定。"""
    from golden_ratio.experiment import ema_update
    stats = {"ok": 0.0, "over": 0.0, "under": 0.0}
    import random
    rng = random.Random(1)
    for _ in range(1000):
        status = rng.choice(["ok", "over", "under"])
        stats = ema_update(stats, status, decay=0.9)
    total = sum(stats.values())
    assert total < 12.0                    # EMA 稳态有界（≈1/(1-0.9)=10）
    assert all(v >= 0 for v in stats.values())


def test_repeated_runs_deterministic():
    """同一任务重复运行结果一致（无隐藏状态泄漏）。"""
    cfg = AlgorithmConfig()
    dag = gen_chain(20)
    r1 = [f.fragment_id for f in _run_task(dag, cfg, MockLLM())[1]]
    r2 = [f.fragment_id for f in _run_task(dag, cfg, MockLLM())[1]]
    assert r1 == r2
