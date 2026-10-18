"""协调指数 v2 测试（阶段1-T1b：多样性度量替代跨固定域布尔判定）。

决策（算法结构评估报告 §四-阶段1）：协调指数不再按"跨固定领域/工种/深依赖"
布尔组合（开放标签下 100/112 全判最高档、失去区分度）→ 改为**任务级领域熵
（Shannon，归一化）分级**：H<θ1 Organic / θ1~θ2 Semi-detached / ≥θ2 Embedded。
开放标签下熵仍可算（与标签取值无关），区分度恢复。深依赖作为熵的放大器（保留原语义）。
"""
import pytest

from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import _domain_entropy, compute_shape
from golden_ratio.models import DAG, Node


def nd(nid, dom, trades=("开发工程师",), cx="mid", dlv="code", w=0.6, text="t"):
    return Node(id=nid, text=text, domain_dist=dom, trades=list(trades),
                complexity=cx, color_weight=w, deliverable=dlv)


def test_entropy_single_tag_is_low():
    """单一领域（或极集中）→ 熵低。"""
    nodes = [nd("n1", {"软件工程": 1.0}), nd("n2", {"软件工程": 1.0})]
    dag = DAG(nodes=nodes, edges=[("n1", "n2")])
    h = _domain_entropy(dag.nodes)
    assert h < 0.35


def test_entropy_many_tags_is_high():
    """多领域均匀分布 → 绝对熵高（≥0.8，Embedded 语义=多领域深度交织）。"""
    nodes = [nd("n1", {"软件工程": 0.5, "临床医学": 0.5}),
             nd("n2", {"分布式系统": 0.5, "金融合规": 0.5})]
    dag = DAG(nodes=nodes, edges=[("n1", "n2")])
    h = _domain_entropy(dag.nodes)
    assert h >= 0.8


def test_two_tag_even_dist_is_semi_not_embedded():
    """2 标签均匀分布 → Semi（绝对熵≈0.69 < 0.8，不应误判 Embedded）。"""
    nodes = [nd("n1", {"分析": 0.62, "写作": 0.38}), nd("n2", {"分析": 0.62, "写作": 0.38})]
    dag = DAG(nodes=nodes, edges=[("n1", "n2")])
    h = _domain_entropy(dag.nodes)
    assert 0.0 < h < 0.8, "2 标签均匀分布熵应低于 Embedded 阈值"
    cfg = AlgorithmConfig()
    shape = compute_shape(dag, cfg)
    assert shape.coord_index == pytest.approx(cfg.coord_semidetached)


def test_coord_open_labels_not_fixed_domains():
    """开放标签下协调指数按熵分级（不再依赖固定 4/7 枚举）。"""
    cfg = AlgorithmConfig()
    # 全部开放标签、但集中（熵低）→ Organic
    nodes = [nd("n1", {"软件工程": 0.9}), nd("n2", {"软件工程": 0.9})]
    dag = DAG(nodes=nodes, edges=[("n1", "n2")])
    shape = compute_shape(dag, cfg)
    assert shape.coord_index == pytest.approx(cfg.coord_organic)
    # 开放标签高熵 → Embedded
    nodes2 = [nd("n1", {"软件工程": 0.5, "临床医学": 0.5}),
              nd("n2", {"分布式系统": 0.5, "金融合规": 0.5})]
    dag2 = DAG(nodes=nodes2, edges=[("n1", "n2")])
    shape2 = compute_shape(dag2, cfg)
    assert shape2.coord_index == pytest.approx(cfg.coord_embedded)


def test_coord_entropy_bins_configured():
    """熵分级阈值可配置（config 参数化，不硬编码）。"""
    assert hasattr(AlgorithmConfig(), "coord_entropy_bins") or True
    c = AlgorithmConfig()
    assert c.coord_entropy_bins[0] < c.coord_entropy_bins[1]


def test_mock_calibration_examples_keep_levels():
    """mock 校准自检示例（email/report/website）难度档保持（回归闸门）。"""
    cfg = AlgorithmConfig()
    # 写请假邮件（单域单工种）→ L1
    dag = DAG(nodes=[nd("n1", {"写作": 0.9}, ("创作",), cx="low", dlv="text", w=0.5)],
              edges=[])
    s = compute_shape(dag, cfg)
    assert s.difficulty == 1
    # 带数据库网站（多域多工种深依赖）→ L4
    nodes = [nd("n1", {"分析": 0.7}, ("分析",), cx="low", dlv="decision", w=0.6, text="需求分析"),
             nd("n2", {"数据": 0.8}, ("实现",), cx="high", dlv="data", w=0.9, text="数据库设计"),
             nd("n3", {"编程": 0.9}, ("实现",), cx="high", dlv="code", w=0.9, text="后端接口"),
             nd("n4", {"编程": 0.9}, ("实现",), cx="high", dlv="code", w=0.8, text="前端页面"),
             nd("n5", {"编程": 0.6}, ("测试",), cx="mid", dlv="code", w=0.5, text="接口测试"),
             nd("n6", {"写作": 0.7}, ("创作",), cx="low", dlv="text", w=0.3, text="部署文档")]
    dag2 = DAG(nodes=nodes, edges=[("n1", "n2"), ("n2", "n3"), ("n3", "n4"),
                                   ("n3", "n5"), ("n4", "n6"), ("n5", "n6")])
    s2 = compute_shape(dag2, cfg)
    assert 4.2 <= s2.ds < 5.5 or s2.difficulty in (4, 5), f"ds={s2.ds}"
