from golden_ratio.llm import MockLLM
from golden_ratio.segment import segment
from golden_ratio.shape import shape_task


def test_segment_email_yields_one_fragment():
    dag, shape = shape_task("写一封请假邮件", MockLLM())
    frags = segment(dag, shape, MockLLM())
    assert len(frags) == 1
    assert frags[0].fragment_id.startswith("F-")
    assert frags[0].stage == "segment"


def test_segment_website_hierarchical_splits_by_domain():
    dag, shape = shape_task("开发一个带用户系统的网站", MockLLM())
    frags = segment(dag, shape, MockLLM(), hierarchical=True)
    assert len(frags) >= 2
    for f in frags:
        doms = [max(n.domain_dist, key=n.domain_dist.get)
                for n in dag.nodes if n.id in f.node_ids]
        assert len(set(doms)) == 1, f"碎片 {f.fragment_id} 混领域"


def test_segment_report_fast_path_no_hierarchy():
    dag, shape = shape_task("写一份季度报告", MockLLM())
    frags = segment(dag, shape, MockLLM(), hierarchical=False)
    assert len(frags) >= 1


def test_segment_fragment_metadata_traceable():
    dag, shape = shape_task("写一份季度报告", MockLLM())
    frags = segment(dag, shape, MockLLM())
    f = frags[0]
    assert f.stage == "segment"
    assert all(nid in {n.id for n in dag.nodes} for nid in f.node_ids)


def test_segment_respects_dependencies():
    dag, shape = shape_task("开发一个带用户系统的网站", MockLLM())
    frags = segment(dag, shape, MockLLM(), hierarchical=True)
    all_ids = {n.id for n in dag.nodes}
    flat = [nid for f in frags for nid in f.node_ids]
    assert sorted(flat) == sorted(all_ids)
    assert len(flat) == len(set(flat))

def _meta(nid, dom, dlv, share, effort):
    return {"id": nid, "domain": dom, "deliverable": dlv,
            "share": share, "effort": effort}


def _cfg_crossoff():
    from golden_ratio.config import AlgorithmConfig
    c = AlgorithmConfig()
    c.merge_cross_group = False     # 显式关闭（默认已为 True，C 方案定案）
    return c


def test_merge_group_window_by_level():
    # 窗口按难度档规则表：L2 → 3 节点封块
    from golden_ratio.segment import _merge_group
    metas = [_meta(f"n{i}", "编程", "code", 1.0, 10.0) for i in range(1, 6)]
    blocks = _merge_group(metas, cfg=None, level=2)
    assert len(blocks) == 2                     # 窗口 3 → [n1n2n3],[n4n5]
    assert blocks[0] == ["n1", "n2", "n3"]


def test_merge_group_splits_on_share_drop():
    from golden_ratio.segment import _merge_group
    metas = [_meta("n1", "编程", "code", 1.0, 10.0),
             _meta("n2", "编程", "code", 0.9, 10.0),
             _meta("n3", "编程", "code", 0.5, 10.0)]
    blocks = _merge_group(metas, cfg=None, level=2)
    assert len(blocks) == 2                     # 0.5/1.0 < 0.7 骤降封块
    assert blocks[1] == ["n3"]


def test_merge_group_separates_different_deliverables():
    # 同领域不同交付物：不合并（WBS deliverable-oriented）
    from golden_ratio.segment import _merge_group
    metas = [_meta("n1", "分析", "text", 1.0, 10.0),
             _meta("n2", "分析", "decision", 1.0, 10.0)]
    blocks = _merge_group(metas, cfg=_cfg_crossoff(), level=2)
    assert blocks == [["n1"], ["n2"]]


def test_merge_group_separates_different_domains():
    from golden_ratio.segment import _merge_group
    metas = [_meta("n1", "分析", "text", 1.0, 10.0),
             _meta("n2", "写作", "text", 1.0, 10.0)]
    blocks = _merge_group(metas, cfg=_cfg_crossoff(), level=2)
    assert blocks == [["n1"], ["n2"]]


def test_merge_group_effort_ceiling_blocks():
    # 工时累计 ≥64 且加入下一节点超 80 → 封块（8/80 规则）
    from golden_ratio.segment import _merge_group
    metas = [_meta("n1", "编程", "code", 1.0, 50.0),
             _meta("n2", "编程", "code", 1.0, 30.0),
             _meta("n3", "编程", "code", 1.0, 40.0)]
    blocks = _merge_group(metas, cfg=None, level=4)   # L4 窗口 5，不触发窗口
    assert len(blocks) == 2                     # 50+30=80 ≤80 合并；+40 超限 → 封
    assert blocks[1] == ["n3"]


def test_merge_group_effort_within_interval_merges():
    # 总工时 ≤ 80 且窗口内 → 不封块
    from golden_ratio.segment import _merge_group
    metas = [_meta("n1", "编程", "code", 1.0, 20.0),
             _meta("n2", "编程", "code", 1.0, 20.0),
             _meta("n3", "编程", "code", 1.0, 20.0)]
    blocks = _merge_group(metas, cfg=None, level=4)
    assert blocks == [["n1", "n2", "n3"]]       # 60 ≤ 80，窗口 5 内


def test_merge_group_window_level3_is_five():
    # 用户决策：窗口规则表 2/3/5/7（L3 → 5）
    from golden_ratio.segment import _merge_group
    metas = [_meta(f"n{i}", "编程", "code", 1.0, 5.0) for i in range(1, 7)]
    blocks = _merge_group(metas, cfg=None, level=3)
    assert len(blocks) == 2                     # 窗口 5 → [n1..n5],[n6]
    assert len(blocks[0]) == 5
