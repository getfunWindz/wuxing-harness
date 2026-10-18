from golden_ratio.config import AlgorithmConfig
from golden_ratio.models import DAG, Fragment, Node
from golden_ratio.rebalance import low_importance_ratio, rebalance


def node(nid, w):
    return Node(id=nid, text=nid, domain_dist={"写作": 1.0}, trades=["创作"],
                complexity="low", color_weight=w, deliverable="text")


def test_low_importance_ratio_light_node():
    dag = DAG(nodes=[node("a", 0.9), node("b", 0.1)], edges=[])
    cfg = AlgorithmConfig()
    f = Fragment(fragment_id="F-0001", stage="segment", node_ids=["a", "b"],
                 text="", domain_dist={}, size=2.0)
    r = low_importance_ratio(f, dag, cfg)
    assert abs(r - 0.1) < 1e-9          # 0.1/(0.9+0.1)


def test_rebalance_splits_fat_fragment():
    # 过胖碎片：低重要度占比 r = 0.9/1.4 ≈ 0.643 > 0.618 → 低重要度节点被迁出成新碎片
    dag = DAG(nodes=[node("a", 0.5), node("b", 0.3), node("c", 0.3), node("d", 0.3)], edges=[])
    cfg = AlgorithmConfig()
    f = Fragment(fragment_id="F-0001", stage="segment", node_ids=["a", "b", "c", "d"],
                 text="", domain_dist={}, size=1.4)
    out, _ = rebalance([f], dag, cfg)
    flat = [nid for o in out for nid in o.node_ids]
    assert sorted(flat) == ["a", "b", "c", "d"]     # 节点无丢失
    assert any(set(o.node_ids) == {"b", "c", "d"} for o in out)  # 低权重节点集中到新碎片


def test_rebalance_merges_tiny_fragment():
    dag = DAG(nodes=[node("a", 0.5), node("b", 0.5)], edges=[])
    cfg = AlgorithmConfig()
    big = Fragment(fragment_id="F-0001", stage="segment", node_ids=["a"],
                   text="", domain_dist={}, size=0.1)
    tiny = Fragment(fragment_id="F-0002", stage="segment", node_ids=["b"],
                    text="", domain_dist={}, size=1.9)
    out, _ = rebalance([big, tiny], dag, cfg)
    assert len(out) == 1


def test_rebalance_terminates_within_max_rounds():
    dag = DAG(nodes=[node(f"n{i}", 0.5) for i in range(5)], edges=[])
    cfg = AlgorithmConfig()
    frags = [Fragment(fragment_id=f"F-{i:04d}", stage="segment", node_ids=[f"n{i}"],
                      text="", domain_dist={}, size=1.0) for i in range(5)]
    out, _ = rebalance(frags, dag, cfg)
    assert len(out) >= 1


def test_rebalance_keeps_all_nodes():
    dag = DAG(nodes=[node("a", 0.9), node("b", 0.2), node("c", 0.9)],
              edges=[("a", "b"), ("b", "c")])
    cfg = AlgorithmConfig()
    fa = Fragment(fragment_id="F-0001", stage="segment", node_ids=["a"],
                  text="", domain_dist={}, size=1.0)
    fb = Fragment(fragment_id="F-0002", stage="segment", node_ids=["b", "c"],
                  text="", domain_dist={}, size=1.1)
    out, _ = rebalance([fa, fb], dag, cfg)
    flat = [nid for o in out for nid in o.node_ids]
    assert sorted(flat) == ["a", "b", "c"]
