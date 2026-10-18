"""TDD：技能自进化（用户裁决 2026-09-12——默认开）。

高效任务（机械证据 + LLM 自评审双确认）→ 沉淀 SKILL.md 到用户级 skills 目录；
失败静默、同名不覆盖（技能是优化不是生命线）。
"""
import json

from wuxing.protocols import UnitResult


def _units(*statuses):
    us = []
    for i, st in enumerate(statuses):
        u = UnitResult(unit_id=f"F-{i}", domain_id="execute", status=st)
        u.artifacts = []
        us.append(u)
    return us


class _JsonLlm:
    def __init__(self, payload):
        self.payload = payload if isinstance(payload, str) else json.dumps(payload)

    def name(self):
        return "json-llm"

    def chat(self, messages, tools=None):
        return self.payload


def test_efficiency_evidence_gate():
    from wuxing.skill_evolution import efficiency_evidence

    assert efficiency_evidence(_units("ok", "ok"), "done") is not None
    assert efficiency_evidence(_units("ok", "failed"), "done") is None
    assert efficiency_evidence(_units("ok"), "partial") is None
    assert efficiency_evidence([], "done") is None


def test_review_and_distill_installs_on_efficient(tmp_path):
    from wuxing.skill_evolution import review_and_distill

    llm = _JsonLlm({"efficient": True, "reason": "方法论可复用",
                    "skill": {"name": "batch-verify-flow",
                              "description": "批量验收流程",
                              "body": "## 用法\n先读产物再给结论。"}})
    res = review_and_distill("任务", _units("ok"), "done", llm, skills_dir=tmp_path)
    assert res["installed"] is True and res["name"] == "batch-verify-flow"
    md = (tmp_path / "batch-verify-flow" / "SKILL.md").read_text(encoding="utf-8")
    assert "batch-verify-flow" in md and "批量验收流程" in md


def test_review_and_distill_skips_when_not_efficient(tmp_path):
    from wuxing.skill_evolution import review_and_distill

    llm = _JsonLlm({"efficient": False, "reason": "普通任务", "skill": None})
    res = review_and_distill("任务", _units("ok"), "done", llm, skills_dir=tmp_path)
    assert res["installed"] is False
    assert not any(tmp_path.iterdir())


def test_review_and_distill_swallows_bad_output(tmp_path):
    from wuxing.skill_evolution import review_and_distill

    res = review_and_distill("任务", _units("ok"), "done", _JsonLlm("no json"),
                             skills_dir=tmp_path)
    assert res["installed"] is False
    assert not any(tmp_path.iterdir())


def test_review_and_distill_no_overwrite(tmp_path):
    from wuxing.skill_evolution import review_and_distill

    (tmp_path / "dup-skill").mkdir()
    (tmp_path / "dup-skill" / "SKILL.md").write_text(
        "---\nname: dup-skill\n---\nold", encoding="utf-8")
    llm = _JsonLlm({"efficient": True,
                    "skill": {"name": "dup-skill", "description": "d", "body": "b"}})
    res = review_and_distill("任务", _units("ok"), "done", llm, skills_dir=tmp_path)
    assert res["installed"] is False and res["reason"] == "exists"
    assert "old" in (tmp_path / "dup-skill" / "SKILL.md").read_text(encoding="utf-8")


def test_review_prefix_byte_stable_and_min_size():
    """A13 辅助前缀核对守卫：评审 system 跨调用逐字节稳定且 ≥400 字符。

    证据（FSC 缓存验证报告 §1.2④ + 探针原始载荷复核）：报告时点评审 system
    219 字符、3 run 共 5 次调用全 0 命中；同批缓存命中量全为 128-token 单元
    整数倍（shape 740 字符恒命中 256）。E2-1（2026-10-03）扩写至 457 字符——
    本守卫防回退（前缀低于缓存单元 → 永远 0 命中）。
    """
    from wuxing.skill_evolution import _REVIEW_SYSTEM, build_review_messages
    ev = {"units": 1, "domains": ["execute"]}
    m1 = build_review_messages("任务A", _units("ok"), ev)
    m2 = build_review_messages("任务B", _units("ok"), ev)
    assert [m["role"] for m in m1] == ["system", "user"]
    assert m1[0]["content"] == m2[0]["content"] == _REVIEW_SYSTEM
    assert len(_REVIEW_SYSTEM) >= 400, len(_REVIEW_SYSTEM)


def test_skill_evolution_default_on_and_doublewrite():
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS

    assert EngineConfig().skill_evolution_enabled is True
    assert "skill_evolution_enabled" in {s.name for s in FIELD_SPECS}


def test_engine_calls_hook_on_done_task(monkeypatch, tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine

    called = {}

    def _hook(self, task_text, units, status, metrics=None):
        called["status"] = status
        called["n"] = len(units)
        called["metrics_ok"] = (isinstance(metrics, dict)
                                and "ch_split" in metrics)

    monkeypatch.setattr(Engine, "_skill_evolution_hook", _hook)
    eng = Engine(cfg=EngineConfig(), workdir=tmp_path, auto_confirm=True)
    eng.run_task("写一个简单的报告")
    assert called.get("status") == "done" and called.get("n", 0) >= 1
    # E0-6：hook 收到任务 metrics（辅助账目尾差合并入口）
    assert called.get("metrics_ok"), called


# ---------- E2-1（H1/H12）：沉淀纪律与负面清单 ----------


def test_review_prompt_carries_discipline():
    from wuxing.skill_evolution import _REVIEW_SYSTEM
    for token in ("类级技能", "不要沉淀", "环境依赖故障", "工具负面断言",
                  "未解决失败", "同名不覆盖", "何时用"):
        assert token in _REVIEW_SYSTEM, token


def test_safe_name_kebab():
    from wuxing.skill_evolution import _safe_name
    assert _safe_name("Fix Cache_Bug!") == "fix-cache-bug"
    long = _safe_name("A" * 80)
    assert long.startswith("a") and len(long) <= 40 and long == long.rstrip("-")


# ---------- 2026-10-15：自沉淀前强制查重（异名近义硬闸） ----------

def _mk_user_skill(root, name, body, description="d"):
    d = root / name
    d.mkdir(parents=True, exist_ok=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}\n",
        encoding="utf-8")
    return d


def test_review_and_distill_blocks_near_duplicate(tmp_path):
    from wuxing.skill_evolution import review_and_distill

    body = "步骤一：先写失败测试。步骤二：最小实现。步骤三：回归。"
    _mk_user_skill(tmp_path, "pytest-minimal-function", body,
                   description="纯函数 TDD")
    llm = _JsonLlm({"efficient": True,
                    "skill": {"name": "pytest-minimal-smoke",
                              "description": "冒烟测试",
                              "body": body}})
    res = review_and_distill("任务", _units("ok"), "done", llm,
                             skills_dir=tmp_path)
    assert res["installed"] is False
    assert res["reason"].startswith("near-duplicate:")
    assert res["duplicate_of"] == "pytest-minimal-function"
    assert res["duplicate_description"] == "纯函数 TDD"
    assert res["body_j"] == 1.0
    assert not (tmp_path / "pytest-minimal-smoke").exists()


def test_review_and_distill_allows_distinct(tmp_path):
    from wuxing.skill_evolution import review_and_distill

    _mk_user_skill(tmp_path, "leave-request-email",
                   "写请假邮件：抬头、事由、日期、落款。")
    llm = _JsonLlm({"efficient": True,
                    "skill": {"name": "retry-decorator-tdd",
                              "description": "retry 装饰器",
                              "body": "实现 retry 装饰器：先写失败测试……"}})
    res = review_and_distill("任务", _units("ok"), "done", llm,
                             skills_dir=tmp_path)
    assert res["installed"] is True


def test_review_and_distill_fail_open_on_guard_error(tmp_path, monkeypatch):
    import wuxing.skill_curator as curator_mod
    from wuxing.skill_evolution import review_and_distill

    def boom(*a, **k):
        raise RuntimeError("scan down")

    monkeypatch.setattr(curator_mod, "find_near_duplicate", boom)
    llm = _JsonLlm({"efficient": True,
                    "skill": {"name": "fresh-flow", "description": "d",
                              "body": "b"}})
    res = review_and_distill("任务", _units("ok"), "done", llm,
                             skills_dir=tmp_path)
    assert res["installed"] is True


def test_hook_records_near_duplicate_skip(tmp_path, monkeypatch):
    """命中 → ledger evolve_skipped（source=canonical）+ trace skill_evolve_skipped。

    注：conftest autouse 夹具把 Engine._skill_evolution_hook 置换为空实现
    （测试默认禁自进化）——本测试直调 mixin 实现以覆盖真实分支。
    """
    import wuxing.skill_evolution as se
    from wuxing import skill_ledger
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    from wuxing.engine_skills import EngineSkillsMixin

    user_dir = tmp_path / "user_skills"
    user_dir.mkdir()
    eng = Engine(cfg=EngineConfig(), workdir=tmp_path, auto_confirm=True)
    monkeypatch.setattr(eng.skills, "user_dir", user_dir)
    monkeypatch.setattr(
        se, "review_and_distill",
        lambda *a, **k: {"installed": False, "name": "new-flow",
                         "reason": "near-duplicate:old-flow",
                         "duplicate_of": "old-flow"})
    EngineSkillsMixin._skill_evolution_hook(eng, "任务", _units("ok"), "done")
    rows = skill_ledger.read_events(user_dir)
    assert rows[-1]["event"] == "evolve_skipped"
    assert rows[-1]["skill"] == "new-flow"
    assert rows[-1]["source"] == "old-flow"
    assert eng.trace is not None
    trace_rows = [r for r in eng.trace.load()
                  if r.get("event") == "skill_evolve_skipped"]
    assert trace_rows and trace_rows[-1]["name"] == "new-flow"
    assert trace_rows[-1]["duplicate_of"] == "old-flow"


# ---------- 2026-10-15：评审注入现役技能清单（软层去重） ----------

def test_review_messages_include_skill_cards():
    from wuxing.skill_evolution import _REVIEW_SYSTEM, build_review_messages

    ev = {"units": 1, "domains": ["execute"]}
    cards = [{"name": "pytest-minimal-function", "description": "纯函数 TDD"},
             {"name": "leave-request-email", "description": "请假邮件"}]
    msgs = build_review_messages("任务", _units("ok"), ev, skill_cards=cards)
    assert msgs[0]["content"] == _REVIEW_SYSTEM          # system 不变
    assert "# 现役技能" in msgs[1]["content"]
    assert "pytest-minimal-function: 纯函数 TDD" in msgs[1]["content"]


def test_review_messages_without_cards_unchanged():
    from wuxing.skill_evolution import build_review_messages

    msgs = build_review_messages("任务", _units("ok"),
                                 {"units": 1, "domains": ["execute"]})
    assert "# 现役技能" not in msgs[1]["content"]


def test_review_messages_cards_truncation():
    from wuxing.skill_evolution import (
        _CARD_DESC_MAX,
        _MAX_REVIEW_SKILLS,
        build_review_messages,
    )

    cards = [{"name": f"skill-{i:03d}", "description": "x" * 300}
             for i in range(100)]
    msgs = build_review_messages("任务", _units("ok"),
                                 {"units": 1, "domains": ["execute"]},
                                 skill_cards=cards)
    user = msgs[1]["content"]
    assert user.count("- skill-") == _MAX_REVIEW_SKILLS
    assert f"skill-{_MAX_REVIEW_SKILLS:03d}" not in user
    long_line = next(x for x in user.splitlines()
                     if x.startswith("- skill-000"))
    assert long_line.endswith("…")
    assert len(long_line) <= len("x" * _CARD_DESC_MAX) + 20


def test_review_and_distill_injects_existing_cards(tmp_path):
    from wuxing.skill_evolution import review_and_distill

    _mk_user_skill(tmp_path, "pytest-minimal-function",
                   "步骤一：先写失败测试。步骤二：最小实现。")

    class _CapLlm:
        def __init__(self):
            self.messages = None

        def name(self):
            return "cap"

        def chat(self, messages, tools=None):
            self.messages = messages
            return json.dumps({"efficient": False, "reason": "covered"})

    llm = _CapLlm()
    res = review_and_distill("任务", _units("ok"), "done", llm,
                             skills_dir=tmp_path)
    assert res["installed"] is False
    joined = "\n".join(m["content"] for m in llm.messages)
    assert "pytest-minimal-function" in joined
