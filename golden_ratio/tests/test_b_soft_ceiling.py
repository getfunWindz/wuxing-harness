"""B 臂微调 v5.2 第 2 枪：cap 软目标（ceiling 系数放开，钳制 8/80 绝对上限）。

背景（诊断）：M04/T4/T5/P09/P10 等大任务节点工时 19~38h，两两相加 40.6+ 全超
cap=40 → 全部单节点 → 块数=节点数 → T40 gen (公式 ∩ 每块≤40h) 不可达。
软化：ceiling = min(hi × effort_ceiling, effort_interval[1]) —— 健康口径放宽合并
（46~52h 块），同时不突破 8/80 绝对上限 80（合规保住）。
"""
from golden_ratio.config import AlgorithmConfig
from golden_ratio.segment import _merge_group


def _meta(nid, dom, dlv, share, effort):
    return {"id": nid, "domain": dom, "deliverable": dlv, "share": share, "effort": effort}


def _cfg(ceiling=1.0, cap=40.0):
    cfg = AlgorithmConfig()
    cfg.m_level_cap = cap
    cfg.effort_ceiling = ceiling
    cfg._total_effort = 100.0            # 大任务：hi=min(80, T, 40)=40
    return cfg


def test_default_ceiling_keeps_40h_limit():
    """现状（1.0）：40h 上限 → 21.6+21.6=43.2h 必须分块。"""
    metas = [_meta("n1", "编程", "code", 0.5, 21.6),
             _meta("n2", "编程", "code", 0.5, 21.6)]
    blocks = _merge_group(metas, _cfg(1.0), level=4)
    assert blocks == [["n1"], ["n2"]]


def test_soft_ceiling_merges_two_mid_nodes():
    """soft（1.15）：ceiling=min(40×1.15, 80)=46 → 43.2h 可合并。"""
    metas = [_meta("n1", "编程", "code", 0.5, 21.6),
             _meta("n2", "编程", "code", 0.5, 21.6)]
    blocks = _merge_group(metas, _cfg(1.15), level=4)
    assert blocks == [["n1", "n2"]]


def test_soft_ceiling_still_blocks_real_overrun():
    """soft 下 46h 上限仍封块：21.6×2+21.6 = 64.8 > 46 → 不合并第三个。"""
    metas = [_meta("n1", "编程", "code", 0.6, 21.6),
             _meta("n2", "编程", "code", 0.5, 21.6),
             _meta("n3", "编程", "code", 0.5, 21.6)]
    blocks = _merge_group(metas, _cfg(1.15), level=4)
    assert blocks == [["n1", "n2"], ["n3"]]


def test_soft_ceiling_clamped_to_80_safe():
    """软上限钳制：cap=80 口径下 ceiling=min(80×1.15, 80)=80，不破 8/80。"""
    cfg = _cfg(1.15, cap=80.0)
    metas = [_meta("n1", "编程", "code", 0.5, 42.0),
             _meta("n2", "编程", "code", 0.5, 42.0)]
    blocks = _merge_group(metas, cfg, level=4)
    # 42+42=84 > 80（钳制后）→ 仍分块（合规保住）
    assert blocks == [["n1"], ["n2"]]
