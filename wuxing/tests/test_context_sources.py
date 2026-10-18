"""TDD：上下文来源侧车（A 期 A1）——会话级持久 + 指纹工具 + 预算读取。"""
import json

from wuxing.context_sources import (
    content_fp,
    load,
    resolve,
    save,
    sources_path,
)


def test_sources_default_all_on_and_merge(tmp_path):
    assert resolve(tmp_path) == {
        "history": True, "digest": True, "skills": True, "prefix": True,
        "budget_tokens": 0,
    }
    save(tmp_path, "units", "P-a", {"prefix": False})
    assert resolve(tmp_path, unit="P-a")["prefix"] is False
    assert resolve(tmp_path, unit="P-b")["prefix"] is True          # 其他作用域不受影响
    assert resolve(tmp_path, conversation="c.jsonl")["prefix"] is True
    save(tmp_path, "conversations", "c.jsonl", {"history": False})
    assert resolve(tmp_path, conversation="c.jsonl")["history"] is False
    # 部分键更新不覆盖其他键
    save(tmp_path, "units", "P-a", {"skills": False})
    r = resolve(tmp_path, unit="P-a")
    assert r["prefix"] is False and r["skills"] is False
    # unit 比 conversation 更具体（unit 覆盖）
    save(tmp_path, "conversations", "c.jsonl", {"skills": True})
    assert resolve(tmp_path, conversation="c.jsonl", unit="P-a")["skills"] is False


def test_sources_tolerates_missing_and_corrupt(tmp_path):
    assert load(tmp_path) == {}
    p = sources_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{corrupt", encoding="utf-8")
    assert resolve(tmp_path)["history"] is True       # 损坏 → 默认（不阻断）
    p.write_text(json.dumps({"units": {"P-a": {"prefix": "nope"}}}),
                 encoding="utf-8")
    assert resolve(tmp_path, unit="P-a")["prefix"] is True   # 非法类型 → 默认
    # 原子写：文件为合法 JSON 且含版本
    save(tmp_path, "conversations", "c.jsonl", {"digest": False})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert data["conversations"]["c.jsonl"]["digest"] is False


def test_budget_resolution_precedence(tmp_path):
    assert resolve(tmp_path, default_budget=5000)["budget_tokens"] == 5000
    save(tmp_path, "conversations", "c.jsonl", {"budget_tokens": 8000})
    assert resolve(tmp_path, conversation="c.jsonl",
                   default_budget=5000)["budget_tokens"] == 8000
    save(tmp_path, "units", "P-a", {"budget_tokens": 9000})
    assert resolve(tmp_path, conversation="c.jsonl", unit="P-a",
                   default_budget=5000)["budget_tokens"] == 9000


def test_content_fp_deterministic_and_bounded():
    assert content_fp("abc") == content_fp("abc")
    assert len(content_fp("abc")) == 12
    assert content_fp("abc") != content_fp("abd")
    assert content_fp("") == ""
    assert content_fp("  x  ") == content_fp("  x  ")   # 不 strip（确定性）


def _stub_engine(tmp_path):
    import typing

    from wuxing.engine import Engine

    class _Llm:
        usage_history: typing.ClassVar[list] = []

        def name(self):
            return "stub"

        def spec(self):
            return "stub"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 100, "output": 10,
                                       "cache_read": 0, "cache_write": 0})
            return ToolCallResult(text="完成声明：已完成", tool_calls=[])

    return Engine(workdir=tmp_path, llm=_Llm(), auto_confirm=True)


def test_runner_and_preview_honor_sources(tmp_path):
    """A1：关 history/digest/skills → 注入跳过（trace 实测 0）+ 投影同步。"""
    eng = _stub_engine(tmp_path)
    conv = tmp_path / ".wuxing" / "conversation-x.jsonl"
    sess = eng.start_session(conversation_path=conv)
    sess.send("第一轮任务")
    # 投影（全开）：history 段存在
    d0 = eng.preview_session_context(conversation_path=conv)
    assert d0["sources"]["history"] is True
    assert any(s["key"] == "history" for s in d0["segments"])
    # 关闭三项（会话级持久）
    save(tmp_path, "conversations", "conversation-x.jsonl",
         {"history": False, "digest": False, "skills": False})
    sess.send("第二轮任务")
    rows = [json.loads(x) for x in
            (tmp_path / ".wuxing" / "trace.jsonl").read_text(
                encoding="utf-8").splitlines() if x.strip()]
    started = [r for r in rows if r.get("event") == "unit_started"]
    assert started
    last = started[-1]
    assert int(last.get("history_chars") or 0) == 0
    assert int(last.get("digest_chars") or 0) == 0
    assert int(last.get("skills_chars") or 0) == 0
    assert int(last.get("system_chars") or 0) > 0     # 机制必需段不受开关影响
    # 投影同步：段消失 + sources 反映开关
    d1 = eng.preview_session_context(conversation_path=conv)
    keys = {s["key"] for s in d1["segments"]}
    assert "history" not in keys and "digest" not in keys and "skills" not in keys
    assert d1["sources"]["history"] is False
    # 恢复全开 → 段回来（不破坏后续）
    save(tmp_path, "conversations", "conversation-x.jsonl",
         {"history": True, "digest": True, "skills": True})
    d2 = eng.preview_session_context(conversation_path=conv)
    assert any(s["key"] == "history" for s in d2["segments"])


class _FakeRunner:
    """FSC 编排测试桩（同 test_loop_fsc_orchestrator 口径）。"""

    emit_event = None

    def __init__(self, sink):
        self.sink = sink
        self._messages = [{"role": "system", "content": "S"}]

    def run_unit(self, unit_id, domain_id, params, resume_session=None,
                 bypass_confirm=False, continue_from=None, cancel=None,
                 llm_candidate=0):
        from wuxing.protocols import UnitResult
        self.sink.append((unit_id, list(continue_from or [])))
        if continue_from:
            self._messages = list(continue_from) + [
                {"role": "user", "content": params["goal"]}]
        else:
            self._messages = [{"role": "system", "content": "S"},
                              {"role": "user", "content": params["goal"]}]
        return UnitResult(unit_id=unit_id, domain_id=domain_id, status="ok")


def test_prefix_off_skips_fsc_match_and_retain(tmp_path):
    """A1：unit prefix=false → 不匹配会话池（不延续/不 retain）；恢复后可延续。"""
    from wuxing.config import EngineConfig
    from wuxing.orchestrator import Orchestrator
    from wuxing.registry import DomainRegistry
    from wuxing.session_pool import SessionPool
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace

    ws = Workspace(tmp_path)
    cfg = EngineConfig()
    pool = SessionPool(retention_rounds=4)
    seen = []
    orch = Orchestrator(cfg, DomainRegistry(cfg), ws, None, [],
                        session_pool=pool,
                        trace=TraceLogger(ws.root / "trace.jsonl"))
    orch._make_runner = lambda: _FakeRunner(seen)
    orch.run([{"fragment_id": "F-1", "domain": "execute", "deps": [],
               "text": "更新 docs/a.md 内容", "deliverables": []}], "t1")
    assert seen[0][1] == [], "首轮无延续"
    # 关闭 prefix：同键也不得延续/retain
    save(tmp_path, "units", "F-2", {"prefix": False})
    orch.run([{"fragment_id": "F-2", "domain": "execute", "deps": [],
               "text": "继续完善 docs/b.md", "deliverables": []}], "t2")
    assert seen[1][1] == [], "prefix=false 不得延续"
    rows = orch.trace.load()
    assert not any(r["event"] == "session_reused" for r in rows), rows
    # 恢复开：池未被关闭期破坏 → F-3 可续
    save(tmp_path, "units", "F-2", {"prefix": True})
    orch.run([{"fragment_id": "F-3", "domain": "execute", "deps": [],
               "text": "继续 docs/c.md", "deliverables": []}], "t3")
    assert seen[2][1], "恢复后必须可延续（池未被破坏）"
