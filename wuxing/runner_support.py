"""Runner 支撑件（骨架分期 P7/F-3f：自 runner.py 提取的模块级常量/校验/工具函数 + 节流器）。

来源：`wuxing/runner.py`（2026-10-06 迁移；常量/函数体逐字节保持）。
理由：F-3 巨型文件分期——支撑面落隔离模块供 runner/mixin 共用；**不得 import engine**（守卫）。
"""
import re
import time

_TOOLCALL_RE = re.compile(r"^TOOLCALL:(\w+)(.*)$")
_KV_RE = re.compile(r"(\w+)=(\S+)")

# #3（用户裁决 2026-09-11）：单碎片工具批量并发硬上限 10（目标 8）——
# 单轮全方案场景下防工具并发失控；全局上界 = 单元并行 × 本上限
MAX_PARALLEL_TOOLS = 10

# M1-4：无副作用工具集（组内并发执行——read 突发并发化；其余保序串行）
_NO_SIDE_EFFECT = {"read_file", "read_dependency", "load_skill"}

# E2-5（L5）：整表替换型工具——保序调用（同批多次调用按模型顺序应用），强制串行
# E2-5（A10）：ask_user 挂起语义——不参与并行只读批（同批独占，Q7）
_SERIAL_ONLY = {"todo_write", "ask_user"}


# 真测缺陷（RT5）：显式要求「运行测试」的碎片需要运行物证——
# 机制只认「文本要求 + 成功运行输出」，不认模型的完成声明。
# O3/C2a（2026-10-07）：语义扩展——「测试/用例」+ 运行动词（同子句邻近）也触发；
# 不纳入裸「验证」（「运行程序验证输入」类误伤为运行要求——证据面无法满足）；
# 「运行验证」场景由 C2b（测试文件触发）兜住。
_TEST_RUN_VERBS = ("运行", "执行", "跑", "run")
_RUN_TEST_RE = re.compile(
    r"(?:运行|执行|跑)[^。；;\n]{0,6}(?:测试|用例|pytest|unittest)"
    r"|(?:测试|用例|pytest|unittest)[^。；;\n]{0,6}(?:运行|执行|跑)")


def _requires_test_run(text: str) -> bool:
    """碎片文本是否显式要求运行测试（execute 域物证需求）。

    O3/C2a：pytest+动词（旧口径）或 「测试/用例」+运行动词（邻近）均触发。
    """
    t = str(text or "").lower()
    if not t:
        return False
    if "pytest" in t and any(k in t for k in _TEST_RUN_VERBS):
        return True
    return bool(_RUN_TEST_RE.search(t))


# O3/C2b（2026-10-07）：测试文件触发——写出测试型路径 ⇒ 承诺运行（任务书
# 「编写并运行验证」的机械镜像；不依赖 shaper 保留「运行」字样）。
_TEST_DIR_RE = re.compile(r"(^|/)(tests?|__tests__)(/|$)", re.IGNORECASE)
_TEST_NAME_RE = re.compile(
    r"(^|/)(test_[^/]+|[^/]+_test)(\.[A-Za-z0-9]{1,8})?$", re.IGNORECASE)


def _is_test_path(path: str) -> bool:
    """测试型路径：tests/ 目录段、test_* / *_test 文件名（反斜杠归一）。"""
    p = str(path or "").replace("\\", "/").strip()
    if not p:
        return False
    return bool(_TEST_DIR_RE.search(p) or _TEST_NAME_RE.search(p))


def _pytest_passed(content: str) -> bool:
    """pytest 输出是否显示「通过」：取最后一条含 passed 的行，同行不得含 failed/error。"""
    c = str(content or "").lower()
    for line in reversed(c.splitlines()):
        if " passed" in line:
            return ("failed" not in line) and ("error" not in line)
    return False


def _test_run_passed(cmd: str, content: str) -> bool:
    """O3/C2c：测试运行物证——pytest（原口径）或 unittest（OK/FAILED 汇总行）。

    非测试命令（python --version 等）不构成运行物证（防「随便跑个命令」即算）。
    """
    c = str(cmd or "").lower()
    text = str(content or "").lower()
    if "pytest" in c:
        return _pytest_passed(text)
    if "unittest" in c:
        for line in reversed(text.splitlines()):
            s = line.strip()
            if s == "ok" or s.startswith("ok ("):
                return True
            if s.startswith(("failed", "error")):
                return False
        return False
    return False


def _test_run_attempted(cmd: str) -> bool:
    """S1-B：运行尝试证据位——测试命令被执行过（不论通过与否）。

    与 _test_run_passed（通过物证）配对：attempted 且非 passed = 跑过未过。
    """
    c = str(cmd or "").lower()
    return "pytest" in c or "unittest" in c


def _is_side_effect_free(name: str, registry) -> bool:
    """无副作用判定——机制机械裁决（非模型自觉）。

    - 静态表（内置只读种子/兼容）
    - 权限声明推导（X5 · E3-1：统一内置 + MCP + 扩展）：read=True 且
      write/execute/network/destructive 全 False → 只读（组内并发安全）
    - 其余（写/bash/delegate/网络类）→ 串行（顺序语义）
    """
    if name in _SERIAL_ONLY:
        return False
    if name in _NO_SIDE_EFFECT:
        return True
    tool = registry.get(name) if registry is not None else None
    if tool is None:
        return False
    try:
        perm = dict(tool.permission() or {})
    except Exception:
        return False  # 声明不可读 → 保守串行（fail-closed）
    return (bool(perm.get("read"))
            and not perm.get("write") and not perm.get("execute")
            and not perm.get("network") and not perm.get("destructive"))

def _wrap_tool_result(line: str) -> str:
    """PE-1：工具日志行 → 边界标记格式（<tool_result source=… status=…>）。

    格式：\n<tool_result source=\"{name}\" status=\"{kind}\">\n{content}\n</tool_result>\n
    status 保留：tool→无（默认 ok）/ tool:error/guard/warn → 语义标记（
    L2-2 修正——旧版把错误语义抹平为纯 source 标签，模型无法区分成功与失败）。
    """
    import re as _re
    # L0-1（审查 A1）：[^\s:]+ 非贪婪至冒号/空白——修复旧正则 (\S+) 贪婪导致
    # source="bash:" 冒号残留（溯源字段脏——<tool_result source> 质量）。
    m = _re.match(r"^\[(tool|tool:error|guard|warn)\]\s*([^\s:]+):?\s*(.*)$", line,
                  _re.DOTALL)
    if m:
        kind, name, content = m.group(1), m.group(2), m.group(3)
        attrs = f'source="{name}"'
        if kind != "tool":
            attrs += f' status="{kind}"'
        return (f'<tool_result {attrs}>\n'
                f'{content}\n</tool_result>')
    return f"<tool_result>\n{line}\n</tool_result>"


def _prepare_tool_result(line: str, *, sanitize: bool = True) -> tuple:
    """SEC1：净化（可选）→ PE-1 信封。返回 (wrapped, findings)。"""
    findings: list = []
    if sanitize:
        from wuxing.content_trust import sanitize_untrusted
        res = sanitize_untrusted(line)
        line, findings = res.clean, res.findings
    return _wrap_tool_result(line), findings


# 思维链增量累计封顶（与 UnitReasoning 整段口径一致）
_REASONING_DELTA_CAP = 10000


class _ReasoningDeltaThrottle:
    """思维链增量节流器（专项 Task 2 · 风险#2）：时间窗/字符量双阈值合并发送。

    目的：token 级 delta 不逐条成事件（事件体积与订阅队列保护）；
    纪律：push 顺序保持，流结束必须 flush()（尾部不丢）。
    """

    def __init__(self, emit, min_interval: float = 0.08, min_chars: int = 64):
        self._emit = emit
        self._min_interval = max(0.0, float(min_interval))
        self._min_chars = max(1, int(min_chars))
        self._buf: list = []
        self._n = 0
        self._last = 0.0

    def push(self, text: str) -> None:
        if not text:
            return
        self._buf.append(text)
        self._n += len(text)
        now = time.monotonic()
        if self._n >= self._min_chars or (now - self._last) >= self._min_interval:
            self.flush()

    def flush(self) -> None:
        if not self._buf:
            return
        text = "".join(self._buf)
        self._buf = []
        self._n = 0
        self._last = time.monotonic()
        self._emit(text)
