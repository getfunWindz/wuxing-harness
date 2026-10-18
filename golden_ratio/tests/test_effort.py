"""工时规则表 v1 测试（WBS 8/80 调研结论落地）。"""
import pytest

from golden_ratio.config import AlgorithmConfig
from golden_ratio.effort import fragment_effort, node_effort
from golden_ratio.models import Fragment, Node


def node(nid, dlv="text", cx="mid", trades=("实现",), dom=None, w=0.5):
    return Node(id=nid, text=nid, domain_dist=dom or {"编程": 0.9},
                trades=list(trades), complexity=cx, color_weight=w, deliverable=dlv)


def test_node_effort_scales_with_difficulty():
    cfg = AlgorithmConfig()
    n1 = node("a", cx="mid")                       # L1
    n4 = node("b", cx="high")                      # L4 权重更重
    e1 = node_effort(n1, None, cfg, level=1)
    e4 = node_effort(n4, None, cfg, level=4)
    assert e4 > e1                                 # 高难度档工时更大


def test_node_effort_trade_coef_applied():
    cfg = AlgorithmConfig()
    slow = node("a", trades=("实现",))
    fast = node("b", trades=("创作",))
    e_slow = node_effort(slow, None, cfg, level=2)
    e_fast = node_effort(fast, None, cfg, level=2)
    assert e_slow > e_fast                         # 实现 > 创作系数


def test_node_effort_scale_with_weight_pts():
    # 规模信号：weight_pts 越大（data high=15 vs text low=3）→ 工时越大
    cfg = AlgorithmConfig()
    small = node("a", dlv="text", cx="low")
    big = node("b", dlv="data", cx="high")
    assert node_effort(big, None, cfg, level=2) > node_effort(small, None, cfg, level=2)


def test_fragment_effort_sums_nodes():
    cfg = AlgorithmConfig()
    frag = Fragment(fragment_id="F-0001", stage="segment", node_ids=["a", "b"],
                    text="", domain_dist={})
    dag_nodes = [node("a", cx="low"), node("b", cx="mid")]
    e = fragment_effort(frag, dag_nodes, None, cfg, level=2)
    assert e == pytest.approx(node_effort(dag_nodes[0], None, cfg, level=2) +
                              node_effort(dag_nodes[1], None, cfg, level=2))


def test_effort_scale_reasonable_for_typical_fragments():
    # 网站典型碎片（L4 代码 high × 3）总工时应落在 [8, 80] 内
    cfg = AlgorithmConfig()
    nodes = [node("n3", dlv="code", cx="high"), node("n4", dlv="code", cx="high"),
             node("n5", dlv="code", cx="mid", trades=("测试",))]
    frag = Fragment(fragment_id="F-0001", stage="segment", node_ids=["n3", "n4", "n5"],
                    text="", domain_dist={})
    e = fragment_effort(frag, nodes, None, cfg, level=4)
    assert cfg.effort_interval[0] <= e <= cfg.effort_interval[1]


def test_effort_bounds_scale_with_total():
    # 8/80 按任务总工时缩放（用户决策：保持灵活可变）
    from golden_ratio.effort import effort_bounds
    cfg = AlgorithmConfig()
    lo1, hi1 = effort_bounds(cfg, total_effort=20.0)
    assert (lo1, hi1) == (5.0, 20.0)             # [min(8,20/4), min(80,20)] 小任务整块合法
    lo2, hi2 = effort_bounds(cfg, total_effort=40.0)
    assert (lo2, hi2) == (8.0, 40.0)
    lo3, hi3 = effort_bounds(cfg, total_effort=200.0)
    assert (lo3, hi3) == (8.0, 80.0)             # 大任务回到标准 8/80


def test_effort_bounds_monotonic():
    from golden_ratio.effort import effort_bounds
    cfg = AlgorithmConfig()
    prev = effort_bounds(cfg, 10.0)
    for t in (30.0, 60.0, 120.0, 300.0):
        cur = effort_bounds(cfg, t)
        assert cur[1] >= prev[1] and cur[0] >= prev[0]
        prev = cur
