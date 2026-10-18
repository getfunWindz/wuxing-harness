"""C 臂分桶 v2 测试（阶段1-T1c：结构 key 替代开放主领域）。

决策（算法结构评估报告 §四-阶段1）：桶 key=（主领域×难度）在开放标签下桶爆炸
（每桶样本 0~2，学习失效）→ 改为**结构 key**=（难度档 × 规模层 × 熵层）：
- 规模层：total_effort 分档（bucket_size_bands）
- 熵层：领域熵分档（bucket_entropy_bands）
与标签取值无关（开放标签可算），桶数有界（5×4×3=60 理论上限），
且语义不变（相近复杂度/规模的同域多样性任务共桶）。
"""
import json

from golden_ratio.calibrate import build_dag
from golden_ratio.config import AlgorithmConfig
from golden_ratio.difficulty import compute_shape
from golden_ratio.experiment import BucketAdaptiveRunner


def _shape_of(dag, cfg):
    return compute_shape(dag, cfg)


def test_bucket_key_stable_for_same_shape():
    """同任务两次求 key 一致（确定性）。"""
    with open('golden_ratio/data/real_shape_outputs.json', encoding='utf-8') as f:
        outs = json.load(f)
    rec = next(r for r in outs['tasks'].values() if r.get('ok'))
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    dag = build_dag(rec['dag_spec'])
    shape = _shape_of(dag, cfg)
    assert runner.bucket_for(shape) == runner.bucket_for(shape)


def test_bucket_key_uses_structure_not_tag():
    """key 与开放标签无关：不同主领域但同结构 → 同桶（有界）；熵层变化 → 异桶。"""
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    # 构造两个任务：结构相同（同难度/规模/熵）但主领域标签不同
    from golden_ratio.models import DAG, Node
    def dag_with(main_tag, extra):
        return DAG(nodes=[Node(id="n1", text="a", domain_dist={main_tag: 0.6, extra: 0.4},
                               trades=["t1"], complexity="mid", color_weight=0.6,
                               deliverable="code"),
                          Node(id="n2", text="b", domain_dist={main_tag: 0.6, extra: 0.4},
                               trades=["t2"], complexity="mid", color_weight=0.5,
                               deliverable="code")],
                   edges=[("n1", "n2")])
    d1 = dag_with("软件工程", "数据工程")
    d2 = dag_with("临床医学", "金融合规")
    s1, s2 = _shape_of(d1, cfg), _shape_of(d2, cfg)
    assert max(_s_max := s1.domain_dist, key=s1.domain_dist.get) != \
           max(s2.domain_dist, key=s2.domain_dist.get), "构造前提：主领域标签不同"
    assert runner.bucket_for(s1) == runner.bucket_for(s2), "结构 key 应忽略标签取值"


def test_bucket_count_bounded_on_real_data():
    """真实 112 任务：结构 key 桶数有界（≤5×4×3）且远小于标签 key。"""
    with open('golden_ratio/data/real_shape_outputs.json', encoding='utf-8') as f:
        outs = json.load(f)
    cfg = AlgorithmConfig()
    runner = BucketAdaptiveRunner(cfg)
    keys = {}
    old_keys = set()
    for rec in outs['tasks'].values():
        if not rec.get('ok'):
            continue
        dag = build_dag(rec['dag_spec'])
        shape = _shape_of(dag, cfg)
        keys[runner.bucket_for(shape)] = keys.get(runner.bucket_for(shape), 0) + 1
        dom = max(shape.domain_dist, key=shape.domain_dist.get)
        old_keys.add((dom, shape.difficulty))
    max_theory = 5 * (len(cfg.bucket_size_bands) + 1) * (len(cfg.bucket_entropy_bands) + 1)
    assert len(keys) <= max_theory, f"结构桶数 {len(keys)} 超理论上限 {max_theory}"
    print(f"结构桶数={len(keys)}（理论上限 {max_theory}） vs 标签桶数={len(old_keys)}")
    assert len(keys) < len(old_keys), "结构 key 桶数应显著少于开放标签 key"


def test_bucket_bands_configured():
    """分档参数可配置、有序。"""
    cfg = AlgorithmConfig()
    assert cfg.bucket_size_bands == tuple(sorted(cfg.bucket_size_bands))
    assert cfg.bucket_entropy_bands == tuple(sorted(cfg.bucket_entropy_bands))
