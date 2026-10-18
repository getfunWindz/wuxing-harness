"""全面复核产物：边界条件回归测试（2026-08 复核 21 项检查固化）。"""
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape
from golden_ratio.effort import effort_bounds
from golden_ratio.keyify import extract_keys
from golden_ratio.llm import MockLLM
from golden_ratio.models import DAG, Fragment, Node
from golden_ratio.rebalance import rebalance
from golden_ratio.segment import _merge_group, segment


def node(nid, dlv="text", cx="low", tr=("实现",), dom=None):
    return Node(id=nid, text=nid, domain_dist=dom or {"编程": 0.9},
                trades=list(tr), complexity=cx, color_weight=0.5, deliverable=dlv)


def test_empty_dag_safe():
    empty = DAG(nodes=[], edges=[])
    s = compute_shape(empty, None)
    assert DAG.max_depth(empty) == 0 and s.difficulty == 1 and DAG.is_acyclic(empty)


def test_single_node_yields_one_fragment():
    cfg = AlgorithmConfig()
    one = DAG(nodes=[node("n1")], edges=[])
    frags = segment(one, compute_shape(one, cfg), MockLLM(), cfg)
    assert len(frags) == 1


def test_merge_group_empty_input():
    cfg = AlgorithmConfig()
    assert _merge_group([], cfg, level=1) == []


def test_rebalance_empty_list_returns_zero_rounds():
    cfg = AlgorithmConfig()
    one = DAG(nodes=[node("n1")], edges=[])
    out, rounds = rebalance([], one, cfg, compute_shape(one, cfg))
    assert out == []
    assert rounds >= 0


def test_rebalance_single_fragment_no_merge():
    cfg = AlgorithmConfig()
    one = DAG(nodes=[node("n1")], edges=[])
    f = Fragment(fragment_id="F-0001", stage="segment", node_ids=["n1"],
                 text="", domain_dist={}, size=1.0)
    out, _ = rebalance([f], one, cfg, compute_shape(one, cfg))
    assert len(out) == 1


def test_effort_bounds_extremes():
    cfg = AlgorithmConfig()
    lo, hi = effort_bounds(cfg, 1.0)
    assert lo >= 0.5 and hi > lo
    assert effort_bounds(cfg, 100000.0) == (8.0, 80.0)


def test_keyify_empty_text():
    assert extract_keys("", AlgorithmConfig()) == []
