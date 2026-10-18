"""TDD：上下文压缩（DSH 式——工具结果头尾保留+中间摘要；压缩点不破前缀）。"""
from wuxing.context import compress_tool_results


def test_long_result_truncated_head_tail():
    """单条超限：头 2K + 中间注记 + 尾 2K。"""
    long = "A" * 10000
    out = compress_tool_results([{"role": "user", "content": f"[tool] read: {long}"}],
                                max_chars=8192)
    joined = out[0]["content"]
    assert len(joined) < len(long) + 100, "必须压缩"
    assert "已压缩" in joined or "[中间" in joined, joined[:80]
    assert joined.startswith("[tool] read: AA"), "头部保留"
    assert joined.rstrip().endswith("AA"), "尾部保留"


def test_short_result_unchanged():
    """未超限：原样（零扰动）。"""
    msgs = [{"role": "user", "content": "[tool] write: done"}]
    out = compress_tool_results(msgs, max_chars=8192)
    assert out == msgs


def test_system_prefix_never_touched():
    """system（前缀）不参与压缩——压缩点=尾部动态区（TokenPilot 铁律）。"""
    sys_msg = {"role": "system", "content": "你是规划域智能体（域：plan）。" * 5}
    long = "B" * 12000
    out = compress_tool_results([sys_msg, {"role": "user", "content": long}],
                                max_chars=8192)
    assert out[0] == sys_msg, "system 必须逐字节不变（缓存红线）"
    assert len(out[1]["content"]) == 12000, "非工具消息不压缩（LLM 输出是必需上下文）"


def test_multiple_tool_results_accumulated_compressed():
    """多条结果累计超限：每条独立压缩（不删条）。"""
    msgs = [{"role": "user", "content": f"[tool] a: {'X'*5000}"},
            {"role": "user", "content": f"[tool] b: {'Y'*5000}"}]
    out = compress_tool_results(msgs, max_chars=4000)
    assert len(out) == 2, "不删条——逐条压缩"
    assert all("已压缩" in m["content"] or "[中间" in m["content"] for m in out)


# ============================== L0-1 回归守卫 ================================
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner, _wrap_tool_result
from wuxing.tools.loader import load_tools
from wuxing.workspace import Workspace


def test_tool_result_source_name_no_colon():
    """_wrap_tool_result：source 名不得带冒号残留（溯源字段干净）。"""
    assert _wrap_tool_result("[tool] bash: echo hi").startswith(
        '<tool_result source="bash">'), "source 名不应含冒号"
    assert _wrap_tool_result("[tool:error] read_file: boom").startswith(
        '<tool_result source="read_file" status="tool:error">'), \
        "error 语义必须保留（status 属性）"


class _LongOutputLlm:
    """execute 域多轮：读长产物（回填 90K 工具结果）→ 收口。"""

    def __init__(self):
        self.calls = 0
        self.seen = []

    def name(self):
        return "long-out"

    def chat(self, messages, tools=None):
        from wuxing.llm.tool_results import ToolCallResult
        self.calls += 1
        self.seen.append([dict(m) for m in messages])
        if self.calls == 1:
            # M1-5 契约语义（写物证即通过）——第 1 轮读长文件制造长回填（ws 预置 big.txt）
            return ToolCallResult(text="", tool_calls=[
                {"name": "read_dependency", "arguments": {"path": "big.txt"}}])
        return ("执行完成\n"
                "TOOLCALL:write_artifact path=out.md kind=result content=y")


def test_runner_wrapped_tool_result_is_compressed():
    """回归（A1/PE-1）：runner 真实路径——工具结果先 wrap 后压缩必须生效。

    未修复前：wrap 后以 <tool_result 开头，compress_tool_results 按 [tool] 前缀
    过滤 → 压缩不触发 → 90K 工具结果原样进入消息历史（上下文膨胀）。
    """
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=5)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / "big.txt").write_text("x" * 90000, encoding="utf-8")  # 预置长依赖
    llm = _LongOutputLlm()
    r = Runner(cfg, DomainRegistry(cfg), ws, llm, load_tools(ws))
    res = r.run_unit("U-1", "execute", {"goal": "g"})
    assert res.status == "ok", res.error
    # 第二轮调用时的历史：90K 工具结果若未压缩 → 总长 >> 30K
    total = sum(len(m.get("content", "")) for m in llm.seen[1]
                if isinstance(m.get("content"), str))
    assert total < 30000, f"工具结果未压缩：历史总长 {total}（长工具结果原样灌入）"
    joined = " ".join(m["content"] for m in llm.seen[1]
                      if isinstance(m.get("content"), str))
    assert "已压缩" in joined or "[中间" in joined, "压缩注记缺失"


def test_graded_compression_aggressive_for_huge_results():
    """E3（企业级审查/DSH）：超大工具结果分级压缩——>64K 更激进（头尾 1500），
    256K+ 极端（头尾 800）——超大输出不按固定 2000 兜底（成本控制）。"""
    from wuxing.context import HEAD_KEEP, TAIL_KEEP, _compress_single
    # 基线场景：<=64K 按默认（2000）
    s1 = ("A" * HEAD_KEEP + "B" * 5000 + "C" * 3000 + "E" * 1800
          + "TAILMARK" + "F" * 200)  # >8K（标记落在尾部保留区）
    c1 = _compress_single(s1, 8192, HEAD_KEEP, TAIL_KEEP)
    assert "TAILMARK" in c1 and len(c1) < len(s1)
    # 70K → 分级更激进（head/tail 1500——比默认 2000 短）
    s2 = "A" * 70_000 + "B" * 4000 + "TAILMARK-" + "C" * 100
    c2 = _compress_single(s2, 8192, HEAD_KEEP, TAIL_KEEP)
    assert "TAILMARK" in c2, "尾部内容必须保留（分级只加剧中段裁剪）"
    # 70K 内容中段注记在（字符数信息）
    assert "已压缩" in c2
    # 分级生效：>64K 结果比 2000+2000 更短
    assert len(c2) < 2 * HEAD_KEEP + 2 * TAIL_KEEP, \
        f"70K 结果必须分级压缩（实际 {len(c2)}——旧路径恒 4000+）"


def test_extreme_grading_256k():
    """256K+ 极端级（头尾 800）——巨量工具输出不得撑大上下文。"""
    from wuxing.context import HEAD_KEEP, TAIL_KEEP, _compress_single
    s = "X" * 300_000 + "ENDMARK-999"
    c = _compress_single(s, 8192, HEAD_KEEP, TAIL_KEEP)
    assert "ENDMARK-999" in c
    assert len(c) < 2_500, f"256K+ 极端级应压缩到 2.5K 内（实际 {len(c)}）"


# ===================== B：按工具来源差异化压缩（2026-09-11） =====================

def test_default_tool_limits_32k_policy():
    """B 档位回调（用户裁决 + batch2 数据）：read 64K→32K——
    batch2 中 >32K 读取仅 beginner 6 条/novice 1 条（scripter/precise 0）——
    32K 保留绝大多数内容同时回收上下文成本；bash 维持 16K。"""
    from wuxing.config import EngineConfig
    lim = EngineConfig().context_tool_limits
    assert lim["read_file"] == 32768, lim
    assert lim["read_dependency"] == 32768, lim
    assert lim["bash"] == 16384, lim


def test_tool_specific_limits_keep_read_results():
    """B（报告 #6 数据）：read_file 上限 64K——大文件读取不再被裁
    （44 条压缩事件中 read 占 18 条/248K 字符——验收「不完整」根因）。"""
    from wuxing.context import compress_tool_results
    big = "[tool] read_file: " + "x" * 20000
    out = compress_tool_results([{"role": "user", "content": big}], max_chars=8192,
                                tool_limits={"read_file": 65536, "bash": 16384})
    assert "[中间" not in out[0]["content"], "read_file 在 64K 内不得压缩"
    assert len(out[0]["content"]) == len(big)


def test_tool_specific_limits_compress_bash():
    """bash 上限 16K——日志类输出仍受控（实测 26 条 bash 压缩事件全 <=16K）。"""
    from wuxing.context import compress_tool_results
    big = "[tool] bash: " + "y" * 20000
    out = compress_tool_results([{"role": "user", "content": big}], max_chars=8192,
                                tool_limits={"read_file": 65536, "bash": 16384})
    assert "[中间" in out[0]["content"], "bash 超 16K 仍压缩"


def test_wrapped_tool_result_source_limits():
    """<tool_result source=\"...\"> 包装形态同样按 source 取上限（runner 真实路径）。"""
    from wuxing.context import compress_tool_results
    big = ('<tool_result source="read_file" status="ok">\n'
           + "z" * 20000 + "\n</tool_result>")
    out = compress_tool_results([{"role": "user", "content": big}], max_chars=8192,
                                tool_limits={"read_file": 65536})
    assert "[中间" not in out[0]["content"]


def test_compress_guard_small_limit_no_expansion():
    """六轮审查 C4：压缩结果不得超过上限、不得比原文更长。

    head/tail 预算大于上限时（极端配置/极小工具上限），原实现输出
    head+tail+注记 > 原文——压缩反而膨胀（3500 字符 @limit=1000 → 4017）。"""
    from wuxing.context import _compress_single
    s = "a" * 3500
    out = _compress_single(s, 1000, 2000, 2000)
    assert len(out) <= 1000, f"压缩结果不得超上限（实际 {len(out)}）"
    s2 = "b" * 5000
    out2 = _compress_single(s2, 100, 2000, 2000)
    assert len(out2) < len(s2), "压缩不得比原文更长"
