"""E2-3（⑰）：提示词分节/节级哈希/稳定标注/跨域公共段（设计 §5 清单守卫）。"""
from wuxing.domains.defaults import DEFAULT_DOMAINS

EXECUTE_DOMAIN = DEFAULT_DOMAINS["execute"]
PLAN_DOMAIN = DEFAULT_DOMAINS["plan"]


class _Tool:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def description(self):
        return f"{self._name} 描述"


def test_sections_join_equals_build_system_text():
    from wuxing.prompt_builder import build_system_text, system_sections
    for thin in (False, True):
        secs = system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 5,
                               thin=thin)
        assert "".join(s["text"] for s in secs) == build_system_text(
            EXECUTE_DOMAIN, [_Tool("bash")], True, 5, thin=thin)
        names = [s["name"] for s in secs]
        assert names == ["contract", "domain", "tools", "budget"], names
        assert {s["stability"] for s in secs} == {"static", "unit"}


def test_budget_section_only_unit_variant():
    from wuxing.prompt_builder import system_sections
    from wuxing.prompt_sections import diff_sections, hash_sections
    a = hash_sections(system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 5))
    b = hash_sections(system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 3))
    assert diff_sections(a, b) == {"changed": ["budget"], "added": [],
                                   "removed": []}
    secs = system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 5)
    contract = secs[0]["text"]
    budget = secs[3]["text"]
    assert "5 轮思考" not in contract and "轮思考" not in contract
    assert "5 轮思考" in budget


def test_system_bytes_stable_twice():
    from wuxing.prompt_builder import build_system_text, system_sections
    from wuxing.prompt_sections import hash_sections
    t1 = build_system_text(EXECUTE_DOMAIN, [_Tool("bash")], True, 5)
    t2 = build_system_text(EXECUTE_DOMAIN, [_Tool("bash")], True, 5)
    assert t1 == t2
    assert hash_sections(system_sections(EXECUTE_DOMAIN, [_Tool("bash")],
                                         True, 5)) == \
        hash_sections(system_sections(EXECUTE_DOMAIN, [_Tool("bash")],
                                      True, 5))


def test_cross_domain_shared_prefix_covers_contract():
    from wuxing.prompt_builder import build_system_text, system_sections
    plan = build_system_text(PLAN_DOMAIN, [_Tool("read_file")], True, 5)
    verify = build_system_text(EXECUTE_DOMAIN, [_Tool("bash")], True, 3)
    contract = system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True,
                               3)[0]["text"]
    assert plan.startswith(contract) and verify.startswith(contract)
    n = 0
    for a, b in zip(plan, verify):
        if a != b:
            break
        n += 1
    assert n >= len(contract)          # 跨域共享前缀 ≥ 契约节（预算尾部化收益）
    assert "数据面纪律" in verify[:n]   # 共享前缀覆盖数据面纪律


def test_message_hashes_isolate_changes():
    from wuxing.prompt_sections import diff_sections, message_hashes
    base = [{"role": "system", "content": "S"},
            {"role": "user", "content": "[上一轮碎片上下文]digest-A"},
            {"role": "user", "content": "[会话历史]\n第1轮"},
            {"role": "user", "content": "任务背景：A"}]
    changed = [dict(base[0]),
               {"role": "user", "content": "[上一轮碎片上下文]digest-B"},
               dict(base[2]), dict(base[3])]
    d = diff_sections(message_hashes(base), message_hashes(changed))
    assert d == {"changed": ["digest"], "added": [], "removed": []}


def test_prompt_sections_trace_event(tmp_path):
    import json

    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(cfg=EngineConfig(llm="mock"), workdir=tmp_path,
                 auto_confirm=True)
    eng.run_task("写一个报告")
    rows = [json.loads(x) for x in
            (tmp_path / ".wuxing" / "trace.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
    ev = [r for r in rows if r.get("event") == "prompt_sections"]
    assert ev, "缺少 prompt_sections trace 事件"
    h = ev[-1].get("hashes") or {}
    assert "sys:contract" in h and "sys:budget" in h and "msg:prompt" in h


def test_custom_notes_and_addendum_sections():
    """#3：notes 覆盖域节、addendum 追加 custom 节（domain 后）。"""
    from wuxing.prompt_builder import system_sections
    secs = system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 5,
                           custom={"notes": "自定义注记", "addendum": "自定义补充段"})
    names = [s["name"] for s in secs]
    assert names == ["contract", "domain", "custom", "tools", "budget"], names
    assert "自定义注记" in secs[1]["text"]
    assert "自定义补充段" in secs[2]["text"]
    assert secs[2]["stability"] == "static"


def test_custom_empty_equals_default_bytes():
    """#3：无配置/空配置 → 与现状逐字节一致（回归基准）。"""
    from wuxing.prompt_builder import build_system_text
    base = build_system_text(EXECUTE_DOMAIN, [_Tool("bash")], True, 5)
    assert build_system_text(EXECUTE_DOMAIN, [_Tool("bash")], True, 5,
                             custom={"notes": "", "addendum": ""}) == base
    assert build_system_text(EXECUTE_DOMAIN, [_Tool("bash")], True, 5,
                             custom=None) == base


def test_custom_addendum_only_keeps_domain_bytes():
    from wuxing.prompt_builder import system_sections
    a = system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 5)
    b = system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 5,
                        custom={"addendum": "仅补充"})
    assert a[1]["text"] == b[1]["text"], "只加 addendum 不应改 domain 节"
    assert [s["name"] for s in b] == ["contract", "domain", "custom",
                                      "tools", "budget"]


def test_custom_bytes_stable_twice():
    from wuxing.prompt_builder import system_sections
    from wuxing.prompt_sections import hash_sections
    custom = {"notes": "N", "addendum": "A"}
    assert hash_sections(system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 5,
                                         custom=custom)) == \
        hash_sections(system_sections(EXECUTE_DOMAIN, [_Tool("bash")], True, 5,
                                      custom=custom))
