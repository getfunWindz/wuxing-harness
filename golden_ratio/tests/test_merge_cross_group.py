"""merge_cross_group 开关测试（细分粒度修复方案 A：跨组不再强制分块）。

背景（诊断）：同组规则（领域argmax×交付物互斥）阻断跨组合并 → L2 小任务
（T05/T06）T40 口径 gd=1.0、L3/L4 任务（T14/T21）两口径过碎。
开关开启后，组变更仅保留"优先合并同组"的自然倾向，不再强制分块；
窗口/骤降/工时封块仍然生效。
"""
from golden_ratio.config import AlgorithmConfig
from golden_ratio.llm import MockLLM
from golden_ratio.segment import segment
from golden_ratio.shape import shape_task


def _cross_group_cfg():
    """T06 场景：text + decision 跨交付物链（L2，T≈16h，T40 期望 1 块）。"""
    cfg = AlgorithmConfig()
    cfg.llm_merge_enabled = False
    return cfg


def test_cross_group_disabled_split_still_blocks():
    """显式关闭（False）：跨交付物仍强制分块（同组规则行为保留，开关可用）。"""
    llm = MockLLM()
    cfg = _cross_group_cfg()
    cfg.merge_cross_group = False
    dag, shape = shape_task("分析两款产品并选择一款", llm)
    frags = segment(dag, shape, llm, cfg)
    assert len(frags) == 2, "关闭时：text 与 decision 分属两块"


def test_cross_group_enabled_merges_within_budget():
    """开启后：16h 跨交付物链应合并为 1 块（≤8/80 上限，窗口内无骤降）。"""
    llm = MockLLM()
    cfg = _cross_group_cfg()
    cfg.merge_cross_group = True
    dag, shape = shape_task("分析两款产品并选择一款", llm)
    frags = segment(dag, shape, llm, cfg)
    assert len(frags) == 1, "跨组合并后应一块（T≈16h < 上限）"
    assert frags[0].fragment_id.startswith("F-")


def test_cross_group_still_respects_effort_ceiling():
    """开启后：跨组块仍受工时上限约束（两节点相加超 ceiling 时仍分块）。"""
    llm = MockLLM()
    cfg = _cross_group_cfg()
    cfg.merge_cross_group = True
    dag, shape = shape_task("开发一个带用户系统的网站", llm)
    # 该套件 L4：n3(28h)+n4(28h)=56h > ceiling(=min(80,T,40)×1.0) → 仍分块
    frags = segment(dag, shape, llm, cfg)
    assert len(frags) >= 2, "工时超限时不应因跨组合并而变一块"


def test_cross_group_metadata_still_traceable():
    """开启后碎片元数据完整（覆盖、无重复、stage=segment）。"""
    llm = MockLLM()
    cfg = _cross_group_cfg()
    cfg.merge_cross_group = True
    dag, shape = shape_task("写一份季度报告", llm)
    frags = segment(dag, shape, llm, cfg)
    flat = [nid for f in frags for nid in f.node_ids]
    assert sorted(flat) == sorted(n.id for n in dag.nodes)
    assert all(f.stage == "segment" for f in frags)
