"""全面回顾修复测试：Fragment 关口前置条件补强（P1-2/P1-3）。"""
import pytest

from golden_ratio.config import AlgorithmConfig
from golden_ratio.llm import MockLLM
from golden_ratio.segment import segment
from golden_ratio.shape import shape_task


def test_fragment_meta_completeness_for_gateway():
    """关口-子智能体前置条件：碎片携带任务上下文/聚合领域/难度/工时/交付物。"""
    dag, shape = shape_task("开发一个带用户系统的网站", MockLLM())
    frags = segment(dag, shape, MockLLM(), task_text="开发一个带用户系统的网站")
    f = frags[0]
    assert f.task_ref == "开发一个带用户系统的网站"
    assert f.difficulty == shape.difficulty >= 1
    assert f.total_effort == pytest.approx(shape.total_effort)
    assert len(f.deliverables) >= 1
    # 聚合领域分布：Σ=1（软路由前提），不再单值化
    assert abs(sum(f.domain_dist.values()) - 1.0) < 1e-6
    assert len(f.domain_dist) >= 1


def test_fragment_aggregated_domain_keeps_distribution():
    """块内多节点时聚合领域保留分布形状（非 argmax 单值）。"""
    from golden_ratio.difficulty import compute_shape
    from golden_ratio.models import DAG, Node
    nodes = [
        Node(id="n1", text="a", domain_dist={"分析": 0.6, "写作": 0.3}, trades=["调研"],
             complexity="mid", color_weight=0.5, deliverable="text"),
        Node(id="n2", text="b", domain_dist={"分析": 0.8}, trades=["分析"],
             complexity="mid", color_weight=0.5, deliverable="text"),
    ]
    dag = DAG(nodes=nodes, edges=[("n1", "n2")])
    shape = compute_shape(dag, None)
    frags = segment(dag, shape, MockLLM())
    assert len(frags) == 1                       # 同组（分析/text）合并
    dist = frags[0].domain_dist
    assert dist.get("分析", 0) > dist.get("写作", 0)
    assert abs(sum(dist.values()) - 1.0) < 1e-6


def test_theta_low_semantics_documented():
    """P1-1：黄金比下界保留为诊断阈值（高价值密度不处理），上界仍为决策阈值。"""
    cfg = AlgorithmConfig()
    assert cfg.theta_low < cfg.theta_high
    # rebalance 仅用上界做剥离决策（过胖），下界语义由文档/诊断承载
    import inspect

    from golden_ratio import rebalance
    src = inspect.getsource(rebalance)
    assert "theta_high" in src
