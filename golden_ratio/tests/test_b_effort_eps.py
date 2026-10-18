"""B 臂微调（v5.2）：effort_hit 浮点边界容差。

根因（T05 诊断）：整块工时 = Σ node_effort（round 2 位）在浮点下可能比
ceiling（= T 本身）大 1e-15 量级 → 严格大于判定误封块 → 小任务整块边界过碎
（T05 3 节点 24.15h 被切成 2 块；T11~T13 同类）。容差 1e-6 不改变真实超限行为。
"""
from golden_ratio.config import AlgorithmConfig
from golden_ratio.llm import MockLLM
from golden_ratio.segment import segment
from golden_ratio.shape import shape_task


def _cfg():
    cfg = AlgorithmConfig()          # merge_cross_group=True（C 方案定案）
    cfg.m_level_cap = 40.0           # T40 健康口径
    return cfg


def _meta(nid, dom, dlv, share, effort):
    return {"id": nid, "domain": dom, "deliverable": dlv, "share": share, "effort": effort}


def test_t05_whole_task_fits_ceiling_single_block():
    """浮点边界：整块工时=ceiling 时不应因 1e-15 误差切块（构造式稳定复现）。"""
    from golden_ratio.segment import _merge_group
    cfg = _cfg()
    cfg._total_effort = 46.0                    # → hi=min(80,46,40)=40?? 用 cap 40 的话 ceiling=40×1.15=46
    metas = [_meta("n1", "编程", "code", 0.4, 16.0),
             _meta("n2", "编程", "code", 0.3, 15.0),
             _meta("n3", "编程", "code", 0.3, 15.0)]
    # 16+15+15=46 == ceiling（40×1.15）→ 精确边界，不应封块
    blocks = _merge_group(metas, cfg, level=4)
    assert len(blocks) == 1, "整块工时=ceiling 时不应因浮点误封块"


def test_real_over_limit_still_blocks():
    """真实超限（两节点 56h > 40）仍应封块（容差不改变行为）。"""
    llm = MockLLM()
    cfg = _cfg()
    dag, shape = shape_task("开发一个带用户系统的网站", llm)
    frags = segment(dag, shape, llm, cfg)
    # 网站模板 L4：n3+n4 = 56.8h > 40 → 必须分块（≥2）
    assert len(frags) >= 2
