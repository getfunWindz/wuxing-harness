import pathlib
import tempfile

from wuxing.llm.brain import BrainMemory
from wuxing.llm.router import ModelRouter


def _mk_brain(cases):
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    for c in cases:
        mem.record(**c)
    return mem

def test_strong_evidence_overrides():
    mem = _mk_brain([{"key": "验证|测试|回归", "domain": "verify",
                      "model": "anthropic:claude-sonnet-5", "success": True}])
    r = ModelRouter({"verify": "deepseek:deepseek-chat", "_default": "mock"}, brain=mem)
    p = r.for_domain("verify", fragment_key="验证 测试 回归")
    assert p.name().startswith("anthropic")  # 强证据覆盖（相似 1.0≥0.7 且 成功率=1.0）

def test_no_evidence_falls_back():
    mem = BrainMemory(pathlib.Path(tempfile.mkdtemp()) / "b.json")
    r = ModelRouter({"verify": "deepseek:deepseek-chat", "_default": "mock"}, brain=mem)
    p = r.for_domain("verify", fragment_key="完全无关")
    assert p.name().startswith("deepseek")  # 回退域路由

def test_weak_evidence_wheel():
    # 弱证据（相似但 success=False）→ 轮盘（可能选记忆或回退——断言合法 provider）
    mem = _mk_brain([{"key": "验证|测试", "domain": "verify",
                      "model": "openai:gpt-4o", "success": False}])
    r = ModelRouter({"verify": "deepseek:deepseek-chat", "_default": "mock"}, brain=mem)
    p = r.for_domain("verify", fragment_key="验证 测试 回归")
    assert p.name() in ("openai-compat:gpt-4o", "deepseek:deepseek-chat")

def test_no_brain_keeps_behavior():
    r = ModelRouter({"plan": "deepseek:deepseek-chat", "_default": "mock"})
    p = r.for_domain("plan", fragment_key="任意")
    assert p.name().startswith("deepseek")

def test_domain_candidate_list():
    # P15 决策 A：域级多候选（模拟真实多 API 场景）——无记忆回退 = 候选[0]
    r = ModelRouter({"verify": ["deepseek:deepseek-chat", "anthropic:claude-sonnet-5"],
                     "_default": "mock"})
    p = r.for_domain("verify")
    assert p.name() == "deepseek:deepseek-chat"


def test_brain_pick_uses_spec_field():
    # D1c：记忆案例带 spec（可回构）；model 字段为旧名（兼容）
    mem = _mk_brain([])
    mem.cases.append({"key": "验证|测试|回归", "domain": "verify",
                      "model": "openai-compat:gpt-4o", "spec": "openai:gpt-4o",
                      "success": True, "attempts": 1, "last_at": 1.0})
    r = ModelRouter({"verify": ["deepseek:deepseek-chat", "anthropic:claude-sonnet-5"]},
                    brain=mem)
    picked = r._brain_pick("verify", "验证 测试 回归")
    assert picked is not None  # spec 回构成功（旧实现 create_provider(opencai-compat) 抛 ValueError）
    assert picked.name() == "openai-compat:gpt-4o"


def test_brain_pick_falls_back_on_not_spec():
    # 兼容：旧案例无 spec 字段，model 名恰好可回构（deepseek:...）——
    # sim=1.0 → 强覆盖确定性（避免随机轮盘 flaky）
    mem = _mk_brain([])
    mem.cases.append({"key": "验证|测试|回归", "domain": "verify",
                      "model": "deepseek:deepseek-chat",
                      "success": True, "attempts": 2, "last_at": 1.0})
    r = ModelRouter({"verify": ["anthropic:claude-sonnet-5"]}, brain=mem)
    picked = r._brain_pick("verify", "验证 测试 回归")
    assert picked is not None
    assert picked.name() == "deepseek:deepseek-chat"


def test_brain_pick_tolerates_unreconstructable_spec(monkeypatch):
    """2026-10-01 壳端复验 P1：记忆案例 spec 不可回构（旧 responses name()）→
    不得抛错中断任务；安全回退（None → 调用方走域路由）。

    现场：openai-responses 适配器缺 spec()，首任务成功但把 name() 记入记忆；
    第二个相似任务命中强证据 → create_provider('openai-responses:…')
    → ValueError: 未知 provider type → 任务 error。"""
    mem = _mk_brain([])
    mem.cases.append({"key": "改写|文件|两行", "domain": "execute",
                      "model": "openai-responses:deepseek-flash",
                      "spec": "openai-responses:deepseek-flash",
                      "success": True, "attempts": 1, "last_at": 2.0})
    r = ModelRouter({"execute": "deepseek:deepseek-chat", "_default": "mock"},
                    brain=mem)
    picked = r._brain_pick("execute", "改写 文件 两行")   # 不得抛 ValueError
    assert picked is None or picked.name() == "deepseek:deepseek-chat"


def test_brain_pick_falls_back_on_runtime_key_error(tmp_path, monkeypatch):
    """2026-10-01 真机 P1（续）：重建 provider 抛 RuntimeError（凭据丢失
    『未配置 OPENAI_API_KEY』）同样必须回退，不得中断任务。"""
    import wuxing.credentials as creds
    monkeypatch.setattr(creds, "credentials_path", lambda: tmp_path / "c.json")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    mem = _mk_brain([])
    mem.cases.append({"key": "设计|产品|方案", "domain": "design",
                      "model": "openai-responses:deepseek-flash",
                      "spec": {"type": "responses", "model": "deepseek-flash",
                               "base_url": "https://api.deepseek.com"},
                      "success": True, "attempts": 1, "last_at": 2.0})
    r = ModelRouter({"design": "deepseek:deepseek-chat", "_default": "mock"},
                    brain=mem)
    picked = r._brain_pick("design", "设计 产品 方案")   # 不得抛 RuntimeError
    assert picked is None or picked.name() == "deepseek:deepseek-chat"


def test_brain_pick_weak_branch_tolerates_unreconstructable_spec(monkeypatch):
    """弱证据轮盘分支同样要容错（2026-10-01 实战路径：相似度 <0.7 走轮盘），
    _wheel 会把记忆 spec 并入候选——选中脏 spec 时须安全回退。"""
    import wuxing.llm.router as router_mod
    mem = _mk_brain([])
    mem.cases.append({"key": "改写|文件|两行", "domain": "execute",
                      "model": "openai-responses:deepseek-flash",
                      "spec": "openai-responses:deepseek-flash",
                      "success": True, "attempts": 1, "last_at": 2.0})
    r = ModelRouter({"execute": "deepseek:deepseek-chat", "_default": "mock"},
                    brain=mem)
    monkeypatch.setattr(router_mod.random, "choices",
                        lambda candidates, weights, k: ["openai-responses:deepseek-flash"])
    picked = r._brain_pick("execute", "改写 文件 两行")   # 不得抛 ValueError
    assert picked is None or picked.name() == "deepseek:deepseek-chat"


def test_brain_wheel_includes_unexplored_candidates():
    """P15 发现：纯利用轮盘只含「用过的模型」→ 在线学习死锁候选[0]，A/B 零信号。
    探索机制：候选集中未使用的模型以先验权重进入轮盘（否则智脑永不尝试新模型）。"""
    from wuxing.llm.router import EXPLORE_PRIOR, _wheel
    hits = [{"model": "deepseek:deepseek-chat", "spec": "deepseek:deepseek-chat",
             "success": False, "similarity": 0.6}]
    cands = ["deepseek:deepseek-chat", "openai:gpt-4o"]
    weights, picked = _wheel(hits, cands)
    assert "openai:gpt-4o" in picked  # 未探索候选进入轮盘
    assert weights[picked.index("openai:gpt-4o")] == EXPLORE_PRIOR
    # B1：失败案例权重 = 成功率(0) × 相似度——失败模型零权重（成功率口径）
    assert abs(weights[picked.index("deepseek:deepseek-chat")] - 0.0) < 1e-9


def test_brain_wheel_all_known_no_duplicates():
    from wuxing.llm.router import _wheel
    hits = [{"model": "deepseek:deepseek-chat", "spec": "deepseek:deepseek-chat",
             "success": True, "similarity": 0.6}]
    _weights, picked = _wheel(hits, ["deepseek:deepseek-chat", "openai:gpt-4o"])
    assert picked.count("deepseek:deepseek-chat") == 1  # 不重复
    assert len(picked) == 2


def test_router_cache_key_with_dict_candidate():
    """P15 真跑发现：候选含 dict spec（中转站 base_url）时缓存键不可哈希——TypeError。"""
    r = ModelRouter({"verify": ["deepseek:deepseek-chat",
                                 {"type": "openai", "model": "gpt-5.6-luna",
                                  "base_url": "https://www.micuapi.ai/v1"}]})
    p1 = r.for_domain("verify")
    p2 = r.for_domain("verify")  # 第二次应命中缓存（不再构造）
    assert p1.name() == p2.name() == "deepseek:deepseek-chat"


def test_router_dict_spec_single_candidate():
    """dict spec（中转站单候选）不得被 list() 拆 keys——4b 评分场景崩溃回归。"""
    r = ModelRouter({"_default": {"type": "openai", "model": "kimi-k2.7-code",
                                  "base_url": "https://www.micuapi.ai/v1"},
                     "plan": "deepseek:deepseek-chat"})
    p = r.for_domain("execute")  # _default dict 路径
    assert p.name() == "openai-compat:kimi-k2.7-code"


def test_brain_pick_strong_evidence_not_shadowed_by_weak_high_tier(monkeypatch):
    """第七轮审查：强证据判定必须在（同域）命中集内做——弱相似 high 案例不得
    压制精确匹配强证据（规格 §15.3：强证据→确定性覆盖）。

    run-2 实测：tier-first 排序使 hits[0]=弱相似 high（sim≈0.05）→ 强证据判定
    失准 → 决策落入探索轮盘（同 key 先后抽中 mimo/glm——见 AB 报告 §3）。
    """
    import wuxing.llm.router as router_mod
    mem = _mk_brain([])
    mem.cases.append({"key": "单元测试与模块配置验证", "domain": "verify",
                      "model": "deepseek:deepseek-chat",
                      "spec": "deepseek:deepseek-chat", "success": True,
                      "success_count": 1, "attempts": 1, "last_at": 1e12,
                      "tier": "high"})  # 弱相似 high（仅共享极少词元）
    mem.cases.append({"key": "执行运营商侧修复与优化（网络刷新、换卡）",
                      "domain": "verify", "model": "openai-compat:mimo-v2.5",
                      "spec": {"type": "openai", "model": "mimo-v2.5",
                               "base_url": "https://api.xiaomimimo.com/v1"},
                      "success": True, "success_count": 1, "attempts": 1,
                      "last_at": 1e11, "tier": "normal"})  # 精确匹配强证据

    def _boom(*_a, **_k):
        raise AssertionError("强证据存在时不得进入探索轮盘（应确定性覆盖）")

    monkeypatch.setattr(router_mod.random, "choices", _boom)
    r = ModelRouter({"verify": ["deepseek:deepseek-chat",
                                 {"type": "openai", "model": "mimo-v2.5",
                                  "base_url": "https://api.xiaomimimo.com/v1"}]},
                    brain=mem)
    picked = r._brain_pick("verify", "执行运营商侧修复与优化（网络刷新、换卡）")
    assert picked is not None
    assert picked.name() == "openai-compat:mimo-v2.5", \
        "精确匹配强证据必须确定性命中（不得被弱相似 high 压制进轮盘）"


def test_brain_pick_domain_filter_precedes_topk():
    """跨域 top-5 截断不得挤掉同域精确匹配（域过滤先于截断）。

    第七轮审查（run-2 同源风险）：搜索先按 tier 截断 top-5 再按域过滤——
    6 个他域 high 案例可把同域精确匹配挤出，导致记忆指导整体失效（回退域路由）。
    """
    mem = _mk_brain([])
    for i in range(6):
        mem.cases.append({"key": f"执行模块{i}验证", "domain": "execute",
                          "model": "deepseek:deepseek-chat",
                          "spec": "deepseek:deepseek-chat", "success": True,
                          "success_count": 1, "attempts": 1, "last_at": 1e12,
                          "tier": "high"})
    mem.cases.append({"key": "验证 测试 回归", "domain": "verify",
                      "model": "anthropic:claude-sonnet-5",
                      "spec": "anthropic:claude-sonnet-5", "success": True,
                      "success_count": 1, "attempts": 1, "last_at": 1e11,
                      "tier": "normal"})  # 同域精确匹配（相似度 1.0）
    r = ModelRouter({"verify": "deepseek:deepseek-chat"}, brain=mem)
    picked = r._brain_pick("verify", "验证 测试 回归")
    assert picked is not None and picked.name().startswith("anthropic"), \
        "同域精确匹配不得被他域 top-k 截断挤出（域过滤必须先于截断）"
