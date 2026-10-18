"""TDD · L4 真跑发现：碎片交付物语义缺失 + 内部目录泄露——模型无法自交付（探索不止）。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.builtin import BUILTIN_TOOLS
from wuxing.workspace import Workspace


def test_fragment_carries_deliverables():
    """碎片必须携带交付物类型（segment 有——引擎丢弃=信息缺失链起点）。"""
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    d = {"nodes": [{"id": "n1", "text": "实现登录", "domain": {"开发": 0.9},
                    "trades": [], "complexity": "low", "deliverable": "code",
                    "weight": 0.5}], "edges": []}
    eng.shape_cache.put("实现登录功能", d)
    res = eng.run_task("实现登录功能")
    assert res.fragments, res.report
    assert any(f.get("deliverables") for f in res.fragments), \
        "碎片必须携带 deliverables（交付物语义——F-000x 未知交付→探索不止）"


def test_prompt_announces_deliverable_type():
    """执行 prompt 必须注入本碎片交付物类型（模型知道交付什么才收敛）。"""
    class L:
        def __init__(self): self.seen = []
        def name(self): return "l"
        def chat(self, messages, tools=None):
            self.seen.append([dict(m) for m in messages])
            return "x"
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = L()
    r = Runner(EngineConfig(), DomainRegistry(EngineConfig()), ws, llm,
               BUILTIN_TOOLS(ws))
    r.run_unit("U-1", "execute", {"goal": "实现登录", "deliverables": ["code"]})
    usr = " ".join(m["content"] for m in llm.seen[0] if m.get("role") != "system")
    assert "交付物" in usr and ("code" in usr or "代码" in usr), \
        "prompt 必须声明本碎片交付物类型"


def test_internal_dir_hidden_from_read():
    """read 工具必须屏蔽引擎内部目录（.wuxing——模型困惑源：把缓存当任务上下文）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / ".wuxing").mkdir()
    (ws.root / ".wuxing" / "shape_cache.json").write_text("{}", encoding="utf-8")
    from wuxing.tools.fs_tools import ReadFileTool
    t = ReadFileTool(ws)
    res = t.execute(path=".wuxing/shape_cache.json")
    assert res.status in ("blocked", "error"), \
        "内部目录不得可读（模型看到引擎缓存=上下文污染）"


def test_root_internal_files_hidden():
    """根级内部文件（reply_cache/shape_cache 等）不可读——非 .wuxing 路径同样屏蔽。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / "reply_cache.json").write_text("{}", encoding="utf-8")
    (ws.root / "shape_cache.json").write_text("{}", encoding="utf-8")
    from wuxing.tools.fs_tools import ReadFileTool
    t = ReadFileTool(ws)
    for f in ("reply_cache.json", "shape_cache.json"):
        res = t.execute(path=f)
        assert res.status in ("blocked", "error"), f"{f} 必须不可读"


def test_last_round_pressure_injected():
    """最后轮前必须注入轮次压力提示（模型感知「声明轮」——时序缺口修复）。"""
    class L4:
        def __init__(self): self.calls = 0; self.seen = []
        def name(self): return "l"
        def chat(self, messages, tools=None):
            self.calls += 1
            self.seen.append([dict(m) for m in messages])
            if self.calls <= 3:
                return "探索中"  # 纯文本（无写物证——测压力提示注入本身）
            return "完成"
    cfg = EngineConfig(max_loop_rounds=6, max_unit_budget=4)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    llm = L4()
    Runner(cfg, DomainRegistry(cfg), ws, llm, BUILTIN_TOOLS(ws)).run_unit(
        "U-1", "execute", {"goal": "g"})
    # 第 4 轮调用（最后一轮）应看到压力提示（第 3 轮后注入——user 动态区）
    last = " ".join(m["content"] for m in llm.seen[3]
                    if m.get("role") == "user" and isinstance(m.get("content"), str))
    assert "剩余 1 轮" in last, "最后轮前必须注入轮次压力提示（user 动态区）"


def test_brain_memory_internal_file_hidden():
    """brain_memory.json（智脑记忆）同为内部文件——模型不可读。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / "brain_memory.json").write_text("{}", encoding="utf-8")
    from wuxing.tools.fs_tools import ReadFileTool
    res = ReadFileTool(ws).execute(path="brain_memory.json")
    assert res.status in ("blocked", "error")


def test_plan_artifact_injected_to_dep_free_fragment():
    """计划产物全局注入：无依赖碎片（分析型）也收到计划内容（免探索）。"""
    from wuxing.engine import Engine

    class L5:
        def __init__(self): self.seen = {}
        def name(self): return "l"
        def chat(self, messages, tools=None):
            # 探测运行：按消息内容选策略
            joined = " ".join(str(m.get("content", "")) for m in messages)
            if "制定方案" in joined:
                return ("方案：先分析后开发\n"
                        "TOOLCALL:write_artifact path=plan.md kind=plan content=方案文本")
            if "请验收" in joined:
                return "TOOLCALL:read_dependency path=plan.md\n结论：通过"
            return "执行完成\nTOOLCALL:write_artifact path=out.md kind=result content=产物"
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), llm=L5(),
                 auto_confirm=True)
    eng.shape_cache.put("分析并实现", {
        "nodes": [
            {"id": "n1", "text": "需求分析与架构设计", "domain": {"规划": 0.9},
             "trades": [], "complexity": "low", "deliverable": "text",
             "weight": 0.5},
            {"id": "n2", "text": "开发用户系统", "domain": {"开发": 0.9},
             "trades": [], "complexity": "low", "deliverable": "code",
             "weight": 0.5}],
        "edges": [["n1", "n2"]]})
    res = eng.run_task("分析并实现")
    # 无依赖碎片（F-0001/分析型）应能收敛——计划注入免探索
    assert res.status in ("done", "partial"), res.report


def test_internal_read_error_semantic():
    """内部文件读取错误语义化（「不可读请勿重试」——原 not found 误导重试循环）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    (ws.root / "brain_memory.json").write_text("{}", encoding="utf-8")
    from wuxing.tools.fs_tools import ReadFileTool
    res = ReadFileTool(ws).execute(path="brain_memory.json")
    assert "internal data hidden" in res.error, "错误必须语义化（防误导重试）"
