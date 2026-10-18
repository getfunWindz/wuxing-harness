"""TDD：FSC 核心——工作流键 / 匹配 / 三重闸门 / 淘汰。"""
from wuxing.session_pool import (
    SessionPool,
    assign_tags,
    extract_dirs,
    extract_tag_contexts,
    fsc_key,
)


def test_extract_dirs_from_text_and_paths():
    """目录提取：文本路径提及 + 依赖产物路径 → Top-2 目录前缀集合。"""
    dirs = extract_dirs("请更新 docs/api.md 与 backend/src/main/java/A.java",
                        "plans/x.md\nfrontend/src/app.js")
    assert "docs" in dirs and "backend/src" in dirs and "frontend/src" in dirs


def test_fsc_key_requires_dirs():
    """无目录 → 无键（保守：不发动，不猜）。"""
    assert fsc_key("execute", "写一个脚本", "") is None
    key = fsc_key("execute", "更新 tools/rename.py", "")
    assert key == ("execute", frozenset({"tools"}))


def test_exact_key_and_domain_isolation():
    """精确键语义（用户裁决 2026-09-12·方案2）：同域 + 键完全相等才命中。

    修订记录：初稿设计 §2.2 的 Jaccard 阈值匹配未落地且并发会话互斥复杂——
    正式定稿为**精确键相等**（域 + frozenset(目录/标签)）；C 标签通道使键可靠。
    """
    p = SessionPool(retention_rounds=4)
    assert not hasattr(p, "match_threshold"), "阈值死配置必须移除（方案2）"
    p.retain(fsc_key("execute", "docs/a.md", ""), "execute",
             [{"role": "user", "content": "工作历史"}], unit_id="U-1", current_round=1)
    # 归约后键相等（均为 {"docs"}）→ 命中
    hit = p.match("execute", fsc_key("execute", "docs/b.md", ""), current_round=2)
    assert hit is not None and hit.unit_id == "U-1"
    # 跨域不命中（同键目录也不行）
    assert p.match("plan", fsc_key("execute", "docs/b.md", ""), current_round=2) is None
    # 部分重叠（{"docs"} vs {"docs","tools"}）不命中——精确键语义（推翻 Jaccard）
    assert p.match("execute", fsc_key("execute", "docs/c.md 与 tools/x.py", ""),
                   current_round=2) is None
    # 目录不重合 → 不命中
    assert p.match("execute", fsc_key("execute", "web/a.md", ""), current_round=2) is None


def test_retention_rounds_eviction():
    p = SessionPool(retention_rounds=2)
    p.retain(fsc_key("execute", "docs/a.md", ""), "execute", [], unit_id="U-1",
             current_round=1)
    assert p.match("execute", fsc_key("execute", "docs/b.md", ""),
                   current_round=3) is not None
    assert p.match("execute", fsc_key("execute", "docs/b.md", ""),
                   current_round=4) is None  # 轮龄 3 > K=2


def test_gates_session_chars_and_reuse_and_budget():
    """三重闸门：单会话字符上限 / 复用次数上限 / 池总预算——超限即不再复用。"""
    p = SessionPool(max_session_chars=100, max_reuse=2, total_char_budget=1000)
    key = fsc_key("execute", "docs/a.md", "")
    big = [{"role": "user", "content": "x" * 200}]
    p.retain(key, "execute", big, unit_id="U-1", current_round=1)
    # 单会话超字符上限 → 不匹配（但记录仍可留档）
    assert p.match("execute", fsc_key("execute", "docs/b.md", ""),
                   current_round=2) is None


def test_reuse_cap_and_stats():
    p = SessionPool(max_reuse=2)
    key = fsc_key("execute", "docs/a.md", "")
    p.retain(key, "execute", [{"role": "user", "content": "h"}], unit_id="U-1",
             current_round=1)
    m = p.match("execute", fsc_key("execute", "docs/b.md", ""), current_round=2)
    assert m is not None
    p.retain(key, "execute", [{"role": "user", "content": "h2"}], unit_id="U-2",
             current_round=2, reused=True)
    m2 = p.match("execute", fsc_key("execute", "docs/c.md", ""), current_round=3)
    assert m2 is not None
    p.retain(key, "execute", [{"role": "user", "content": "h3"}], unit_id="U-3",
             current_round=3, reused=True)
    # 复用次数已达上限 → 不再匹配
    assert p.match("execute", fsc_key("execute", "docs/d.md", ""),
                   current_round=4) is None
    st = p.stats()
    assert st["reused"] == 2 and st["pool_size"] >= 1


def test_total_budget_evicts_oldest():
    """池总预算：超限淘汰最旧（LRU）。"""
    p = SessionPool(total_char_budget=300, max_session_chars=10 ** 6)
    for i in range(3):
        p.retain(fsc_key("execute", f"docs{i}/a.md", ""), "execute",
                 [{"role": "user", "content": "x" * 150}], unit_id=f"U-{i}",
                 current_round=i + 1)
    st = p.stats()
    assert st["pool_size"] <= 2, st
    assert st["evicted"] >= 1, st


def test_note_fragment_counts_key_coverage():
    """键覆盖率口径（A2）：note_fragment 登记 keyed/unkeyed——
    覆盖率 = keyed/(keyed+unkeyed)（mock 验收与真机报告共用同一口径）。"""
    p = SessionPool()
    p.note_fragment(True)
    p.note_fragment(True)
    p.note_fragment(False)
    st = p.stats()
    assert st["keyed"] == 2 and st["unkeyed"] == 1, st


def test_pool_stats_mutations_under_guard():
    """六轮审查 C1（确定性口径）：_stats 自增必须在 _guard 内。

    给 _stats 换成「写入时断言锁已持」的字典——原实现的 matched/over_window
    在锁外自增，本测试单线程即可复现（非概率口径）。"""
    class _AssertLockedDict(dict):
        def __init__(self, guard, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._guard = guard

        def __setitem__(self, k, v):
            assert self._guard.locked(), f"stats mutation outside guard: {k}"
            super().__setitem__(k, v)

    p = SessionPool(context_window=1000, audit_ratio=0.6, switch_ratio=0.95)
    p._stats = _AssertLockedDict(p._guard, p._stats)
    key = ("execute", frozenset({"docs"}))
    p.retain(key, "execute", [{"role": "user", "content": "x" * 650}],
             unit_id="U-1", current_round=1)  # over_window 路径
    s = p.match("execute", key, 2)            # matched 路径
    assert s is not None
    p.mark_audited(key)                        # audited 路径
    p.retain(key, "execute", [{"role": "user", "content": "x" * 700}],
             unit_id="U-2", current_round=2, reused=True)


def test_pool_stats_thread_safe():
    """六轮审查 C1：统计自增必须在 _guard 内——多线程并发 match/retain
    不得丢计数（原实现 matched/over_window 在锁外自增）。"""
    import threading
    p = SessionPool(retention_rounds=1000, max_session_chars=10 ** 9,
                    total_char_budget=10 ** 9)
    n_threads, per_thread = 8, 50
    errors = []

    def worker(t):
        try:
            for i in range(per_thread):
                key = ("execute", frozenset({f"w{t}-{i}"}))
                p.retain(key, "execute", [{"role": "user", "content": "h"}],
                         unit_id=f"U-{t}-{i}", current_round=1)
                if p.match("execute", key, 2) is None:
                    errors.append((t, i))
        except Exception as e:  # 测试线程内任意异常都收集（不中断其他线程）
            errors.append(repr(e))

    ts = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    st = p.stats()
    assert not errors, errors[:3]
    assert st["matched"] == n_threads * per_thread, \
        f"并发下 matched 计数不得丢失（实际 {st['matched']}）"


def test_workstream_tag_channel_c():
    """C 通道（用户裁决 2026-09-11）：显式工作流标签可直接键控——无路径也能稳定匹配。"""
    from wuxing.session_pool import extract_tags, fsc_key
    assert extract_tags("工作流：docs/guide") == {"docs/guide"}
    assert extract_tags("workstream:backend/src") == {"backend/src"}
    key = fsc_key("execute", "按工作流：docs 更新文档", "")
    assert key == ("execute", frozenset({"docs"}))
    assert fsc_key("execute", "无任何键源", "") is None


def test_extract_tag_contexts():
    """C 通道（A 阶段）：从 plan 文本提取「标签 + 上下文行」——去重保序。"""
    text = ("## 实施工作流\n"
            "- 工作流：docs——更新用户手册与指南\n"
            "- workstream: backend/src——实现接口与测试\n"
            "工作流：docs（文档校审）\n")
    items = extract_tag_contexts(text)
    assert items == [("docs", "- 工作流：docs——更新用户手册与指南"),
                     ("backend/src", "- workstream: backend/src——实现接口与测试")], \
        items


def test_assign_tags_by_overlap_and_single_fallback():
    """标签分配：token 重叠取最高分；单标签全量兜底；多标签零重叠不越权。"""
    frags = [{"fragment_id": "F-1", "text": "更新用户手册与指南文档"},
             {"fragment_id": "F-2", "text": "实现后端接口代码"}]
    out = assign_tags(frags, [("docs", "工作流：docs——更新用户手册与指南"),
                              ("backend/src", "工作流：backend/src——实现接口")])
    assert out == {"F-1": ["docs"], "F-2": ["backend/src"]}, out
    # 单标签兜底：无重叠也全量继承（同一工作流——C 通道语义）
    out2 = assign_tags(frags, [("docs", "工作流：docs——无关描述")])
    assert out2 == {"F-1": ["docs"], "F-2": ["docs"]}, out2
    # 多标签且均零重叠：保守不分配（宁缺毋滥——防幻觉）
    out3 = assign_tags(frags, [("a/b", "工作流：a/b——甲事务"),
                               ("c/d", "工作流：c/d——乙事务")])
    assert out3 == {"F-1": [], "F-2": []}, out3


def test_audit_flag_survives_retain_replace():
    """六轮审查 B1：审计标记必须跨 retain 换代保持（设计「每会话一次」）。

    原实现：retain 新建 FragmentSession（audited=False）→ 每次延续都重复
    注入审计指令（实测 4 轮 2 次）。"""
    p = SessionPool(context_window=1000, audit_ratio=0.6, switch_ratio=0.95)
    key = ("execute", frozenset({"docs"}))
    p.retain(key, "execute", [{"role": "user", "content": "x" * 650}],
             unit_id="U-1", current_round=1)
    s = p.match("execute", key, 2)
    assert s is not None and s.audit_pending is True, "65% 必须标记审计"
    p.mark_audited(key)
    p.retain(key, "execute", [{"role": "user", "content": "x" * 700}],
             unit_id="U-2", current_round=2, reused=True)
    s2 = p.match("execute", key, 3)
    assert s2 is not None and s2.audit_pending is False, \
        "审计已注入——换代后不得重复标记（audited 必须继承）"
