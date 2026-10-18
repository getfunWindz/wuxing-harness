"""工时规则表 v1（WBS 8/80 调研落地，2026-08 用户确认）。

effort(node) = 基准(难度档) × 工种系数 × √(weight_pts / ref_pts)
- 基准表：难度档 1~5 → 6/10/16/24/36 小时
- 工种系数：实现 1.0 / 分析 1.1 / 创作 0.9 / 测试 0.8 / 调研 0.7 / 评审 0.6 / 管理 0.8
- 规模信号：IFPUG weight_pts 注入（√ 减缓规模爆炸），缓解"规则表对规模不敏感"缺陷
- 双通道架构：本模块 = 测试基线（确定性）；真 LLM 阶段由形状化输出替代，本模块降级为校验器
"""
import math


def node_effort(node, shape, cfg, level=None):
    """单节点工时预估（规则表 v1）。shape 预留（真 LLM 阶段由形状化输出替代）。"""
    if shape is not None and getattr(shape, "per_node_effort", None):
        # 真 LLM 阶段：形状化输出附带的工时预估（双通道主通道）
        return shape.per_node_effort.get(node.id, node.weight_pts)
    lv = level if level is not None else (shape.difficulty if shape is not None else 1)
    base = cfg.effort_base_by_level.get(lv, 10.0)
    coefs = [cfg.effort_trade_coef.get(t, 1.0) for t in node.trades]
    coef = max(coefs) if coefs else 1.0
    # 自查 IFPUG 权重（不依赖 difficulty 预填，保证顺序无关）
    table = {"text": cfg.weight_text, "code": cfg.weight_code,
             "data": cfg.weight_data, "decision": cfg.weight_decision}
    pts = table.get(node.deliverable, cfg.weight_text)[node.complexity]
    scale = math.sqrt(pts / cfg.effort_ref_pts)
    return round(base * coef * scale, 2)


def effort_bounds(cfg, total_effort):
    """8/80 按任务规模缩放（用户决策：保持灵活可变；v3.1 修正过紧问题）。

    区间 = [min(8, T/4), min(80, T)]，T = 任务总工时：
    - 上限 min(80, T)：小任务允许整块存在（总工时 <80 的任务，整块即合法工作包）；
      大任务（T≥80）回到标准 80h 上限——8/80 上限约束的是工作包，不约束任务本身
    - 下限 min(8, T/4)：小任务下限同步收紧（允许更细的碎片），大任务保持 8h
    - v3.0 教训：上限用 T/2 会把"同组自然组合"（如 T05 的 19.6h 块）强行拆碎，
      与组结构冲突导致 gd 与合规率同时恶化
    """
    lo = min(cfg.effort_interval[0], max(1.0, total_effort / 4))
    hi = min(cfg.effort_interval[1], max(lo + 1.0, total_effort), cfg.m_level_cap)
    return lo, hi


def fragment_effort(fragment, dag_nodes, shape, cfg, level=None):
    """碎片工时 = Σ 节点工时（8/80 区间判定的依据）。"""
    node_map = {n.id: n for n in dag_nodes}
    return round(sum(node_effort(node_map[nid], shape, cfg, level)
                     for nid in fragment.node_ids if nid in node_map), 2)
