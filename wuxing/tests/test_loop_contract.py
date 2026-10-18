"""TDD：P0 T3 契约硬化（S5——验收需物证而非关键词出现即通过）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.llm.tool_results import ToolCallResult
from wuxing.protocols import Artifact
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


class TalkOnlyLlm:
    """只说不做：输出含 marker，但从不调用工具。"""

    def __init__(self, text: str):
        self._text = text
        self.calls = 0

    def name(self):
        return "talkonly"

    def chat(self, messages, tools=None):
        self.calls += 1
        return self._text


def _runner(domain, llm, max_budget=3):
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=max_budget)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws)), ws


def test_execute_marker_without_write_evidence_fails():
    """S5 复现：『执行完成』文本出现即通过——无写工具物证必须失败。"""
    llm = TalkOnlyLlm("执行完成：已完成，产物：result.md")
    r, _ = _runner("execute", llm)
    res = r.run_unit("U-1", "execute", {"goal": "实现一个登录页"})
    assert res.status == "failed", \
        f"无写物证的『执行完成』不得判 ok（status={res.status}）"


def test_verify_marker_without_read_evidence_fails():
    """S5 复现：verify 输出『结论：通过』但从未读取产物 → 不得判 ok。"""
    llm = TalkOnlyLlm("评审结论：通过。理由：产物满足验收标准")
    r, _ = _runner("verify", llm)
    res = r.run_unit("U-1", "verify", {"result": "待验产物"})
    assert res.status == "failed", \
        f"无读物证的『结论：通过』不得判 ok（status={res.status}）"


def test_execute_with_write_evidence_converges():
    """正向往：execute 带写工具成功物证 + marker → ok（防误杀）。"""
    class WriteThenDone:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "writethen"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="我先执行任务", tool_calls=[
                    {"name": "write_artifact",
                     "arguments": {"path": "out.md", "kind": "result",
                                   "content": "登录页已实现: <h1>login</h1>"}}])
            return "执行完成：登录页已实现，产物 out.md"

    r, _ = _runner("execute", WriteThenDone(), max_budget=4)
    res = r.run_unit("U-1", "execute", {"goal": "实现一个登录页"})
    assert res.status == "ok", f"有写物证应收敛：{res.error}"


class JsonOnlyLlm:
    """只输出 JSON（不调用工具）——A1 复现：JSON schema 路径绕过物证闸。"""

    def __init__(self, text: str):
        self._text = text
        self.calls = 0

    def name(self):
        return "jsononly"

    def chat(self, messages, tools=None):
        self.calls += 1
        return self._text


def test_execute_json_without_write_evidence_fails():
    """A1 复现：execute 输出合法 JSON（{result}）但无写物证——不得判 ok（物证绕过）。"""
    llm = JsonOnlyLlm('{"result": "登录页已实现"}')
    r, _ = _runner("execute", llm)
    res = r.run_unit("U-1", "execute", {"goal": "实现一个登录页"})
    assert res.status == "failed", \
        f"JSON 输出无写物证不得判 ok（status={res.status}）——物证闸被 schema 路径绕过"


def test_verify_json_without_read_evidence_fails():
    """A1 复现：verify 输出 JSON 结论但从未读产物——不得判通过（读物证绕过）。"""
    llm = JsonOnlyLlm('{"verdict": "通过", "结论": "通过"}')
    r, _ = _runner("verify", llm)
    res = r.run_unit("U-1", "verify", {"result": "待验产物"})
    assert res.status == "failed", \
        f"JSON 结论无读物证不得判 ok（status={res.status}）——读物证闸被 schema 路径绕过"


def test_execute_json_with_write_evidence_converges():
    """正向往（防误杀）：JSON 输出 + 写物证 → ok。"""
    class JsonThenWrite:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "jsonwrite"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="写出", tool_calls=[
                    {"name": "write_artifact",
                     "arguments": {"path": "out.json.md", "kind": "result",
                                   "content": "{\"result\": \"登录页已实现\"}"}}])
            return '{"result": "登录页已实现"}'

    r, _ = _runner("execute", JsonThenWrite(), max_budget=4)
    res = r.run_unit("U-1", "execute", {"goal": "实现一个登录页"})
    assert res.status == "ok", f"有写物证 + JSON 应收敛：{res.error}"


def test_verify_json_with_read_evidence_converges():
    """正向往（防误杀）：verify JSON 结论 + 读物证 → ok 且 verdict_fail 判定正确。"""
    class JsonThenRead:
        def chat(self, messages, tools=None):
            return ToolCallResult(text='{"verdict": "不通过", "结论": "不通过"}',
                                  tool_calls=[
                                      {"name": "read_dependency",
                                       "arguments": {"path": "result.md"}}])

        def name(self):
            return "jsonread"

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="result.md", kind="result",
                               producer_unit="F-exec"), "登录页已实现")
    r = Runner(cfg, DomainRegistry(cfg), ws, JsonThenRead(), load_tools(ws))
    res = r.run_unit("U-1", "verify", {"result": "result.md 内容"})
    assert res.status == "ok", f"有读物证 + JSON 应收敛：{res.error}"
    # 结论「不通过」仍须标记 verdict_fail（验收语义不因 JSON 形态丢失）
    assert getattr(res, "verdict_fail", False) is True


def test_verify_with_read_evidence_converges():
    """正向往：verify 带读工具调用（检查行为）+ marker → ok。"""
    class ReadThenDone:
        def chat(self, messages, tools=None):
            return ToolCallResult(text="评审结论：通过。产物满足验收标准", tool_calls=[
                {"name": "read_dependency", "arguments": {"path": "result.md"}}])

        def name(self):
            return "readthen"

    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=3)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="result.md", kind="result",
                               producer_unit="F-exec"), "登录页已实现")
    r = Runner(cfg, DomainRegistry(cfg), ws, ReadThenDone(), load_tools(ws))
    res = r.run_unit("U-1", "verify", {"result": "result.md 内容"})
    assert res.status == "ok", f"有读物证应收敛：{res.error}"


def test_verify_conclusion_in_file_judged_unpassed():
    """B1（真实测试 F3 证据链）：verify 写了验收结论文件且含「结论：不通过」→
    按文件内容判定（单元 ok + verdict_fail）——v4-flash 工具轮无文本，
    结论在文件里（此前只能预算耗尽 failed）。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    from wuxing.protocols import Artifact

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="verify/结论.md", kind="verdict",
                               producer_unit="V-1"),
                      "## 验收报告\n检查了产物……\n**验收结论：不通过**（缺证据）")
    dom = DEFAULT_DOMAINS["verify"]
    res = contract_check(dom, "检查了一下", "V-1", [], [], write_ok=True,
                         read_ok=True, ws=ws, deliverables=["verify/结论.md"])
    assert res is not None, "写了结论文件必须能判定（不再预算耗尽）"
    assert res.status == "ok"
    assert res.verdict_fail is True


def test_verify_conclusion_in_file_judged_passed():
    """对照：文件含「结论：通过」→ ok + vf=False。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    from wuxing.protocols import Artifact

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="v.md", kind="verdict", producer_unit="V-1"),
                      "逐条核查：全部满足。\n结论：通过")
    dom = DEFAULT_DOMAINS["verify"]
    res = contract_check(dom, "检查", "V-1", [], [], write_ok=True,
                         read_ok=True, ws=ws, deliverables=["v.md"])
    assert res is not None and res.verdict_fail is False


def test_verify_no_conclusion_in_file_still_fails():
    """对照：文件无「结论」字样 → 保持未通过（机制不放水）。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    from wuxing.protocols import Artifact

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="v.md", kind="verdict", producer_unit="V-1"),
                      "我看了一圈，还行吧")
    dom = DEFAULT_DOMAINS["verify"]
    res = contract_check(dom, "检查", "V-1", [], [], write_ok=True,
                         read_ok=True, ws=ws, deliverables=["v.md"])
    assert res is None, "无结论不得判定（不放水）"


def _runner_b1(tmp):
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry

    class WriteOnlyLlm:
        """B1 场景：工具轮无文本（v4-flash 特性）——只写结论文件+读产物。"""

        def __init__(self):
            self.usage_history = []
            self.call_count = 0

        def name(self):
            return "writeonly"

        def spec(self):
            return "writeonly"

        def supports_native_tools(self):
            return False

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.usage_history.append({"input": 0, "output": 0,
                                       "cache_read": 0, "cache_write": 0})
            return ToolCallResult(text="", tool_calls=[
                {"name": "read_dependency", "arguments": {"path": "r.md"}},
                {"name": "write_artifact", "arguments": {
                    "path": "verify/结论.md", "kind": "verdict",
                    "content": "逐条核查：证据不足。\n**验收结论：不通过**"}}])

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tmp))
    (ws.root / "r.md").write_text("产物内容", encoding="utf-8")
    r = Runner(cfg, DomainRegistry(cfg), ws, WriteOnlyLlm(), load_tools(ws))
    return r


def test_runner_verify_conclusion_file_converges():
    """B1 集成（真实测试 F3）：verify 工具轮无文本、结论写文件 → 单元收敛
    （不再预算耗尽 failed）+ verdict_fail 正确传播。"""
    import tempfile
    r = _runner_b1(tempfile.mkdtemp())
    res = r.run_unit("V-1", "verify",
                     {"result": "内容", "paths": "r.md", "task": "t"})
    assert res.status == "ok", f"写了结论文件必须收敛：{res.error}"
    assert getattr(res, "verdict_fail", False) is True


def test_verify_conclusion_file_exempts_read_evidence():
    """B1 修复（novice-2 根因）：只写验收文件（未读）——文件含结论 → 收敛。
    验收结论文件的产出本身=验收行为证据（read 物证豁免——否则只写不读的
    模型永远被 require_read 拦回）。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    from wuxing.protocols import Artifact

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="v.md", kind="verdict", producer_unit="V-1"),
                      "检查完成。\n结论：通过")
    dom = DEFAULT_DOMAINS["verify"]
    res = contract_check(dom, "", "V-1", [], [], write_ok=True,
                         read_ok=False, ws=ws, deliverables=["v.md"])
    assert res is not None, "只写验收文件（无 read）也必须收敛（B1 豁免 read 物证）"
    assert res.verdict_fail is False
    # 对照：无结论文件时 read 物证仍必需（机制不放水）
    res2 = contract_check(dom, "结论：不通过", "V-2", [], [], write_ok=True,
                          read_ok=False, ws=ws, deliverables=[])
    assert res2 is None, "无文件路径时 require_read 仍生效"


def test_user_domain_acceptance_file_judged():
    """S4（novice-4 剩余失败）：user 域写验收文件（含 markers）→ 收敛
    （B1 同构——语义域文件判定；user 域无 vf 概念）。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    from wuxing.protocols import Artifact

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="user/验收.md", kind="acceptance",
                               producer_unit="U-1"),
                      "从用户视角：验收标准如下……体验要求……")
    dom = DEFAULT_DOMAINS["user"]
    res = contract_check(dom, "", "U-1", [], [], write_ok=True,
                         read_ok=False, ws=ws, deliverables=["user/验收.md"])
    assert res is not None, "user 域写了含 markers 的文件必须收敛（S4）"
    assert res.status == "ok"
    # 对照：文件无 markers → 不放水
    ws2 = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws2.write_artifact(Artifact(path="u.md", kind="acceptance",
                                producer_unit="U-2"), "随便写点东西")
    res2 = contract_check(dom, "", "U-2", [], [], write_ok=True,
                          read_ok=False, ws=ws2, deliverables=["u.md"])
    assert res2 is None, "无 markers 不得判定"


def test_verify_file_prose_not_conclusion_does_not_fail():
    """真测 REAL-10：文件里非结论的「不通过」字样（如「不构成不通过」）不得误判。

    实况（T4 · T-3）：验收文件唯一一处「不通过」出现在小节标题
    「备注 / 观察（不构成不通过）」，而真正结论是「结论：通过」——
    子串判定把 T-3 误判失败（票据 failed，人肉复测 17 passed 证明实现无误）。
    """
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS
    from wuxing.protocols import Artifact

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    ws.write_artifact(Artifact(path="v.md", kind="verdict", producer_unit="V-1"),
                      "## 备注 / 观察（不构成不通过）\n逐条核查全部满足。\n结论：通过")
    dom = DEFAULT_DOMAINS["verify"]
    res = contract_check(dom, "检查", "V-1", [], [], write_ok=True,
                         read_ok=True, ws=ws, deliverables=["v.md"])
    assert res is not None
    assert res.verdict_fail is False, "非结论性「不通过」字样不得误判"


def test_verify_reply_prose_not_conclusion_does_not_fail():
    """真测 REAL-10：回复文本里「未发现不通过项。结论：通过」不得误判。"""
    from wuxing.contracts import contract_check
    from wuxing.domains.defaults import DEFAULT_DOMAINS

    dom = DEFAULT_DOMAINS["verify"]
    res = contract_check(dom, "逐条核查：未发现不通过项。结论：通过", "V-1",
                         [], [], write_ok=True, read_ok=True)
    assert res is not None
    assert res.verdict_fail is False


def test_empty_out_result_artifact_gets_fallback_content():
    """真测 REAL-13(a)：纯工具轮无文本 → result 产物不得为空（防 verify 饥饿）。

    实况（W4 复跑）：F-T2 执行末轮只调工具（pytest 17 passed）→ 自动写的
    F-T2-result.md 为空 → verify 注入只有路径无正文 → 判「产物缺失」→
    依赖链阻塞。修复：空文本回退「交付摘要」。
    """
    class ToolOnlyLlm:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "toolonly"

        def chat(self, messages, tools=None):
            self.calls += 1
            return ToolCallResult(text="", tool_calls=[
                {"name": "write_artifact",
                 "arguments": {"path": "x.md", "kind": "result",
                               "content": "实现内容"}}])

    cfg = EngineConfig()
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    r = Runner(cfg, DomainRegistry(cfg), ws, ToolOnlyLlm(), load_tools(ws))
    res = r.run_unit("U-1", "execute", {"goal": "实现 x"})
    assert res.status == "ok"
    content = ws.read("U-1-result.md") or ""
    assert content.strip(), "空文本收口必须回退交付摘要（不得空产物）"
    assert "x.md" in content, "摘要须含交付物清单"


# ---- 真测缺陷（RT5）：显式要求「运行 pytest 确认通过」的碎片需要运行物证 ----

def test_requires_test_run_heuristic():
    """要求识别：显式含 pytest + 运行动词 → 需运行物证；仅提及 pytest 不算。"""
    from wuxing.runner import _requires_test_run
    assert _requires_test_run("创建 x.py 并运行 pytest 确认通过")
    assert _requires_test_run("编写测试后执行 pytest")
    assert not _requires_test_run("写 test_x.py 用 pytest 覆盖空文件场景")
    assert not _requires_test_run("实现 x.py 并写入结果")


def test_pytest_evidence_parse():
    """物证解析：通过输出接受；失败/错误输出拒绝。"""
    from wuxing.runner import _pytest_passed
    assert _pytest_passed("9 passed in 0.12s")
    assert _pytest_passed("collected 3 items\n\n3 passed in 0.02s")
    assert not _pytest_passed("1 failed, 8 passed in 0.10s")
    assert not _pytest_passed("no tests ran in 0.01s")
    assert not _pytest_passed("")


def test_execute_required_test_run_without_pytest_evidence_fails():
    """RT5 复现：碎片要求运行 pytest，但只产出代码未跑测试 → 不得判 ok。"""
    class WriteOnly:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "writeonly"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="先写代码", tool_calls=[
                    {"name": "write_file",
                     "arguments": {"path": "stats.py",
                                   "content": "def total(a, b):\n    return a + b\n"}}])
            return "执行完成：stats.py 已产出"

    r, _ = _runner("execute", WriteOnly(), max_budget=3)
    res = r.run_unit("U-1", "execute",
                     {"goal": "创建 stats.py 并运行 pytest 确认通过"})
    assert res.status == "failed", \
        f"无 pytest 运行物证的『完成』不得判 ok（status={res.status}）"


def test_execute_required_test_run_with_pytest_evidence_converges():
    """正向往（防误杀）：真实运行 pytest 通过（输出含 passed）→ ok。"""
    class WriteRunThenDone:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "writerun"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="写代码", tool_calls=[
                    {"name": "write_file",
                     "arguments": {"path": "stats.py",
                                   "content": "def add(a, b):\n    return a + b\n"}}])
            if self.calls == 2:
                return ToolCallResult(text="写测试", tool_calls=[
                    {"name": "write_file",
                     "arguments": {"path": "test_stats.py",
                                   "content": ("from stats import add\n\n"
                                               "def test_add():\n"
                                               "    assert add(1, 2) == 3\n")}}])
            if self.calls == 3:
                return ToolCallResult(text="运行测试", tool_calls=[
                    {"name": "bash",
                     "arguments": {"command": "python -m pytest -q"}}])
            return "执行完成：pytest 全部通过"

    r, _ = _runner("execute", WriteRunThenDone(), max_budget=8)
    res = r.run_unit("U-1", "execute",
                     {"goal": "创建 stats.py 并运行 pytest 确认通过"})
    assert res.status == "ok", f"有 pytest 通过物证应收敛：{res.error}"


def test_execute_without_test_requirement_unaffected():
    """防误杀：碎片未要求运行 pytest → 写物证即收敛（既有语义不变）。"""
    class WriteThenDone:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "writethen"

        def chat(self, messages, tools=None):
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="写代码", tool_calls=[
                    {"name": "write_file",
                     "arguments": {"path": "stats.py",
                                   "content": "def add(a, b):\n    return a + b\n"}}])
            return "执行完成：stats.py 已产出"

    r, _ = _runner("execute", WriteThenDone(), max_budget=4)
    res = r.run_unit("U-1", "execute", {"goal": "实现 stats.py 的加法函数"})
    assert res.status == "ok", res.error


def test_requires_test_run_semantics_v2():
    """O3/C2a：测试/用例 + 运行动词（同子句邻近）即触发；不纳入裸『验证』。"""
    from wuxing.runner import _requires_test_run
    assert _requires_test_run("编写自动化测试用例并运行验证")   # E3-4 任务书原句
    assert _requires_test_run("运行测试并给出结论")
    assert _requires_test_run("执行用例覆盖边界")
    assert _requires_test_run("创建 x.py 并运行 pytest 确认通过")  # 旧口径保留
    assert not _requires_test_run("运行程序验证输入校验")          # 误伤面：无测试名词
    assert not _requires_test_run("实现 x.py 并写入结果")
    assert not _requires_test_run("编写测试用例：覆盖边界条件")    # 无运行动词（由 C2b 兜）


def test_is_test_path_patterns():
    from wuxing.runner import _is_test_path
    assert _is_test_path("tests/test_x.py")
    assert _is_test_path("bookstore/tests/foo.py")
    assert _is_test_path("test_x.py")
    assert _is_test_path("x_test.py")
    assert _is_test_path(r"tests\test_x.py")
    assert not _is_test_path("bookstore/contest.py")
    assert not _is_test_path("docs/tests.md")
    assert not _is_test_path("")


def test_write_test_file_requires_run_dynamically(tmp_path):
    """execute 单元写出测试文件 ⇒ 动态触发运行要求（trace source=test_file）。"""
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace

    class _T:
        def __init__(self):
            self.events = []

        def log(self, event, *a, **k):
            self.events.append((event, k))

    cfg = EngineConfig()
    ws = Workspace(tmp_path)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, load_tools(ws))
    r.trace = _T()
    r._current_domain_id = "execute"
    r._write_ok = r._read_ok = r._run_ok = False
    r._require_run = False
    r._deliverables = []
    r._note_evidence("write_file", {"path": "tests/test_a.py"}, "ok", "",
                     unit_id="U-1")
    assert r._write_ok and r._require_run
    assert any(e[0] == "run_required" and e[1].get("source") == "test_file"
               for e in r.trace.events)


def test_test_run_passed_matchers():
    from wuxing.runner import _test_run_passed
    assert _test_run_passed("python -m pytest -q", "3 passed in 0.02s")
    assert not _test_run_passed("python -m pytest", "1 failed, 2 passed in 0.10s")
    assert _test_run_passed("python -m unittest discover -s tests -v", "....\nOK\n")
    assert not _test_run_passed("python -m unittest", "FAILED (failures=2)")
    assert not _test_run_passed("python --version", "Python 3.10.11")
    assert not _test_run_passed("echo done", "done")


def test_note_evidence_bash_sets_run_ok(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace
    cfg = EngineConfig()
    ws = Workspace(tmp_path)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, load_tools(ws))
    r._current_domain_id = "execute"
    r._write_ok = r._read_ok = r._run_ok = False
    r._require_run = False
    r._deliverables = []
    r._note_evidence("bash", {"command": "python -m unittest discover -s tests"},
                     "ok", "....\nOK\n")
    assert r._run_ok


# ---- O3/C1：声称-交付物一致性（软观测，不驳回）----

def test_claim_extract_and_missing(tmp_path):
    """C1：反引号路径型声称提取；不在 deliverables 且工作区不可读 → missing。"""
    from wuxing.contracts import _extract_claims, _missing_claims
    from wuxing.workspace import Workspace
    (tmp_path / "bookstore").mkdir()
    (tmp_path / "bookstore" / "models.py").write_text("x", encoding="utf-8")
    ws = Workspace(tmp_path)
    claims = _extract_claims(
        "已产出 `bookstore/models.py` 与 `bookstore/cli.py`，见 `README.md`")
    assert "bookstore/models.py" in claims and "bookstore/cli.py" in claims
    missing = _missing_claims(ws, claims, ["bookstore/models.py"])
    assert missing == ["bookstore/cli.py", "README.md"]


def test_claim_mismatch_is_soft_observation(tmp_path):
    """C1 软档：收敛轮声称缺件仍判 ok（claim_mismatch 留痕），不驳回。"""

    class _T:
        def __init__(self):
            self.events = []

        def log(self, event, *a, **k):
            self.events.append((event, k))

    class ClaimThenWrite:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "claimthenwrite"

        def chat(self, messages, tools=None):
            self.calls += 1
            return ToolCallResult(
                text="执行完成：已产出 `bookstore/models.py` 与 `bookstore/cli.py`",
                tool_calls=[{"name": "write_file",
                             "arguments": {"path": "bookstore/models.py",
                                           "content": "x = 1\n"}}])

    r, _ws = _runner("execute", ClaimThenWrite(), max_budget=4)
    tr = _T()
    r.trace = tr
    res = r.run_unit("U-1", "execute", {"goal": "实现书店 CLI"})
    assert res.status == "ok", f"C1 软档不得驳回（status={res.status}）"
    mismatch = [k for e, k in tr.events if e == "claim_mismatch"]
    assert mismatch, "声称缺件应留 claim_mismatch trace（软观测）"
    assert "bookstore/cli.py" in (mismatch[0].get("missing") or []), mismatch
    nudge = [m for m in r._messages
             if "[契约]" in str(m.get("content", ""))
             and "未检出" in str(m.get("content", ""))]
    assert nudge, "应有一次性的缺件提醒（提醒不驳回——软档）"
