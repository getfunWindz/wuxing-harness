"""TDD：技能清单公开契约（UI 重构 · 技能快捷选择）——壳只拿名称/描述/层级。"""
import pathlib
import tempfile

from wuxing.config import EngineConfig
from wuxing.engine import Engine


def _mk_engine(wd) -> Engine:
    return Engine(cfg=EngineConfig(llm="mock"), workdir=wd)


def test_list_skills_reads_project_skills():
    wd = pathlib.Path(tempfile.mkdtemp())
    sdir = wd / ".skills" / "my-skill"
    sdir.mkdir(parents=True)
    (sdir / "SKILL.md").write_text(
        "---\nname: my-skill\ndescription: 测试技能\n---\n\n正文\n",
        encoding="utf-8")
    eng = _mk_engine(wd)
    skills = eng.list_skills()
    names = {s["name"]: s for s in skills}
    assert "my-skill" in names, skills
    assert names["my-skill"]["description"] == "测试技能"
    assert "path" not in names["my-skill"], "壳不需要内部路径"


def test_list_skills_empty_is_safe():
    wd = pathlib.Path(tempfile.mkdtemp())
    eng = _mk_engine(wd)
    assert isinstance(eng.list_skills(), list)


def test_engine_skill_manage_install_detail_remove(tmp_path, monkeypatch):
    """阶段 5（T5.1）：技能安装/详情/卸载（仅用户级；内置受保护）。"""
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path, auto_confirm=True)
    monkeypatch.setattr(eng.skills, "user_dir", tmp_path / "user_skills")
    out = eng.install_skill(
        "demo-skill", "演示技能",
        "---\nname: demo-skill\ndescription: 演示技能\nlevel: fragment\n---\n正文内容")
    assert out["name"] == "demo-skill"
    detail = eng.skill_detail("demo-skill")
    assert detail and "正文内容" in detail["content"]
    assert "demo-skill" in [s["name"] for s in eng.list_skills()]
    assert eng.remove_skill("demo-skill")["ok"] is True
    assert eng.skill_detail("demo-skill") is None
    import pytest
    with pytest.raises(ValueError):
        eng.remove_skill("find-skill")          # 内置技能不可删
    with pytest.raises(ValueError):
        eng.remove_skill("no-such-skill")
    with pytest.raises(ValueError):
        eng.install_skill("bad/name", "x", "---\nname: x\n---\n")  # 路径遍历拒绝


def test_engine_skill_discover_structured_failure(tmp_path, monkeypatch):
    """在线发现：成功返回 items；网络失败返回结构化错误（不抛）。"""
    import wuxing.skills as skills_mod
    from wuxing.engine import Engine
    eng = Engine(workdir=tmp_path, auto_confirm=True)
    monkeypatch.setattr(skills_mod.SkillRadarClient, "discover",
                        lambda self, goal, constraints="", max_results=5: [{"name": "found"}])
    out = eng.discover_skills("写周报")
    assert out["ok"] is True and out["items"][0]["name"] == "found"

    def boom(self, goal, constraints="", max_results=5):
        raise RuntimeError("network down")

    monkeypatch.setattr(skills_mod.SkillRadarClient, "discover", boom)
    out2 = eng.discover_skills("写周报")
    assert out2["ok"] is False and "network down" in out2["error"]


def test_engine_mcp_status(tmp_path):
    """阶段 5（T5.2）：MCP 状态——服务/工具/权限声明/连接统计。"""
    from wuxing.engine import Engine
    from wuxing.tools.mcp_bridge import McpServerConfig
    eng = Engine(workdir=tmp_path, auto_confirm=True)
    eng._mcp_cfgs = [McpServerConfig(name="demo", command="python", args=["-m", "x"])]

    class T:
        is_mcp = True
        _server = "demo"
        def name(self): return "demo_echo"
        def description(self): return "echo"
        def input_schema(self): return {"type": "object"}
        def permission(self):
            return {"read": True, "write": False, "execute": False,
                    "network": False, "destructive": False}

    eng.tools.register(T())
    st = eng.mcp_status()
    assert st["enabled"] is True
    srv = st["servers"][0]
    assert srv["name"] == "demo" and srv["command"] == "python"
    tool = srv["tools"][0]
    assert tool["name"] == "demo_echo" and tool["permissions"]["read"] is True
    assert "connections" in srv["stats"]


def test_engine_skill_near_duplicates(tmp_path, monkeypatch):
    """B 面：引擎近义报告（只读；用户级目录；异常结构化失败）。"""
    from wuxing.engine import Engine

    eng = Engine(workdir=tmp_path, auto_confirm=True)
    ud = tmp_path / "user_skills"
    body = "步骤一：先写失败测试。步骤二：最小实现。步骤三：回归。"
    for name in ("pytest-minimal-function", "pytest-minimal-smoke"):
        d = ud / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d\n---\n{body}\n",
            encoding="utf-8")
    monkeypatch.setattr(eng.skills, "user_dir", ud)
    out = eng.skill_near_duplicates()
    assert out["skills_total"] == 2 and out["error"] == ""
    assert len(out["clusters"]) == 1
    monkeypatch.setattr(eng.skills, "user_dir", None)
    empty = eng.skill_near_duplicates()
    assert empty["skills_total"] == 0 and empty["clusters"] == []
    assert empty["error"] == ""
