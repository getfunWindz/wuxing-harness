"""TDD（双模式批 1 · Task 4）：工具集一致性——write_file 四域白名单 + 描述巡检。

依据：docs/plans/2026-09-23-wuxing-dual-mode-batch1.md Task 4 + 调研附五
（write_file 从未进入任何域白名单，但提示词/执行域质量注记引用它——一致性缺陷）。
"""
from wuxing.domains.defaults import DEFAULT_DOMAINS


def test_write_file_whitelisted_everywhere():
    """四域白名单必须含 write_file（与 build_system_text 公共段『write_artifact 或
    write_file』一致；execute 质量注记亦引用）。"""
    for d in DEFAULT_DOMAINS.values():
        assert "write_file" in d.tool_whitelist, d.domain_id


def test_core_tools_have_meaningful_descriptions():
    """描述巡检：核心工具描述非空且含行为要点（CLI 质量直连——模型据此使用）。"""
    import pathlib
    import tempfile

    from wuxing.tools.loader import load_tools
    from wuxing.workspace import Workspace

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    tools = {t.name(): t for t in load_tools(ws).list()}
    for name in ("bash", "read_file", "write_file", "write_artifact",
                 "read_dependency"):
        assert name in tools, name
        desc = tools[name].description() or ""
        assert len(desc.strip()) >= 8, f"{name} 描述过短：{desc!r}"
    # 行为要点在场（使用决策所需——用户最大担忧=CLI 能力）
    assert "超时" in (tools["bash"].description() or "")
    assert "原子" in (tools["write_file"].description() or "")
    assert "越界" in (tools["read_file"].description() or "")
    assert "产物清单" in (tools["write_artifact"].description() or "")


def test_read_write_reject_workspace_escape(tmp_path):
    """越界拒绝（守卫单一来源 Workspace._safe_path——巡检补测）。"""
    from wuxing.tools.fs_tools import ReadFileTool, WriteFileTool
    from wuxing.workspace import Workspace

    ws = Workspace(tmp_path)
    r = ReadFileTool(ws).execute(path="../outside.txt")
    assert r.status == "blocked"
    w = WriteFileTool(ws).execute(path="../outside.txt", content="x")
    assert w.status == "blocked"


def test_write_file_uses_atomic_write(tmp_path, monkeypatch):
    """write_file 走 atomic_write_text（巡检修复：原实现直写 p.write_text）。"""
    from wuxing.tools import fs_tools
    from wuxing.workspace import Workspace

    calls = {"n": 0}
    orig = fs_tools.atomic_write_text

    def _spy(path, text, **kw):
        calls["n"] += 1
        return orig(path, text, **kw)

    monkeypatch.setattr(fs_tools, "atomic_write_text", _spy)
    r = fs_tools.WriteFileTool(Workspace(tmp_path)).execute(
        path="a/b.txt", content="内容")
    assert r.status == "ok" and calls["n"] == 1
    assert (tmp_path / "a" / "b.txt").read_text(encoding="utf-8") == "内容"
    assert not (tmp_path / "a" / "b.txt.tmp").exists()
