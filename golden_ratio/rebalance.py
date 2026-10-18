"""边界阈值膨胀（修订稿 §3.3）：黄金比再平衡——过胖迁移、过小合并、依赖完整性不变式。"""
from golden_ratio.models import DAG, Fragment


def low_importance_ratio(fragment, dag, cfg):
    """碎片内低重要度节点（w < θ）的权重占碎片总权重比例 r(F)。"""
    ws = {n.id: n.color_weight for n in dag.nodes}
    total = sum(ws[nid] for nid in fragment.node_ids)
    low = sum(ws[nid] for nid in fragment.node_ids
              if ws[nid] < cfg.low_importance_threshold)
    return low / total if total > 0 else 0.0


def _similarity(f1, f2):
    """碎片相似度：节点文本字符集合 Jaccard（简化实现，真 LLM 阶段可换语义相似度）。"""
    s1, s2 = set(f1.text), set(f2.text)
    if not s1 or not s2:
        return 0.0
    return len(s1 & s2) / len(s1 | s2)


def _apply_move(frags, move):
    """应用 LLM 迁移建议：node_ids 从 from 碎片并入 to 碎片；来源腾空则移除。"""
    fid_from, fid_to = move.get("from"), move.get("to")
    node_ids = move.get("node_ids", [])
    src = next((f for f in frags if f.fragment_id == fid_from), None)
    dst = next((f for f in frags if f.fragment_id == fid_to), None)
    if src is None or dst is None:
        raise ValueError(f"LLM move 引用不存在的碎片: {fid_from} -> {fid_to}")
    if not node_ids:
        return False
    if not set(node_ids) <= set(src.node_ids):
        raise ValueError(f"LLM move 节点不属于来源碎片: {node_ids}")
    dst.node_ids = sorted(set(dst.node_ids) | set(node_ids))
    dst.stage = "rebalance"
    src.node_ids = [n for n in src.node_ids if n not in set(node_ids)]
    if not src.node_ids:
        frags.remove(src)
    return True


def _contraction_acyclic(node2frag, edges):
    """收缩图无环检查（§3.3 不变式）：给定节点→碎片映射与原 DAG 边，
    碎片层依赖图必须无环（迁移/合并不得收紧回路——T15 硬伤修复）。"""
    from types import SimpleNamespace
    ids = sorted(set(node2frag.values()))
    sub_edges = sorted({(node2frag[a], node2frag[b]) for a, b in edges
                        if a in node2frag and b in node2frag
                        and node2frag[a] != node2frag[b]})
    sub = DAG(nodes=[SimpleNamespace(id=i) for i in ids], edges=sub_edges)
    return DAG.is_acyclic(sub)


def _merge_acyclic(src, dst, frags, dag):
    """模拟合并 src→dst 后收缩图是否仍无环（有环 → 候选被拒绝）。"""
    n2f = {nid: f.fragment_id for f in frags for nid in f.node_ids}
    for nid in src.node_ids:
        n2f[nid] = dst.fragment_id
    return _contraction_acyclic(n2f, dag.edges)


def _split_acyclic(f, keep, low, frags, dag):
    """把 f 分裂为 keep/low 两块后收缩图是否仍无环。"""
    n2f = {nid: fr.fragment_id for fr in frags for nid in fr.node_ids}
    new_id = f"{f.fragment_id}-S"
    for nid in keep:
        n2f[nid] = f.fragment_id
    for nid in low:
        n2f[nid] = new_id
    return _contraction_acyclic(n2f, dag.edges)


def rebalance(fragments, dag, cfg=None, shape=None, llm=None):
    """过小判定：shape 提供时用工时 < 8 小时（8/80 下限），否则退回碎片规模判定。

    llm 参数：llm_rebalance_enabled 且 llm 提供时，每轮先应用 rebalance_suggest 的
    moves（确定性规则仍是兜底，moves 为空则行为与关闭时完全一致）。
    """
    if cfg is None:
        from golden_ratio.config import AlgorithmConfig
        cfg = AlgorithmConfig()
    llm_mode = getattr(cfg, "llm_rebalance_enabled", False) and llm is not None
    if shape is not None:
        from golden_ratio.effort import fragment_effort
        frag_effort = lambda f: fragment_effort(f, dag.nodes, shape, cfg)
    else:
        frag_effort = None
    frags = list(fragments)
    executed_rounds = 0
    skipped_moves = []
    for _ in range(cfg.rebalance_max_rounds):
        executed_rounds += 1
        moved = False
        if llm_mode:
            info = {"fragments": [{"fragment_id": f.fragment_id, "node_ids": f.node_ids,
                                    "text": f.text, "size": f.size} for f in frags]}
            suggest = llm.rebalance_suggest(info) or {}
            for mv in suggest.get("moves", []) or []:
                try:
                    if _apply_move(frags, mv):
                        moved = True
                except ValueError:
                    # 无效/过时建议（引用已不存在的碎片）→ 跳过累加（建议层不产生硬失败）
                    skipped_moves.append(mv)
        new_frags = []
        for f in frags:
            r = low_importance_ratio(f, dag, cfg)
            if r > cfg.theta_high and len(f.node_ids) > 1:
                # 过胖：迁出低重要度节点，独立成新碎片（§3.3 步骤3）
                ws = {n.id: n.color_weight for n in dag.nodes}
                low_nodes = [nid for nid in f.node_ids
                             if ws[nid] < cfg.low_importance_threshold]
                if low_nodes:
                    keep = [nid for nid in f.node_ids if nid not in low_nodes]
                    if keep:                      # 暗伤 T13：keep 空（全低重要度）不产出空碎片
                        if not _split_acyclic(f, keep, low_nodes, frags, dag):
                            pass                  # 剥离会收紧回路 → 跳过剥离（保持原块）
                        else:
                            new_frags.append(Fragment(
                                fragment_id=f.fragment_id, stage="rebalance",
                                node_ids=keep, text=f.text, domain_dist=f.domain_dist,
                                size=round(f.size * (1 - r), 3),
                            ))
                            new_frags.append(Fragment(
                                fragment_id=f"F-{len(new_frags) + 1:04d}", stage="rebalance",
                                node_ids=low_nodes, text=f.text, domain_dist=f.domain_dist,
                                size=round(f.size * r, 3),
                            ))
                            moved = True
                            continue
                    # 全低重要度：全部迁出为一碎片（保 id，不分裂）
                    new_frags.append(Fragment(
                        fragment_id=f.fragment_id, stage="rebalance",
                        node_ids=low_nodes, text=f.text, domain_dist=f.domain_dist,
                        size=f.size,
                    ))
                    moved = True
                    continue
            if frag_effort is not None:
                from golden_ratio.effort import effort_bounds
                lo, _ = effort_bounds(cfg, getattr(shape, "total_effort", 200.0))
                is_tiny = frag_effort(f) < lo
            else:
                is_tiny = f.size < cfg.min_fragment_size
            if is_tiny and len(frags) > 1:
                # 过小：并入最相近碎片（§3.3 步骤4；硬伤 T15：逐候选无环预检，全环则保持）
                candidates = sorted([g for g in new_frags + frags
                                     if g.fragment_id != f.fragment_id],
                                    key=lambda g: -_similarity(f, g))
                target = next((g for g in candidates if _merge_acyclic(f, g, frags, dag)),
                              None)
                if target is not None:
                    target.node_ids = sorted(set(target.node_ids) | set(f.node_ids))
                    target.size = round(target.size + f.size, 3)
                    target.stage = "rebalance"
                    moved = True
                    continue
            new_frags.append(f)
        # 轮末不变式守卫（暗伤 T15 防逃逸）：同轮多次迁移的合效应模拟不查 → 最终检查，
        # 有环则回退本轮（保留上一轮无环状态并终止——宁缺毋滥）
        if moved and new_frags:
            n2f = {nid: fr.fragment_id for fr in new_frags for nid in fr.node_ids}
            if not _contraction_acyclic(n2f, dag.edges):
                break
        # 收敛判定：本轮无迁移则终止（§3.3 步骤5）
        if not moved:
            break
        frags = new_frags
    return frags, executed_rounds
