"""TDD · M1-1（数据驱动重定向）：verify 依赖缺失 → 机制自动兜底「结论：不通过」。

数据（v4-flash n=5）：失败单元 = execute「探索不写」+ verify「read 24 次无结论」——
verify 面对缺失产物（读 not found 循环）时模型不输出结论。机制裁决：
验收对象缺失 = 不通过（确定性判定，无需模型自觉）；任务状态传播（L0-4）。
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


class _ReadLoopLlm:
    """verify 域：反复读不存在的文件（模拟 n=5 数据中的 read 循环）+ 无结论。"""

    def __init__(self):
        self.calls = 0

    def name(self):
        return "read-loop"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.calls += 1
        return ToolCallResult(text="", tool_calls=[
            {"name": "read_dependency",
             "arguments": {"path": "missing-result.md"}}])


def test_verify_missing_evidence_auto_unpassed():
    """verify 依赖产物缺失（不存在）→ 机制兜底：单元 ok + verdict_fail（不通过）。"""
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=5)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, _ReadLoopLlm(), BUILTIN_TOOLS(ws))
    res = r.run_unit("V-1", "verify", {"goal": "验收", "paths": "missing-result.md",
                                       "result": ""})
    assert res.status == "ok", \
        "依赖缺失必须机制兜底（验收对象缺失=不通过——非模型自觉）"
    assert getattr(res, "verdict_fail", False) is True, "缺失=不通过（verdict_fail 传播）"


def test_verify_existing_evidence_requires_model_verdict():
    """对照：产物存在 → 机制不兜底（模型必须给出结论——质量域语义保持）。"""
    class _NoVerdict:
        def name(self):
            return "no-verdict"

        def chat(self, messages, tools=None):
            return "我读了产物但不想给结论"  # 无「结论：」marker

    cfg = EngineConfig(max_loop_rounds=3, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / "result.md").write_text("产物内容", encoding="utf-8")
    r = Runner(cfg, DomainRegistry(cfg), ws, _NoVerdict(), BUILTIN_TOOLS(ws))
    res = r.run_unit("V-1", "verify", {"goal": "验收", "paths": "result.md",
                                       "result": ""})
    assert res.status == "failed", "产物存在但无结论 → 仍失败（不替代模型判断）"


def test_task_done_when_verify_passes_despite_unit_failures():
    """验收语义：verify 通过 + 部分单元失败 → 任务 done（验收权威——降级记录在报告）。"""
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    units = [
        UnitResult(unit_id="P", domain_id="plan", status="ok"),
        UnitResult(unit_id="E", domain_id="execute", status="failed",
                   error="单元失败（降级）"),
        UnitResult(unit_id="V", domain_id="verify", status="ok",
                   verdict_fail=False),
    ]
    assert Engine._task_status(units) == "done", \
        "verify 通过=任务完成（单元失败可降级——验收权威）"


def test_task_failed_when_verify_unpassed():
    """验收语义：verify 结论不通过（含自动兜底）→ 任务 failed（明确失败非 partial）。"""
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    units = [
        UnitResult(unit_id="P", domain_id="plan", status="ok"),
        UnitResult(unit_id="E", domain_id="execute", status="ok"),
        UnitResult(unit_id="V", domain_id="verify", status="ok",
                   verdict_fail=True),
    ]
    assert Engine._task_status(units) == "failed", \
        "验收不通过=未完成（明确失败——非降级）"


def test_no_verify_fallback_partial():
    """无 verify 域（小任务形状化无验证碎片）→ 回落：全 ok=done；有失败=partial。"""
    from wuxing.engine import Engine
    from wuxing.protocols import UnitResult
    assert Engine._task_status([
        UnitResult(unit_id="E", domain_id="execute", status="failed")]) == "failed"
    assert Engine._task_status([
        UnitResult(unit_id="P", domain_id="plan", status="ok"),
        UnitResult(unit_id="E", domain_id="execute", status="failed")]) == "partial"
    assert Engine._task_status([
        UnitResult(unit_id="E", domain_id="execute", status="ok")]) == "done"


def test_verify_budget_capped():
    """verify 域预算基线减配（3）+ 动态轮数语义（真测裁决 W2·2026-09-26）：
    基线到达后进入收敛模式（机械评分+自评），停滞 2 轮才失败——不再硬停在 3。
    """
    class _Loop:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "loop"

        def chat(self, messages, tools=None):
            self.calls += 1
            return "检查中还是不给结论"

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=5)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = _Loop()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    res = r.run_unit("V-1", "verify", {"goal": "验收", "paths": "r.md",
                                        "result": "有产物"})
    assert res.status == "failed"
    # 基线 3 + 停滞窗口 2 = 至多 5（停滞即停，不允许烧到安全上限）
    assert llm.calls <= 5, f"verify 域基线 3+停滞窗口（得 {llm.calls}）"
    assert "stalled" in (res.error or "") or "safety cap" in (res.error or "")


class _PromptProbeLlm:
    """捕获 system 文本——验证预算声明与实际一致。"""

    def __init__(self, text, tool_calls):
        self.usage_history = []
        self.call_count = 0
        self._text = text
        self._calls = tool_calls
        self.system_text = ""

    def name(self):
        return "promptprobe"

    def spec(self):
        return "promptprobe"

    def supports_native_tools(self):
        return False

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.usage_history.append({"input": 0, "output": 0,
                                   "cache_read": 0, "cache_write": 0})
        self.system_text = next((m["content"] for m in messages
                                 if m.get("role") == "system"), "")
        self.call_count += 1
        return ToolCallResult(text=self._text, tool_calls=self._calls)


def test_verify_system_budget_matches_actual():
    """B2：verify 域 system 声明的轮数预算必须与实际执行预算一致
    （此前声明 cfg 5 轮、实际 max(5,3)=3——模型被误导规划）。"""
    import pathlib
    import tempfile

    from wuxing.config import EngineConfig
    from wuxing.protocols import Artifact
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="r.md", kind="result",
                               producer_unit="U0"), "内容")
    llm = _PromptProbeLlm("结论：通过", [{"name": "read_dependency",
                                        "arguments": {"path": "r.md"}}])
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    r.run_unit("V-1", "verify", {"result": "内容", "paths": "r.md"})
    assert "3 轮" in llm.system_text or "最多 3 轮" in llm.system_text,         f"verify 域 system 必须声明实际预算（3）：{llm.system_text[:200]}"
    assert "最多 5 轮" not in llm.system_text,         f"verify 域不得声明 5 轮（实际 3）：{llm.system_text[:200]}"


def test_verify_prompt_contract_requires_explicit_verdict():
    """用户裁决（2026-09-07）：verify 结论缺口 → prompt 强化（不扩机制）。

    契约断言：verify 域 prompt 必须显式要求
      ①最后一句必须是『结论：通过』或『结论：不通过』（硬性输出契约）
      ②部分缺失/不满足 → 必须给出『结论：不通过』（不得省略结论）
      ③产物不存在 → 『结论：不通过（产物缺失）』
    背景：n=9 数据 failed 4/9 主因=「部分存在+模型不给结论」——不在 M1-1
    自动兜底范围（兜底只救全部缺失）；强化 prompt 让模型显式给结论。
    """
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    text = dom.quality_notes + "\n" + dom.prompt_skeleton
    # ① 硬性输出契约：最后一句必须是结论
    assert "最后一句" in text and "结论：通过" in text and "结论：不通过" in text, \
        "verify prompt 必须显式规定结论输出格式（最后一句）"
    # ② 部分缺失/不满足 → 必须给不通过（不得省略结论）
    assert ("不满足" in text or "部分缺失" in text) and "不通过" in text, \
        "部分存在/不满足场景必须显式要求『结论：不通过』"
    # ③ 产物不存在 → 不通过（产物缺失）
    assert "产物缺失" in text or "不存在" in text, \
        "产物不存在场景必须显式给出『结论：不通过（产物缺失）』"


def test_verify_prompt_contract_reaches_runner_prompt():
    """集成：Runner 组装的 verify prompt（模型实际可见）必须含强化契约段。"""
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    class CapturePrompt:
        def __init__(self):
            self.usage_history = []
            self.call_count = 0
            self.prompts = []

        def name(self):
            return "cap"

        def spec(self):
            return "cap"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 0, "output": 0,
                                       "cache_read": 0, "cache_write": 0})
            self.prompts = list(messages)
            return ToolCallResult(text="结论：通过", tool_calls=[
                {"name": "read_dependency", "arguments": {"path": "r.md"}}])

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / "r.md").write_text("内容", encoding="utf-8")
    llm = CapturePrompt()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    r.run_unit("V-1", "verify", {"goal": "验收", "paths": "r.md", "result": ""})
    prompt = "\n".join(m["content"] for m in llm.prompts
                       if m.get("role") == "user")
    assert "最后一句" in prompt and "结论：不通过" in prompt, \
        "模型实际收到的 verify prompt 必须含强化契约段"


def test_verify_prompt_reply_text_conclusion_required():
    """V4 样例驱动（meg-M15 归因）：模型写结论**文件**但回复文本无结论 → 机制 failed
    ——强化补充：结论必须在回复文本中（写入文件不作为判定依据）。"""
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    text = dom.quality_notes + "\n" + dom.prompt_skeleton
    assert "回复文本" in text and "判定依据" in text, \
        "verify prompt 必须明确：写入文件的结论不作为判定依据（结论在回复文本）"


def test_verify_prompt_forbids_read_loop():
    """V5（全量归因驱动）：verify 失败=模型 3 轮全在读文件（每轮 4-8 个）从未给结论
    ——prompt 必须明确：注入内容即完整验收对象，优先直接验收；无论是否读文件，
    最后一句必须是结论。"""
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    text = dom.quality_notes + "\n" + dom.prompt_skeleton
    assert "直接验收" in text or "不要读取" in text or "优先直接" in text, \
        "verify prompt 必须抑制 read 循环（注入内容即验收对象）"
    assert "无论" in text or "即使" in text, \
        "verify prompt 必须强调无论读不读文件都要给结论"


def test_execute_prompt_states_write_means_done():
    """V6（全量归因驱动）：execute 失败=读多写少预算耗尽——prompt 必须告知机制事实
    「写出产物即视为完成——第一轮就写产物」（v4-flash 实测：写物证=完成充分证据）。"""
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    for did in ("execute", "plan"):
        dom = DEFAULT_DOMAINS[did]
        text = dom.quality_notes + "\n" + dom.prompt_skeleton
        assert "写出产物" in text or "第一轮" in text, \
            f"{did} prompt 必须告知「写产物=完成」机制事实"


def test_execute_prompt_states_target_artifact_semantics():
    """#1（报告 #6：5 例「交付计划而非产物」）：execute 语义澄清——
    目标产物＝成品本身（代码/文档/数据；计划与说明属 plan 域）；
    只用澄清措辞不用禁令；收口压力（第一轮）保留不回归。"""
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    text = DEFAULT_DOMAINS["execute"].quality_notes
    assert "目标产物" in text
    assert "不是" in text and "计划" in text
    assert "第一轮" in text


def test_verify_prompt_contract_fallback_summary_requires_reading_workdir():
    """真测缺陷（THEROAD2）：注入为「回退摘要」时，verify 必须转读工作区真实交付物。

    现场：execute 纯工具轮 → REAL-13 回退摘要成为唯一注入；verify 按
    「待验产物内容即完整验收对象，不要反复读文件」判定 → 判「不可核验 → 不通过」，
    而真实交付物（代码/测试）就在工作区且全绿（误判链：T-2 失败 → 下游全阻）。
    """
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    text = dom.quality_notes + "\n" + dom.prompt_skeleton
    # 回退摘要标记 + 转读工作区指令
    assert "回退摘要" in text, "verify prompt 必须标识回退摘要场景"
    assert "交付摘要" in text, "必须引用回退摘要的硬标记（模型无收口文本——自动生成）"
    assert "read_file" in text or "读取工作区" in text, \
        "回退摘要场景必须要求读取工作区真实交付物"
    # 既有输出契约不回归
    assert "结论：不通过" in text and "最后一句" in text


def test_verify_prompt_contract_fallback_summary_reaches_runner_prompt():
    """集成：Runner 组装的 verify prompt 必须含回退摘要转读指令。"""
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace

    class CapturePrompt:
        def __init__(self):
            self.usage_history = []
            self.prompts = []

        def name(self):
            return "cap2"

        def spec(self):
            return "cap2"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 0, "output": 0,
                                       "cache_read": 0, "cache_write": 0})
            self.prompts = list(messages)
            return ToolCallResult(text="结论：通过", tool_calls=[
                {"name": "read_dependency", "arguments": {"path": "r.md"}}])

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / "r.md").write_text("内容", encoding="utf-8")
    llm = CapturePrompt()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws))
    r.run_unit("V-1", "verify", {"goal": "验收", "paths": "r.md", "result": ""})
    prompt = "\n".join(m["content"] for m in llm.prompts
                       if m.get("role") == "user")
    assert "回退摘要" in prompt and ("read_file" in prompt or "读取工作区" in prompt), \
        "模型实际收到的 verify prompt 必须含回退摘要转读指令"


def test_verify_prompt_contract_requires_workspace_index_reading():
    """P0-1 D（评估方向）：verify 提示词须规定——提供交付物索引时至少读相关真实文件。"""
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    text = dom.quality_notes + "\n" + dom.prompt_skeleton
    assert "工作区交付物索引" in text
    assert "read_file" in text


def test_structured_verdict_parser_items_rule():
    """P0-1b A：结构化条目解析——任一条目不通过→不通过；仅存疑→通过；无条目→None。"""
    from wuxing.contracts import _structured_verdict
    assert _structured_verdict("#1：通过｜证据：a\n#2：不通过｜证据：b") == "不通过"
    assert _structured_verdict("- #1: 通过 | 证据: a\n- #2：存疑｜证据：b") == "通过"
    assert _structured_verdict("结论：不通过") is None
    # 行首锚定：正文引用（非行首）不参与裁决（REAL-9 纪律同源）
    assert _structured_verdict("前文提到 #1：不通过 字样\n结论：通过") is None


def test_verify_structured_items_extra_findings_not_verdict_fail():
    """P0-1b A：验收项全通过 + 额外发现（范围外缺陷）→ verdict_fail=False（不阻断 DAG）。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    out = ("【逐条核查】\n#1：通过｜证据：a\n#2：通过｜证据：b\n"
           "【额外发现（不影响本次验收）】\n"
           "- parse_amount 对超大金额未捕获异常（范围外，建议修复）\n"
           "结论：通过")
    res = contract_check(dom, out, "V-1", [], ["[tool] read_file: code"],
                         write_ok=True, read_ok=True)
    assert res is not None and res.verdict_fail is False


def test_verify_structured_items_fail_blocks():
    """P0-1b A：存在验收项不通过 → verdict_fail=True（阻断语义保持）。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    out = "#1：不通过｜证据：缺失\n#2：通过｜证据：b\n结论：不通过"
    res = contract_check(dom, out, "V-1", [], ["[tool] read_file: code"],
                         write_ok=True, read_ok=True)
    assert res is not None and res.verdict_fail is True


def test_verify_structured_items_override_inconsistent_conclusion():
    """P0-1b A：条目与结论不一致时以条目裁决（机械化优先）。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    out1 = "#1：通过｜证据：a\n结论：不通过"
    r1 = contract_check(dom, out1, "V-1", [], ["[tool] read_file: x"],
                        write_ok=True, read_ok=True)
    assert r1 is not None and r1.verdict_fail is False
    out2 = "#1：不通过｜证据：a\n结论：通过"
    r2 = contract_check(dom, out2, "V-1", [], ["[tool] read_file: x"],
                        write_ok=True, read_ok=True)
    assert r2 is not None and r2.verdict_fail is True


def test_verify_prompt_contract_layered_items_and_advisories():
    """P0-1b A：提示词契约——结构化条目 + 存疑/额外发现分层（不据此判不通过）。"""
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    dom = DEFAULT_DOMAINS["verify"]
    text = dom.quality_notes + "\n" + dom.prompt_skeleton
    assert "存疑" in text and "额外发现" in text and "证据" in text
