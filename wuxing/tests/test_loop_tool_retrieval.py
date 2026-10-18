"""TDD · L2-3：工具检索（FC 层2——工具太多时 top-k 选准；mcp2cli 教训：前缀精简）。

规则：
  工具数 ≤ 阈值 → 零变化（现状保持——小工具集不折腾）
  超阈值 → 按 fragment 文本 jieba 词元 Jaccard 选 top-k（确定性——同片段同选择
  = 单元内 system/tools 前缀稳定 = 缓存安全）
  强制保留集：delegate/load_skill（引擎级——渐进披露/委托能力不可剪）
"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.registry import DomainRegistry
from wuxing.runner import Runner
from wuxing.tools.base import Tool, ToolRegistry
from wuxing.workspace import Workspace


class _FakeTool(Tool):
    def __init__(self, name, desc):
        self._n, self._d = name, desc

    def name(self):
        return self._n

    def description(self):
        return self._d

    def input_schema(self):
        return {"type": "object", "properties": {},
                "required": []}

    def permission(self):
        return {"read": True, "write": False, "execute": False,
                "network": False, "destructive": False}

    def execute(self, **kw):
        from wuxing.protocols import ToolResult
        return ToolResult(status="ok", content=f"ok-{self._n}", tool_name=self._n)

    def is_mcp(self):
        return False


def _many_tools(registry):
    """12 个假工具：文件/数据库/网络/数学 四类——检索可分。"""
    for name, desc in [
        ("file_read", "读取文件内容"), ("file_write", "写入文件"),
        ("db_query", "查询数据库"), ("db_insert", "写入数据库"),
        ("web_fetch", "抓取网页"), ("web_post", "发送网页请求"),
        ("math_add", "数学加法"), ("math_avg", "数学平均"),
        ("log_read", "读取日志文件"), ("cfg_save", "保存配置"),
        ("json_parse", "解析 JSON"), ("csv_parse", "解析 CSV"),
    ]:
        registry.register(_FakeTool(name, desc))


def _whitelist(registry):
    return registry.list()  # 全部豁免（构造超阈值场景）


def test_below_threshold_unchanged():
    """低于阈值：零变化（小工具集不启用检索——现状保持）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([])
    cfg = EngineConfig()
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    r._cur_params = {}
    wh = list(reg._tools.values())
    assert len(wh) <= cfg.tool_retrieval_threshold


def test_retrieval_selects_relevant_topk():
    """超阈值：fragment 含「文件」→ 选文件类，剪掉数据库/网络/数学类。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([])
    _many_tools(reg)
    cfg = EngineConfig(tool_retrieval_threshold=10, tool_retrieval_top_k=5)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    selected = r._select_tools(reg.list(), "读取文件并修改内容")
    names = {t.name() for t in selected}
    assert "file_read" in names and "file_write" in names, names
    assert "db_query" not in names and "web_fetch" not in names, names


def test_retrieval_deterministic():
    """确定性：同 fragment 两次选择相同（前缀稳定=缓存安全）。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([])
    _many_tools(reg)
    cfg = EngineConfig(tool_retrieval_threshold=10, tool_retrieval_top_k=5)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    a = {t.name() for t in r._select_tools(reg.list(), "解析 JSON 数据")}
    b = {t.name() for t in r._select_tools(reg.list(), "解析 JSON 数据")}
    assert a == b


def test_engine_level_tools_always_kept():
    """引擎级工具（delegate/load_skill）强制保留——检索不剪渐进披露/委托能力。"""
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([])
    _many_tools(reg)
    reg.register(_FakeTool("delegate", "委托子智能体"))
    reg.register(_FakeTool("load_skill", "加载技能详情"))
    cfg = EngineConfig(tool_retrieval_threshold=10, tool_retrieval_top_k=4)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    selected = r._select_tools(reg.list(), "解析 JSON 数据")
    names = {t.name() for t in selected}
    assert {"delegate", "load_skill"} <= names, "引擎级工具不可剪"


def 域键(domain_id: str) -> str:
    """C-3：域级检索键（同域确定性——tools 参数跨碎片稳定）。"""
    from wuxing.config import EngineConfig as _EC
    from wuxing.registry import DomainRegistry as _DR
    reg = _DR(_EC())
    d = reg.get(domain_id)
    return f"域 {domain_id} {d.title}"

def test_retrieval_domain_stable_across_fragments():
    """C-3：检索输入=域级（同域碎片同选择——tools 参数跨碎片一致=前缀稳定）。

    碎片文本不参与（同域不同 goal 的工具需求一致；MCP 大集场景前缀稳定性优先）。
    """
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([])
    _many_tools(reg)
    cfg = EngineConfig(tool_retrieval_threshold=10, tool_retrieval_top_k=5)
    r = Runner(cfg, DomainRegistry(cfg), ws, None, reg)
    a = {t.name() for t in r._select_tools(reg.list(), 域键("execute"))}
    b = {t.name() for t in r._select_tools(reg.list(), 域键("execute"))}
    assert a == b, "同域碎片必须同工具集（tools 稳定=前缀稳定）"
    # 与碎片文本无关（不同 goal 同域结果一致）
    c = {t.name() for t in r._select_tools(reg.list(), 域键("execute"))}
    assert a == c


def test_retrieval_tokens_cached():
    """D3：工具检索分词缓存——同输入重复分词不得重复调用 jieba（域级键固定——
    每 run_unit 一次检索——多碎片重复分词；lru 缓存——确定性不变）。"""
    import wuxing.cache as cache_mod
    from wuxing.cache import _tokens_for_sim
    calls = {"n": 0}
    orig = cache_mod.jieba.lcut

    def counting_lcut(*a, **kw):
        calls["n"] += 1
        return orig(*a, **kw)

    import uuid
    key = f"域 execute 执行域 {uuid.uuid4().hex[:8]}"  # 唯一输入防跨测试预热
    key2 = f"域 verify 验证域 {uuid.uuid4().hex[:8]}"
    cache_mod.jieba.lcut = counting_lcut
    try:
        t1 = _tokens_for_sim(key)
        t2 = _tokens_for_sim(key)
        t3 = _tokens_for_sim(key2)  # 不同输入不受缓存影响
        assert t3 is not None
    finally:
        cache_mod.jieba.lcut = orig
    assert t1 == t2
    # 同输入只分词一次（第二次命中缓存）——不同输入照常分词
    assert calls["n"] == 2, f"同输入重复分词不得重复 jieba（实际 {calls['n']} 次）"
