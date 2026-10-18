"""TDD · L4 冒烟发现修复：收敛指令契约绑定 + marker 双语（真 LLM 输出英文叙述
、中文 marker 永不命中 + 无写工具指令 → require_write 物证永不满足）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def test_system_contains_convergence_instruction():
    """system 必须含收敛指令（完成声明——模型知道「如何才算完成」）。"""
    class L:
        def __init__(self): self.seen = []
        def name(self): return "l"
        def chat(self, messages, tools=None):
            self.seen.append([dict(m) for m in messages])
            return "x"
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = L()
    Runner(EngineConfig(), DomainRegistry(EngineConfig()), ws, llm,
           BUILTIN_TOOLS(ws)).run_unit("U-1", "execute", {"goal": "g"})
    sys_text = llm.seen[0][0]["content"]
    assert "收敛指令" in sys_text, "system 必须含收敛指令段"
    assert "完成声明" in sys_text, "收敛指令必须说明声明格式（机制契约）"


def test_execute_system_requires_write_tool():
    """execute 域必须提示「产物用写工具落盘」（require_write 物证的模型侧契约）。"""
    reg = DomainRegistry(EngineConfig())
    d = reg.get("execute")
    joined = (d.quality_notes or "") + "\n" + (d.prompt_skeleton or "")
    assert "写工具" in joined or "write" in joined.lower(), \
        "execute 契约必须指令写工具落盘（产物可追踪）"


def test_markers_include_english_completion_words():
    """markers 双语（模型可能输出英文——中文 marker 独语永不命中，冒烟实锤）。"""
    reg = DomainRegistry(EngineConfig())
    for did in ("execute", "plan"):
        mk = " ".join(reg.get(did).success_markers)
        assert any(w in mk.lower() for w in ("done", "complete", "finish", "plan")), \
            f"{did} markers 缺英文完成词（真 LLM 英文输出场景）"


def test_system_announces_budget():
    """system 必须声明轮预算（真跑发现：预算不透明 → 模型无限探索永不产出）。"""
    class L2:
        def __init__(self): self.seen = []
        def name(self): return "l"
        def chat(self, messages, tools=None):
            self.seen.append([dict(m) for m in messages])
            return "x"
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = L2()
    Runner(EngineConfig(max_unit_budget=3), DomainRegistry(EngineConfig()),
           ws, llm, BUILTIN_TOOLS(ws)).run_unit("U-1", "execute", {"goal": "g"})
    sys_text = llm.seen[0][0]["content"]
    assert "3 轮" in sys_text or "最多有 3" in sys_text, \
        "system 必须声明轮预算（预算透明化——防无限探索）"


def test_system_bans_promise_language():
    """system 必须含反叙述约束（真跑实锤：'I'll write...' 承诺性语句从不执行）。"""
    class L3:
        def __init__(self): self.seen = []
        def name(self): return "l"
        def chat(self, messages, tools=None):
            self.seen.append([dict(m) for m in messages])
            return "x"
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = L3()
    Runner(EngineConfig(), DomainRegistry(EngineConfig()), ws, llm,
           BUILTIN_TOOLS(ws)).run_unit("U-1", "execute", {"goal": "g"})
    sys_text = llm.seen[0][0]["content"]
    assert "承诺" in sys_text or "我将" in sys_text, "必须禁止承诺性语句（叙述≠行动）"
