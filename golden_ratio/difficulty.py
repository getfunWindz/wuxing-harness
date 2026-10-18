"""难度客观计算（修订稿 §3.1.1）：IFPUG 权重① → 结构分② → 协调指数③ → ds④ → 分档⑤。"""
import math

from golden_ratio.models import DAG, Shape


def _weight_pts(node, cfg):
    table = {"text": cfg.weight_text, "code": cfg.weight_code,
             "data": cfg.weight_data, "decision": cfg.weight_decision}
    return table.get(node.deliverable, cfg.weight_text)[node.complexity]


def compute_shape(dag, cfg=None):
    if cfg is None:
        from golden_ratio.config import AlgorithmConfig
        cfg = AlgorithmConfig()

    # ① 节点复杂度分（IFPUG）
    pts = 0.0
    for n in dag.nodes:
        n.weight_pts = _weight_pts(n, cfg)
        pts += n.weight_pts

    # ② 结构分
    struct = cfg.struct_depth_weight * DAG.max_depth(dag) + \
             cfg.struct_branch_weight * DAG.avg_branching(dag)

    # ③ 协调指数 v2（阶段1-T1b：领域熵分级 + 深依赖放大——开放标签下可算、恢复区分度）
    trades = {t for n in dag.nodes for t in n.trades}
    h = _domain_entropy(dag.nodes)
    deep = DAG.max_depth(dag) >= cfg.deep_dependency_threshold
    lo_bin, hi_bin = cfg.coord_entropy_bins
    if h >= hi_bin or (h >= lo_bin and deep):
        coord = cfg.coord_embedded
    elif h >= lo_bin or deep:
        coord = cfg.coord_semidetached
    else:
        coord = cfg.coord_organic

    # ④ 难度分（优化方向1 定案：+规模项恢复动态范围——真实粒度下 ln 压缩导致
    #    75% 任务 ds 挤在 [4.7,5.5]，加 0.3·ln(1+节点数) 后 L1/L2 区分恢复（34.8% 无塌缩））
    ds = math.log(pts + 1.0) * (1.0 + struct / cfg.struct_denom) * coord \
        + cfg.ds_scale_nodes * math.log(1.0 + len(dag.nodes))

    # ⑤ 分档
    bins = cfg.ds_bins
    if ds < bins[0]:
        level = 1
    elif ds < bins[1]:
        level = 2
    elif ds < bins[2]:
        level = 3
    elif ds < bins[3]:
        level = 4
    else:
        level = 5

    # 任务总工时（8/80 缩放依据；effort 规则表，双通道主通道在真 LLM 阶段替换）
    from golden_ratio.effort import node_effort
    total_effort = sum(node_effort(n, None, cfg, level) for n in dag.nodes)

    return Shape(
        domain_dist=_aggregate_domains(dag),
        trades=trades,
        difficulty=level,
        ds=round(ds, 3),
        struct=round(struct, 3),
        coord_index=coord,
        total_size=float(pts),
        total_effort=round(total_effort, 2),
        fast_path=level <= cfg.fast_path_max_difficulty,
        entropy=h,     # T1c：分桶 key 成分（开放标签可算）
    )


def _domain_entropy(nodes):
    """任务级领域熵（Shannon 绝对熵）：聚合各节点 domain_dist → H = -Σ p·ln(p)。

    不归一（2 标签均匀分布与 8 标签均匀分布应区分——Embedded 应表示多领域深度交织）；
    开放标签可算（与标签取值无关——阶段1-T1b 协调指数 v2 的基数）。
    """
    agg = {}
    for n in nodes:
        for d, p in n.domain_dist.items():
            agg[d] = agg.get(d, 0.0) + p
    total = sum(agg.values()) or 1.0
    probs = [p / total for p in agg.values() if p > 0]
    if len(probs) <= 1:
        return 0.0
    return round(-sum(p * math.log(p) for p in probs), 4)


def _aggregate_domains(dag):
    """聚合为归一化概率分布（软路由要求 Σ=1）：按置信度加权，未标注的置信度视为归属其他。"""
    total = {}
    for n in dag.nodes:
        for d, p in n.domain_dist.items():
            total[d] = total.get(d, 0.0) + p
    s = sum(total.values())
    if s == 0:
        return {}
    return {d: round(p / s, 3) for d, p in total.items()}
