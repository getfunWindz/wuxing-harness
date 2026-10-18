"""TDD · L3-2：记忆遗忘（7 步第 6 步——降权不删除，与缓存协同）。

知识库标准：遗忘策略=降权不删除（非硬删除；与缓存/成本联动）。
机制：search 打分 × 衰减（时间半衰 30 天 + 尝试次数惩罚）——tier 分级不变，
同级内排序 sim×decay；用例文件绝不减少（LRU 池容量逐出是唯一删除路径）。
"""
import pathlib
import tempfile
import time

from wuxing.llm.brain import BrainMemory


def _mk_brain():
    return BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")


def _record(bm, key, tier="normal", success=True, age_days=0, attempts=1):
    c = {"key": key, "domain": "execute", "model": "m", "spec": "m",
         "success": success, "attempts": attempts, "last_at": time.time() - age_days * 86400,
         "tier": tier}
    bm.cases.append(c)
    return c


def test_old_case_ranked_after_new_case():
    """同 tier 同相似度：新案例排前（时间衰减——降权不删除）。"""
    bm = _mk_brain()
    _record(bm, "开发登录功能 生成验证码", tier="normal", age_days=0)
    _record(bm, "开发登录功能 短信验证", tier="normal", age_days=60)
    hits = bm.search("开发登录功能 验证码", top_k=5)
    assert len(hits) == 2, "降权不删除：旧案例仍返回"
    assert hits[0]["key"].startswith("开发登录功能 生成验证码"), \
        "新案例必须排前（旧案例衰减后靠后）"


def test_decay_does_not_delete_cases():
    """遗忘=降权：任何 search 都不减少 cases（文件用例数守恒——LRU 池是唯一删除）。"""
    bm = _mk_brain()
    for i in range(10):
        _record(bm, f"任务{i} 写报告", tier="normal", age_days=i * 10)
    n_before = len(bm.cases)
    bm.search("写报告", top_k=3)
    assert len(bm.cases) == n_before, "search 不得删除用例（降权不删除）"


def test_attempt_penalty_ranks_fewer_attempts_first():
    """尝试次数惩罚：同时间同 tier——attempts 少的排前（反复失败经验降权）。"""
    bm = _mk_brain()
    _record(bm, "解析 JSON 数据 生成报表", tier="normal", attempts=5)
    _record(bm, "解析 JSON 数据 生成图表", tier="normal", attempts=1)
    hits = bm.search("解析 JSON 数据", top_k=5)
    assert hits[0]["key"].endswith("生成图表"), \
        "少尝试案例应排前（多尝试=反复失败/反复命中，降权）"


def test_tier_priority_unchanged_by_decay():
    """衰减不改 tier 优先级：high 案例（即使旧）仍排 normal（新）前——分级护栏。"""
    bm = _mk_brain()
    _record(bm, "查询数据库 写报告", tier="high", age_days=90)
    _record(bm, "查询数据库 写报表", tier="normal", age_days=0)
    hits = bm.search("查询数据库", top_k=5)
    assert hits[0]["tier"] == "high", "tier 分级优先于时间衰减（三级参照表不破坏）"
