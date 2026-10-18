"""参数合成 v2 测试（阶段 1：知识注入层 → 开放结构度量）。

决策（算法结构评估报告 §四-阶段 1）：bias 不再查领域/工种封闭表（真 LLM 0%
命中、映射被 774 唯一标签否决）——改为**任务结构特征函数**（零先验枚举）：
  b(n) = α·b_结构(n) + β·b_交付物(dlv) + γ·b_L(难度档)
- b_结构(n) = k1·标签多样性贡献 + k2·下游影响面 + k3·工时占比
- b_交付物：交付物为通用概念（真 LLM 100% 命中）→ 查表保留
- b_L：难度档无需封闭枚举 → 保留
旧 bias_domain/bias_trade 废弃（保留字段但不再参与计算）。
"""
import pytest

from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape
from golden_ratio.models import DAG, Node
from golden_ratio.segment import _synthetic_bias


def nd(nid, text, dom, trades, cx="mid", dlv="code", w=0.6):
    return Node(id=nid, text=text, domain_dist=dom, trades=trades,
                complexity=cx, color_weight=w, deliverable=dlv)


def _dag_and_shape():
    """链式 3 节点：n1(开放标签a) → n2(a+b) → n3(b)。"""
    nodes = [nd("n1", "数据采集", {"device": 0.7, "软件工程": 0.3}, ["数据工程师"]),
             nd("n2", "模型开发", {"软件工程": 0.6, "device": 0.4}, ["数据工程师", "产品经理"]),
             nd("n3", "文档输出", {"软件工程": 0.8}, ["产品经理"], dlv="text", w=0.4)]
    dag = DAG(nodes=nodes, edges=[("n1", "n2"), ("n2", "n3")])
    shape = compute_shape(dag, AlgorithmConfig())
    return dag, shape


def test_open_labels_compute_bias_without_table():
    """开放标签（非封闭集合）→ b_结构 可计算（不依赖查表、不归零退化）。"""
    cfg = AlgorithmConfig()
    dag, shape = _dag_and_shape()
    b = _synthetic_bias(dag.nodes[0], dag, shape, cfg)
    assert b == pytest.approx(b)          # 数值可算
    assert b != 0.0, "开放标签下不再退化为 0"


def test_bias_adds_for_tag_diversity_contribution():
    """标签量越大的节点（多领域/多工种）b 越大（多样性贡献项）。"""
    cfg = AlgorithmConfig()
    dag, shape = _dag_and_shape()
    # n2：domain 2 种 + trade 2 种（4 个标签）；n3：1+1（2 个标签）
    b_n2 = _synthetic_bias(dag.nodes[1], dag, shape, cfg)
    b_n3 = _synthetic_bias(dag.nodes[2], dag, shape, cfg)
    assert b_n2 > b_n3, "标签量大的节点偏置更高"


def test_bias_increases_with_downstream_fanout():
    """下游影响面（后代数）越大 b 越大。"""
    cfg = AlgorithmConfig()
    dag, shape = _dag_and_shape()
    b_n1 = _synthetic_bias(dag.nodes[0], dag, shape, cfg)   # 后代 2
    b_n3 = _synthetic_bias(dag.nodes[2], dag, shape, cfg)   # 后代 0
    assert b_n1 > b_n3


def test_bias_deliverable_table_still_active():
    """交付物查表保留（通用概念 100% 命中）：code > text 组内比较。"""
    cfg = AlgorithmConfig()
    nodes = [nd("n1", "a", {"软件工程": 1.0}, ["开发工程师"], dlv="code", w=0.5),
             nd("n2", "b", {"软件工程": 1.0}, ["开发工程师"], dlv="text", w=0.5)]
    dag = DAG(nodes=nodes, edges=[("n1", "n2")])
    shape = compute_shape(dag, cfg)
    b_code = _synthetic_bias(nodes[0], dag, shape, cfg)
    b_text = _synthetic_bias(nodes[1], dag, shape, cfg)
    assert b_code > b_text, "code 偏置应大于 text（交付物表仍生效）"


def test_bias_level_term_preserved():
    """难度档项保持（与结构项正交，不依赖枚举）。"""
    cfg1 = AlgorithmConfig()
    cfg5 = AlgorithmConfig()
    # 构造不同难度 shape（单节点 ds 由权重决定：用 15h 与 3h 节点）
    dag1 = DAG(nodes=[nd("n1", "a", {"软件工程": 1.0}, ["开发工程师"], cx="low", dlv="text")], edges=[])
    dag5 = DAG(nodes=[nd("n1", "a", {"软件工程": 1.0}, ["开发工程师"], cx="high", dlv="data")], edges=[])
    s1 = compute_shape(dag1, cfg1)
    s5 = compute_shape(dag5, cfg5)
    b1 = _synthetic_bias(dag1.nodes[0], dag1, s1, cfg1)
    b5 = _synthetic_bias(dag5.nodes[0], dag5, s5, cfg5)
    assert cfg1.bias_level[1] == -0.4 and cfg5.bias_level[5] == 0.4
    assert b5 > b1, "难度档偏置仍参与（L5 > L1）"


def test_old_bias_tables_deprecated_not_used():
    """旧领域/工种表废弃（配置仍存在但不再被消费）。"""
    cfg = AlgorithmConfig()
    dag, shape = _dag_and_shape()
    # 改变旧表值 → b 不变（证明不消费）
    b1 = _synthetic_bias(dag.nodes[0], dag, shape, cfg)
    cfg.bias_domain["device"] = 0.9
    cfg.bias_trade["数据工程师"] = 0.9
    b2 = _synthetic_bias(dag.nodes[0], dag, shape, cfg)
    assert b1 == b2, "旧表改动不应影响 b（已废弃）"
