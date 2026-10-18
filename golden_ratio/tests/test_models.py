from golden_ratio.models import DAG, Node


def make_nodes():
    return [
        Node(id="n1", text="收集数据", domain_dist={"分析": 0.6}, trades=["调研"],
             complexity="low", color_weight=0.4, deliverable="text"),
        Node(id="n2", text="撰写报告", domain_dist={"写作": 0.8}, trades=["创作"],
             complexity="mid", color_weight=0.8, deliverable="text"),
    ]

def test_max_depth_simple_chain():
    dag = DAG(nodes=make_nodes(), edges=[("n1", "n2")])
    assert DAG.max_depth(dag) == 2

def test_avg_branching():
    dag = DAG(nodes=make_nodes(), edges=[("n1", "n2")])
    assert abs(DAG.avg_branching(dag) - 0.5) < 1e-9

def test_is_acyclic_detects_cycle():
    dag = DAG(nodes=make_nodes(), edges=[("n1", "n2"), ("n2", "n1")])
    assert not DAG.is_acyclic(dag)

def test_topological_order_chain():
    from golden_ratio.models import Node
    nodes = [Node(id="n1", text="a", domain_dist={}, trades=[], complexity="low",
                  color_weight=0.5, deliverable="text"),
             Node(id="n2", text="b", domain_dist={}, trades=[], complexity="low",
                  color_weight=0.5, deliverable="text"),
             Node(id="n3", text="c", domain_dist={}, trades=[], complexity="low",
                  color_weight=0.5, deliverable="text")]
    dag = DAG(nodes=nodes, edges=[("n1", "n2"), ("n2", "n3")])
    assert DAG.topological_order(dag) == ["n1", "n2", "n3"]


def test_topological_order_with_branch():
    from golden_ratio.models import Node
    nodes = [Node(id="n1", text="a", domain_dist={}, trades=[], complexity="low",
                  color_weight=0.5, deliverable="text"),
             Node(id="n2", text="b", domain_dist={}, trades=[], complexity="low",
                  color_weight=0.5, deliverable="text"),
             Node(id="n3", text="c", domain_dist={}, trades=[], complexity="low",
                  color_weight=0.5, deliverable="text")]
    dag = DAG(nodes=nodes, edges=[("n1", "n2"), ("n1", "n3")])
    order = DAG.topological_order(dag)
    assert order[0] == "n1" and set(order[1:]) == {"n2", "n3"}
