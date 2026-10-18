"""LLM 调用点接入测试（技术债：LLMClient 3/4 方法未接入真实路径）。

契约（llm.py 更新后）：
- merge_nodes(node_infos) -> [[id,...],...]：按原子性三准则合并节点，须覆盖全部、不重复、收缩图无环
- rebalance_suggest(fragment_info) -> {"moves": [{"from","to","node_ids"}]}：迁移建议（可为空）
- score_keys(tokens) -> {word: score}：key 打分（分数替代规则退化方案）
- 默认全部关闭（不确定性规则兜底），cfg 开关开启后进入调用链。
"""
import pytest

from golden_ratio.config import AlgorithmConfig
from golden_ratio.keyify import extract_keys
from golden_ratio.llm import MockLLM
from golden_ratio.pipeline import run_pipeline
from golden_ratio.rebalance import rebalance
from golden_ratio.segment import segment
from golden_ratio.shape import shape_task


class FakeMergeLLM(MockLLM):
    def __init__(self, groups):
        super().__init__()
        self.groups = groups

    def merge_nodes(self, node_infos):
        super().merge_nodes(node_infos)
        return self.groups


class FakeMoveLLM(MockLLM):
    def __init__(self, moves):
        super().__init__()
        self.moves = moves

    def rebalance_suggest(self, fragment_info):
        super().rebalance_suggest(fragment_info)
        return {"moves": self.moves}


class FakeShapeLLM(MockLLM):
    """首次返回非法输出，第二次合法（用于重试测试）。"""

    def __init__(self, bad_first=False, always_bad=False):
        super().__init__()
        self.bad_first = bad_first
        self.always_bad = always_bad
        self.calls = 0

    def shape_task(self, task_text):
        self.calls += 1
        self._hit()
        raw = super().shape_task(task_text)
        if self.always_bad or self.bad_first and self.calls == 1:
            raw = {"nodes": [], "edges": [], "total_size": 1.0}
        return raw


def test_segment_llm_merge_disabled_by_default():
    llm = MockLLM()
    dag, shape = shape_task("写一份季度报告", llm)
    before = llm.call_count
    segment(dag, shape, llm, AlgorithmConfig())
    assert llm.call_count == before, "默认不调用 merge_nodes"


def test_segment_llm_merge_enabled_uses_llm_groups():
    llm = FakeMergeLLM(groups=[["n1", "n2", "n3"]])   # 全部并入一块
    cfg = AlgorithmConfig()
    cfg.llm_merge_enabled = True
    dag, shape = shape_task("写一份季度报告", llm)
    frags = segment(dag, shape, llm, cfg)
    assert len(frags) == 1, "LLM 合并分组应生效（mega 块）"
    assert sorted(frags[0].node_ids) == ["n1", "n2", "n3"]


def test_segment_llm_merge_rejects_incomplete_groups():
    llm = FakeMergeLLM(groups=[["n1"]])               # 丢失 n2/n3
    cfg = AlgorithmConfig()
    cfg.llm_merge_enabled = True
    dag, shape = shape_task("写一份季度报告", llm)
    with pytest.raises(ValueError):
        segment(dag, shape, llm, cfg)


def test_segment_llm_merge_rejects_duplicate_groups():
    llm = FakeMergeLLM(groups=[["n1", "n2"], ["n2", "n3"]])   # n2 重复
    cfg = AlgorithmConfig()
    cfg.llm_merge_enabled = True
    dag, shape = shape_task("写一份季度报告", llm)
    with pytest.raises(ValueError):
        segment(dag, shape, llm, cfg)


def test_rebalance_llm_suggest_disabled_by_default():
    llm = MockLLM()
    cfg = AlgorithmConfig()
    dag, shape = shape_task("写一封请假邮件", llm)
    frags = segment(dag, shape, llm, cfg)
    before = llm.call_count
    rebalance(frags, dag, cfg, shape, llm)
    assert llm.call_count == before, "默认不调用 rebalance_suggest"


def test_rebalance_llm_suggest_called_when_enabled():
    llm = MockLLM()
    cfg = AlgorithmConfig()
    cfg.llm_rebalance_enabled = True
    dag, shape = shape_task("写一封请假邮件", llm)
    frags = segment(dag, shape, llm, cfg)
    before = llm.call_count
    out, _ = rebalance(frags, dag, cfg, shape, llm)
    assert llm.call_count > before, "开启后 rebalance_suggest 被调用"
    # Mock 无 moves → 结果与确定性规则一致（无迁移）
    assert sorted(nid for f in out for nid in f.node_ids) == \
           sorted(nid for f in frags for nid in f.node_ids)


def test_rebalance_llm_moves_applied():
    llm = MockLLM()
    cfg = AlgorithmConfig()
    cfg.llm_rebalance_enabled = True
    dag, shape = shape_task("开发一个带用户系统的网站", llm)
    from golden_ratio.models import Fragment
    fA = Fragment(fragment_id="X", stage="segment", node_ids=["n1"],
                  text="需求分析", domain_dist={"分析": 1.0}, size=1.0)
    fB = Fragment(fragment_id="Y", stage="segment", node_ids=["n2", "n3"],
                  text="数据库设计 后端接口开发", domain_dist={"数据": 1.0}, size=1.0)
    mover = FakeMoveLLM(moves=[{"from": "X", "to": "Y", "node_ids": ["n1"]}])
    out, _ = rebalance([fA, fB], dag, cfg, shape, mover)
    flat = [nid for f in out for nid in f.node_ids]
    assert sorted(flat) == ["n1", "n2", "n3"], "节点无丢失"
    joined = [f for f in out if "n1" in f.node_ids and "n3" in f.node_ids]
    assert len(joined) == 1, "move 应把 n1 并入 Y"
    assert mover.call_count >= 1, "rebalance_suggest 已被调用"


def test_rebalance_llm_stale_moves_skipped_not_fatal():
    """过时建议（引用已不存在的碎片）应被跳过，不导致任务失败（建议层降级）。"""
    llm = MockLLM()
    cfg = AlgorithmConfig()
    cfg.llm_rebalance_enabled = True
    dag, shape = shape_task("开发一个带用户系统的网站", llm)
    from golden_ratio.models import Fragment
    fA = Fragment(fragment_id="X", stage="segment", node_ids=["n1"],
                  text="需求分析", domain_dist={"分析": 1.0}, size=1.0)
    fB = Fragment(fragment_id="Y", stage="segment", node_ids=["n2", "n3"],
                  text="数据库设计 后端接口开发", domain_dist={"数据": 1.0}, size=1.0)
    # 静态 FakeMoveLLM：两轮都返回同一 moves——第二轮 X 已不存在 → 应跳过而非崩溃
    mover = FakeMoveLLM(moves=[{"from": "X", "to": "Y", "node_ids": ["n1"]}])
    out, rounds = rebalance([fA, fB], dag, cfg, shape, mover)
    flat = [nid for f in out for nid in f.node_ids]
    assert sorted(flat) == ["n1", "n2", "n3"], "节点无丢失"
    assert rounds >= 1


def test_keyify_llm_scores_when_enabled():
    llm = MockLLM()
    cfg = AlgorithmConfig()
    cfg.llm_key_scoring_enabled = True
    before = llm.call_count
    toks = extract_keys("开发一个带用户系统的网站", cfg, llm=llm)
    assert llm.call_count > before, "开启后 score_keys 被调用"
    scores = [t.score for t in toks]
    assert scores and scores[0] >= scores[-1]      # Mock score_keys 单调降序


def test_keyify_rule_fallback_when_disabled():
    llm = MockLLM()
    cfg = AlgorithmConfig()
    before = llm.call_count
    extract_keys("开发一个带用户系统的网站", cfg)   # 未传 llm
    assert llm.call_count == before, "默认不调用 score_keys"


def test_shape_validates_retries_once_on_bad_output():
    llm = FakeShapeLLM(bad_first=True)
    dag, _ = shape_task("写一封请假邮件", llm)
    assert llm.calls == 2, "首次非法应重试一次"
    assert len(dag.nodes) == 1


def test_shape_raises_after_two_bad_outputs():
    llm = FakeShapeLLM(always_bad=True)
    with pytest.raises(ValueError):
        shape_task("写一封请假邮件", llm)


def test_pipeline_default_runs_without_llm_extra_methods():
    llm = MockLLM()
    result = run_pipeline("写一封请假邮件", llm)
    assert result.fragments[0].key_tokens
    assert llm.call_count <= 3, "默认流水线仅形状化+（无 merge/score 调用）"


def test_shape_prompt_requires_exec_nodes():
    """S-B（2026-09-05）：形状化契约加固——执行类任务必须有执行节点（prompt 层）。"""
    from golden_ratio.realllm import SHAPE_SYSTEM_PROMPT
    assert "执行节点" in SHAPE_SYSTEM_PROMPT
    assert "deliverable 为 code 或 text" in SHAPE_SYSTEM_PROMPT


def test_shape_prompt_single_responsibility_domains():
    """真测 REAL-3（方案 a）：节点单一职责——构造与验收不得混在同一节点。

    构造节点（创建/编写/实现/生成）只描述产出；验收节点（验收/校验/确认）
    只描述核对与结论——防构造节点被验证语义抢走（T1 实证）。
    """
    from golden_ratio.realllm import SHAPE_SYSTEM_PROMPT
    assert "单一职责" in SHAPE_SYSTEM_PROMPT
    assert "构造" in SHAPE_SYSTEM_PROMPT and "验收" in SHAPE_SYSTEM_PROMPT
