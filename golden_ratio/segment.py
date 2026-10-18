"""初步分割（修订稿 §3.2）：参数合成① → 软路由② → softmax share③ → 分层分割④ → 原子性合并⑤。"""
import math

from golden_ratio.effort import node_effort
from golden_ratio.models import DAG, Fragment

# B 臂微调 v5.2：工时封块浮点容差（Σ node_effort round 后的边界误判，T05 根因）
_CEILING_EPS = 1e-6


def _synthetic_bias(node, dag, shape, cfg, desc=None):
    """参数合成 v2（阶段1 开放结构度量）：b(n) = α·b_结构 + β·b_交付物 + γ·b_L。

    - b_结构：标签量（多领域/多工种节点更复杂）+ 下游影响面 + 工时占比——零先验枚举，
      真 LLM 开放标签下可算（旧 bias_domain/bias_trade 已废弃，0% 命中）。
    - b_交付物：通用概念（真 LLM 100% 命中）→ 查表保留。
    - b_L：难度档（结构无关 → 保留）。
    """
    b_struct = _structural_bias(node, dag, shape, cfg, desc)
    b_dlv = cfg.bias_deliverable.get(node.deliverable, 0.0)
    b_l = cfg.bias_level.get(shape.difficulty, 0.0)
    return cfg.alpha * b_struct + cfg.beta * b_dlv + cfg.gamma * b_l


def _descendant_counts(dag):
    """后代数预计算（拓扑逆序 DP，O(N+E)）——避免 _structural_bias 每节点 BFS 的 O(N²)。"""
    order = DAG.topological_order(dag)
    desc = {nid: 0 for nid in order}
    for nid in reversed(order):
        cnt = 0
        for s in DAG.successors(dag, nid):
            cnt += 1 + desc.get(s, 0)
        desc[nid] = cnt
    return desc


def _structural_bias(node, dag, shape, cfg, desc=None):
    """结构特征偏置（开放度量，值域[0,1]）：
    ① 标签量：节点领域+工种标签数（多标签节点语义更杂，重要度更高）
    ② 下游影响面：后代节点数占比（影响面大的节点更关键）
    ③ 工时占比：节点工时/任务总工时（工作量即重要度）
    """
    if desc is None:
        desc = _descendant_counts(dag)
    tag = min(1.0, (len(node.domain_dist) + len(node.trades)) / cfg.struct_tag_norm)
    fanout = desc.get(node.id, 0) / max(len(dag.nodes) - 1, 1)
    from golden_ratio.effort import node_effort
    total = getattr(shape, "total_effort", 0.0) or 1.0
    share = node_effort(node, shape, cfg) / total
    return round(cfg.struct_scale * (cfg.struct_tag_weight * tag
                 + cfg.struct_fanout_weight * fanout
                 + cfg.struct_effort_weight * share), 4)


def _softmax_share(nodes, shape, cfg, dag=None):
    if dag is None:
        # 兼容旧调用（测试直接传节点列表）：以单节点集为 DAG 退化（无下游），结构项=标签+工时
        dag = DAG(nodes=list(nodes), edges=[])
    desc = _descendant_counts(dag)
    scores = [cfg.gamma_softmax * n.color_weight
              + _synthetic_bias(n, dag, shape, cfg, desc) for n in nodes]
    exps = [math.exp(s) for s in scores]
    total = sum(exps)
    return [e / total for e in exps]


def segment(dag, shape, llm, cfg=None, hierarchical=None, task_text=""):
    if cfg is None:
        from golden_ratio.config import AlgorithmConfig
        cfg = AlgorithmConfig()
    if hierarchical is None:
        hierarchical = cfg.hierarchical_enabled and not shape.fast_path  # 快路径 = 不分层（§7）

    # 分层分割：L≥3 先按拓扑序连续段粗切，再细切。
    # 硬伤修复（T15，阶段3 放开测试）：领域 argmax 硬分组会打乱拓扑连续性 →
    # 组间边双向交错 → 收缩图有环（mock 时代被“领域单一”掩盖）。连续段切分
    # 保证无环（拓扑序单调），领域一致性退化为块内软偏好（_merge_group 同组检查）。
    if getattr(cfg, "llm_merge_enabled", False):
        # LLM 分组即权威（可跨领域组——暗伤修复：此前组内过滤丢节点 KeyError）
        groups = [list(dag.nodes)]
    elif hierarchical:
        groups = _topo_contiguous_groups(dag)
    else:
        groups = [list(dag.nodes)]

    # 细切：share 占比 + 确定性合并规则 v2（同组 + 动态窗口 + 骤降 + 工时 8/80）
    frags, idx = [], 1
    for g in groups:
        shares = _softmax_share(g, shape, cfg, dag)
        id2share = dict(zip([n.id for n in g], shares))
        id2node = {n.id: n for n in g}
        ids_topo = [nid for nid in DAG.topological_order(dag) if nid in id2share]
        metas = [{"id": nid,
                  "domain": max(id2node[nid].domain_dist, key=id2node[nid].domain_dist.get),
                  "deliverable": id2node[nid].deliverable,
                  "share": id2share[nid],
                  "effort": node_effort(id2node[nid], shape, cfg)}
                 for nid in ids_topo]
        cfg._total_effort = shape.total_effort
        if getattr(cfg, "llm_merge_enabled", False) and llm is not None:
            blocks = _validate_groups(llm.merge_nodes(metas), dag)
        else:
            blocks = _merge_group(metas, cfg, level=shape.difficulty)
        for block in blocks:
            block_nodes = [n for n in g if n.id in block]
            # 聚合领域分布（软路由前提：Σ=1，保留分布形状而非 argmax 单值）
            agg = {}
            for n in block_nodes:
                for d, pv in n.domain_dist.items():
                    agg[d] = agg.get(d, 0.0) + pv
            s_agg = sum(agg.values()) or 1.0
            agg = {d: round(pv / s_agg, 4) for d, pv in agg.items()}
            frags.append(Fragment(
                fragment_id=f"F-{idx:04d}", stage="segment",
                node_ids=block,
                text=" ".join(n.text for n in block_nodes),
                domain_dist=agg,
                size=round(sum(id2share[i] for i in block) * shape.total_size, 3),
                task_ref=task_text,
                difficulty=shape.difficulty,
                total_effort=shape.total_effort,
                deliverables=sorted({n.deliverable for n in block_nodes}),
            ))
            idx += 1

    # 依赖元数据（Q4 循迹）
    node2frag = {nid: f.fragment_id for f in frags for nid in f.node_ids}
    for f in frags:
        f.upstream = sorted({node2frag[a] for a, b in dag.edges
                             if b in f.node_ids and a in node2frag and node2frag[a] != f.fragment_id})
        f.downstream = sorted({node2frag[b] for a, b in dag.edges
                               if a in f.node_ids and b in node2frag and node2frag[b] != f.fragment_id})
    return frags

def _topo_contiguous_groups(dag):
    """拓扑序连续段：领域变化点处切分（领域为软偏好；保证收缩无环）。

    各节点必须有 id——若节点无 id 属性（异常输入）回退单组。
    """
    order = DAG.topological_order(dag)
    id2node = {n.id: n for n in dag.nodes}
    groups, cur = [], []
    last_dom = None
    for nid in order:
        node = id2node.get(nid)
        if node is None:
            continue
        dom = max(node.domain_dist, key=node.domain_dist.get)
        if cur and dom != last_dom:
            groups.append(cur)
            cur = []
        cur.append(node)
        last_dom = dom
    if cur:
        groups.append(cur)
    return groups or [list(dag.nodes)]


def _validate_groups(groups, dag):
    """LLM 合并分组校验：覆盖全部节点、无重复、组无自重复、收缩依赖图无环（§3.3 不变式）。"""
    from types import SimpleNamespace
    node_ids = [n.id for n in dag.nodes]
    flat = [x for grp in groups for x in grp]
    if sorted(flat) != sorted(set(node_ids)):
        raise ValueError(f"LLM 合并分组不完整或有多余节点: {sorted(flat)} vs {sorted(node_ids)}")
    for grp in groups:
        if len(grp) != len(set(grp)):
            raise ValueError(f"LLM 分组内元素重复: {grp}")
    if not groups:
        raise ValueError("LLM 合并分组为空")
    # 收缩图：组为节点，组间依赖为边
    gid = {nid: i for i, grp in enumerate(groups) for nid in grp}
    edges = {(gid[a], gid[b]) for a, b in dag.edges if gid[a] != gid[b]}
    sub = DAG(nodes=[SimpleNamespace(id=i) for i in range(len(groups))],
              edges=sorted(edges))
    if not DAG.is_acyclic(sub):
        raise ValueError("LLM 合并分组引入环（收缩图非无环）")
    return groups


def _merge_group(metas, cfg=None, level=1):
    """合并规则 v2（WBS 调研落地）：
    ① 同组（领域 argmax + 交付物）才可合并（deliverable-oriented + 互斥）
    ② 动态窗口：按难度档规则表（7×7 参考）
    ③ share 骤降封块（保留 v1）
    ④ 工时封块：累计 ≥80×0.8 且加节点超上限，或累计已达上限（8/80 规则）
    """
    if cfg is None:
        from golden_ratio.config import AlgorithmConfig
        cfg = AlgorithmConfig()
    window = cfg.merge_window_by_level.get(level, 3)
    from golden_ratio.effort import effort_bounds
    ceiling = min(effort_bounds(cfg, getattr(cfg, "_total_effort", 200.0))[1] * cfg.effort_ceiling,
                  cfg.effort_interval[1])   # v5.2 软目标钳制：不突破 8/80 绝对上限 80
    blocks, cur = [], []
    head_share, cur_effort = None, 0.0
    for m in metas:
        _, dom, dlv, share, effort = (m["id"], m["domain"], m["deliverable"],
                                      m["share"], m["effort"])
        group_changed = cur and (dom != cur[-1]["domain"] or dlv != cur[-1]["deliverable"])
        if getattr(cfg, "merge_cross_group", False):
            group_changed = False      # 方案A：跨组不再强制分块（同组自然合并优先性保留于顺序）
        window_hit = len(cur) >= window
        drop = head_share is not None and share < cfg.merge_drop_ratio * head_share
        effort_hit = (cur and cur_effort >= cfg.effort_interval[0]
                      and cur_effort + effort > ceiling + _CEILING_EPS)
        if cur and (group_changed or window_hit or drop or effort_hit):
            blocks.append([c["id"] for c in cur])
            cur, head_share, cur_effort = [], None, 0.0
        cur.append(m)
        if head_share is None:
            head_share = share
        cur_effort += effort
    if cur:
        blocks.append([c["id"] for c in cur])
    return blocks
