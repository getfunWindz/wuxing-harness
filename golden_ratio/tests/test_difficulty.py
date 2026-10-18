from golden_ratio.difficulty import compute_shape
from golden_ratio.models import DAG, Node


def node(nid, text, dom, trades, cx, cw, dlv):
    return Node(id=nid, text=text, domain_dist=dom, trades=trades,
                complexity=cx, color_weight=cw, deliverable=dlv)


def test_email_task_is_L1():
    dag = DAG(nodes=[node("n1", "写请假邮件", {"写作": 0.9}, ["创作"], "low", 0.5, "text")],
              edges=[])
    s = compute_shape(dag, None)
    assert s.difficulty == 1
    assert 1.0 < s.ds < 2.0


def test_quarterly_report_is_L2():
    dag = DAG(nodes=[
        node("n1", "收集业务数据", {"分析": 0.6}, ["调研"], "mid", 0.5, "text"),
        node("n2", "分析数据", {"分析": 0.7}, ["分析"], "mid", 0.7, "text"),
        node("n3", "撰写季度报告", {"写作": 0.8}, ["创作"], "mid", 0.8, "text"),
    ], edges=[("n1", "n2"), ("n2", "n3")])
    s = compute_shape(dag, None)
    assert s.difficulty == 2
    assert 2.0 <= s.ds < 3.1


def test_website_dev_is_L4():
    dag = DAG(nodes=[
        node("n1", "需求分析", {"分析": 0.7}, ["分析"], "low", 0.6, "decision"),
        node("n2", "数据库设计", {"数据": 0.8}, ["实现"], "high", 0.9, "data"),
        node("n3", "后端接口开发", {"编程": 0.9}, ["实现"], "high", 0.9, "code"),
        node("n4", "前端页面开发", {"编程": 0.9}, ["实现"], "high", 0.8, "code"),
        node("n5", "接口测试", {"编程": 0.6}, ["测试"], "mid", 0.5, "code"),
        node("n6", "部署文档", {"写作": 0.7}, ["创作"], "low", 0.3, "text"),
    ], edges=[("n1", "n2"), ("n2", "n3"), ("n3", "n4"), ("n3", "n5"), ("n4", "n6"), ("n5", "n6")])
    s = compute_shape(dag, None)
    assert s.difficulty == 4
    assert 4.4 <= s.ds < 5.1


def test_difficulty_bounds_never_outside_1_5():
    dag = DAG(nodes=[node("n1", "x", {"写作": 1.0}, ["创作"], "low", 0.5, "text")], edges=[])
    s = compute_shape(dag, None)
    assert 1 <= s.difficulty <= 5


def test_decision_deliverable_uses_decision_weight():
    # 单节点 high 决策：IFPUG decision 权重 high=6 → ln7×1.02×1.05≈2.08 → L2
    dag = DAG(nodes=[node("n1", "产品选型", {"分析": 0.9}, ["分析"], "high", 0.8, "decision")], edges=[])
    s = compute_shape(dag, None)
    assert s.difficulty == 2          # 单节点决策 ds≈2.08：mock bins (2.0,3.1) 下 L2（原注释已注明）
    assert s.ds < 3.1
