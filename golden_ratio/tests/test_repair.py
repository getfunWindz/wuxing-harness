"""DAG 轻量修复器测试（真 LLM 接入实测发现：模型偶发漏边致孤立节点）。

修复原则（成本优先）：孤立节点按拓扑序挂到其前面最近节点（仅向前补边，
不引入环），修复后仍须通过 validate_shape_output；修复失败才进入重试。
"""
from golden_ratio.validate import repair_dag, validate_shape_output


def _raw(nodes, edges, total=1.0):
    d = {"nodes": nodes, "edges": edges}
    return d


def _n(nid, w=0.5):
    return {"id": nid, "text": f"节点{nid}", "domain_dist": {"写作": 1.0},
            "trades": ["创作"], "complexity": "low",
            "deliverable": "text", "color_weight": w}


def test_repair_single_isolated_node():
    """n3 孤立 → 补边 (n2, n3)，DAG 恢复连通且无环。"""
    raw = _raw([_n("n1"), _n("n2"), _n("n3")], [["n1", "n2"]])
    nodes, edges, changed = repair_dag(raw)
    assert changed is True
    assert ["n2", "n3"] in edges
    ok, _, errs = validate_shape_output({"nodes": nodes, "edges": edges, "total_size": 1.0})
    assert ok, errs


def test_repair_multiple_isolated_serially():
    """多个孤立节点按拓扑序串联（n2,n3,n4 孤立 → n1→n2→n3→n4）。"""
    raw = _raw([_n("n1"), _n("n2"), _n("n3"), _n("n4")], [])
    nodes, edges, _ = repair_dag(raw)
    assert ["n1", "n2"] in edges and ["n2", "n3"] in edges and ["n3", "n4"] in edges
    ok, _, errs = validate_shape_output({"nodes": nodes, "edges": edges, "total_size": 1.0})
    assert ok, errs


def test_repair_only_forward_edges_no_cycle():
    """补边只向前（拓扑序），修复后仍无环。"""
    raw = _raw([_n("n1"), _n("n2"), _n("n3"), _n("n4"), _n("n5")],
               [["n3", "n4"], ["n4", "n5"]])     # n1/n2 孤立，n3~n5 链
    nodes, edges, _ = repair_dag(raw)
    # n1→n2→n3（向前补）→ 无环
    assert ["n2", "n3"] in edges
    ok, _, errs = validate_shape_output({"nodes": nodes, "edges": edges, "total_size": 1.0})
    assert ok, errs


def test_repair_no_change_when_connected():
    raw = _raw([_n("n1"), _n("n2")], [["n1", "n2"]])
    _, edges, changed = repair_dag(raw)
    assert changed is False
    assert edges == [["n1", "n2"]]


def test_repair_does_not_mutate_input():
    raw = _raw([_n("n1"), _n("n2"), _n("n3")], [["n1", "n2"]])
    import copy
    snap = copy.deepcopy(raw)
    repair_dag(raw)
    assert raw == snap
