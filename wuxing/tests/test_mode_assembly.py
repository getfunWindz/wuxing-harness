"""TDD（双模式批 1 · Task 3）：模式感知装配——注入面/工具面/打扰面/thin 提示词。

依据：docs/plans/2026-09-23-wuxing-dual-mode-batch1.md Task 3 + 设计 §4。
stub 说明：supports_native_tools=True 使工具 schema 真进入 chat（工具面可断言，
非空集断言——避免产物面空转）。
"""
import json
import typing


class _RecLlm:
    """记录型 stub：捕获每次 chat 的 messages 与 tools。"""
    usage_history: typing.ClassVar[list] = []

    def __init__(self):
        self.messages_seen: list[list[dict]] = []
        self.tools_seen: list[list[str]] = []

    def name(self):
        return "rec"

    def spec(self):
        return "rec"

    def supports_native_tools(self):
        return True  # tools 进 chat → 工具面可断言

    def chat(self, messages, tools=None):
        self.messages_seen.append([dict(m) for m in messages])
        self.tools_seen.append([t["function"]["name"] for t in (tools or [])])
        self.usage_history.append({"input": 100, "output": 10,
                                   "cache_read": 0, "cache_write": 0})
        from wuxing.llm.tool_results import ToolCallResult
        return ToolCallResult(text="完成声明：已完成", tool_calls=[])


def _seed_shared(eng):
    """注入一条已完成碎片记录——共享段开关可断言（否则首碎片为空=断言空转）。"""
    class _R:
        unit_id = "F-0000"
        domain_id = "plan"
        status = "ok"
        logs: typing.ClassVar[list] = []
        deliverables: typing.ClassVar[list] = []
        artifacts: typing.ClassVar[list] = []

    eng.shared.record(_R(), "F-0000")


def _joined(llm, idx=0):
    return "\n".join(str(m.get("content", "")) for m in llm.messages_seen[idx])


def test_pure_mode_assembly(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    llm = _RecLlm()
    eng = Engine(workdir=tmp_path, llm=llm, auto_confirm=True,
                 cfg=EngineConfig(mode_default="minimal-pure"))
    _seed_shared(eng)
    eng.run_task("简单任务")
    joined = _joined(llm)
    assert "可用技能：" not in joined                    # 技能索引未注入
    assert "[同任务已完成碎片的经验]" not in joined       # 共享经验未注入
    names = set(llm.tools_seen[0])
    assert names and names <= {"bash", "read_file", "write_file",
                               "write_artifact", "read_dependency"}
    assert "delegate" not in names and "load_skill" not in names
    # trace 证据：pure 全程 skills_chars=0（装配侧同步）
    rows = [json.loads(x) for x in (tmp_path / ".wuxing" / "trace.jsonl")
            .read_text(encoding="utf-8").splitlines() if x.strip()]
    started = [r for r in rows if r.get("event") == "unit_started"]
    assert started
    assert all(int(r.get("skills_chars") or 0) == 0 for r in started)


def test_standard_mode_keeps_skills_and_shared(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    llm = _RecLlm()
    eng = Engine(workdir=tmp_path, llm=llm, auto_confirm=True,
                 cfg=EngineConfig(mode_default="minimal-standard"))
    _seed_shared(eng)
    eng.run_task("简单任务")
    joined = _joined(llm)
    assert "可用技能：" in joined                        # 内置 find-skill 索引在场
    assert "[同任务已完成碎片的经验]" in joined           # 共享经验保留
    names = set(llm.tools_seen[0])
    assert "delegate" in names and "load_skill" in names


def test_minimal_mode_disables_heartbeat(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    llm = _RecLlm()
    eng = Engine(workdir=tmp_path, llm=llm, auto_confirm=True,
                 cfg=EngineConfig(mode_default="minimal-standard",
                                  progress_heartbeat_enabled=True))
    eng.run_task("简单任务")
    assert "进度心跳约定" not in _joined(llm)   # 模式级让位（显式配置不生效）
    # 非极简模式保留心跳（机制随模式走——批 1 更名后 theroad 按现状装配）
    llm2 = _RecLlm()
    eng2 = Engine(workdir=tmp_path / "wf", llm=llm2, auto_confirm=True,
                  cfg=EngineConfig(mode_default="theroad",
                                   progress_heartbeat_enabled=True))
    eng2.run_task("简单任务")
    assert "进度心跳约定" in _joined(llm2)


def test_session_mode_sidecar_overrides_default(tmp_path):
    """会话级 sidecar 覆盖全局默认（设计 §3.1——缓存前缀纪律的地基）。"""
    from wuxing.config import EngineConfig
    from wuxing.conversation import ConversationState
    from wuxing.engine import Engine
    from wuxing.session_modes import save
    llm = _RecLlm()
    eng = Engine(workdir=tmp_path, llm=llm, auto_confirm=True,
                 cfg=EngineConfig(mode_default="minimal-standard"))
    conv = ConversationState(tmp_path / ".wuxing" / "conversation-y.jsonl")
    save(tmp_path, "conversation-y.jsonl", "minimal", "pure")
    eng.run_task("简单任务", conversation=conv)
    assert "可用技能：" not in _joined(llm)


def test_thin_prompt_keeps_contract_phrases():
    """thin 只删装饰：契约短语必须全部在场（计划 Task 3 断言清单）。"""
    from wuxing.prompt_builder import build_system_text

    class _Tool:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

        def description(self):
            return f"{self._name} 描述"

    class _Domain:
        title = "执行域"
        domain_id = "execute"
        quality_notes = "质量注记-契约"

    whitelist = [_Tool("bash"), _Tool("write_file")]
    full = build_system_text(_Domain, whitelist, True, 5)
    thin = build_system_text(_Domain, whitelist, True, 5, thin=True)
    for phrase in ("安全声明", "完成声明", "write_artifact 或 write_file",
                   "轮思考", "反叙述约束", "质量注记-契约", "- bash",
                   "- write_file"):
        assert phrase in thin, phrase
    assert len(thin) < len(full)


def test_prompt_declares_internal_data_discipline():
    """E0-2/A3：系统提示告知内部数据面（.wuxing 等）——减少模型空耗重试。"""
    from wuxing.prompt_builder import build_system_text

    class _Tool:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

        def description(self):
            return f"{self._name} 描述"

    class _Domain:
        title = "执行域"
        domain_id = "execute"
        quality_notes = "质量注记"

    for thin in (False, True):
        text = build_system_text(_Domain, [_Tool("bash")], True, 5, thin=thin)
        assert ".wuxing" in text, f"thin={thin} 必须告知内部数据面"
        assert "内部数据" in text and "不要尝试读取" in text, f"thin={thin}"


def test_prompt_allows_domain_contract_blocks():
    """真测 REAL-7：基础输出约束不得压制域契约结构块。

    T3 实况：设计域模型连续 3 轮只写设计文档、不给【决策】/【票据】块——
    基础提示词「只允许两种输出：工具/完成声明」与域契约块冲突。
    """
    from wuxing.domains.defaults import DESIGN_DOMAIN
    from wuxing.prompt_builder import build_system_text

    class _Tool:
        def __init__(self, name):
            self._name = name

        def name(self):
            return self._name

        def description(self):
            return f"{self._name} 描述"

    for thin in (False, True):
        text = build_system_text(DESIGN_DOMAIN, [_Tool("bash")], True, 5,
                                 thin=thin)
        assert "域契约" in text, f"thin={thin} 必须允许域契约块"
        assert "【决策】" in text and "【票据】" in text


def test_design_domain_prompt_marks_decision_channel():
    """真测 REAL-6：运行期决策只走受控块；write_map 自由文本不得用于决策。"""
    from wuxing.domains.defaults import DESIGN_DOMAIN

    notes = DESIGN_DOMAIN.quality_notes
    assert "【决策】" in notes and "write_map" in notes
    assert "只走受控块" in notes
