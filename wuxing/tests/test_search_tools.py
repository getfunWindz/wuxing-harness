"""TDD · Wave-1 Task B1/B2：搜索工具（grep/glob——优先 ripgrep，缺失时纯 Python 兜底）。

用户裁决 2026-10-01（壳体验对照调研）：grep 补全——模型真实倾向 bash，
既补全 grep 保证完整性，工具面也要可用（rg 优先 + 兜底，无 rg 环境不失效）。
"""
from wuxing.workspace import Workspace


def _mk_ws(tmp_path):
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "src" / "a.py").write_text("import os\nneedle = 1\n",
                                           encoding="utf-8")
    (tmp_path / "b.md").write_text("no match here\n", encoding="utf-8")
    (tmp_path / ".git").mkdir(exist_ok=True)
    (tmp_path / ".git" / "cfg").write_text("needle", encoding="utf-8")
    return Workspace(tmp_path)


def test_grep_finds_and_skips_vcs(tmp_path):
    from wuxing.tools.search_tools import GrepTool
    r = GrepTool(_mk_ws(tmp_path)).execute(pattern="needle")
    assert r.status == "ok" and "src/a.py:2" in r.content
    assert ".git" not in r.content


def test_grep_include_and_caps(tmp_path):
    from wuxing.tools.search_tools import GrepTool
    r = GrepTool(_mk_ws(tmp_path)).execute(pattern="needle", include="*.md")
    assert "No matches" in r.content
    r2 = GrepTool(_mk_ws(tmp_path), max_matches=1).execute(pattern="e")
    assert r2.status == "ok" and "more matches" in r2.content


def test_grep_invalid_pattern(tmp_path):
    from wuxing.tools.search_tools import GrepTool
    r = GrepTool(_mk_ws(tmp_path)).execute(pattern="([")
    assert r.status == "error" and "invalid pattern" in (r.error or "")


def test_grep_outside_blocked(tmp_path):
    from wuxing.tools.search_tools import GrepTool
    r = GrepTool(_mk_ws(tmp_path)).execute(pattern="x", path="../")
    assert r.status in ("error", "blocked")


def test_glob_finds_files_only(tmp_path):
    """Task B2：glob 只出文件（目录不出），跳 VCS；无匹配 → No files。"""
    from wuxing.tools.search_tools import GlobTool
    ws = _mk_ws(tmp_path)
    r = GlobTool(ws).execute(pattern="**/*.py")
    assert r.status == "ok"
    assert "src/a.py" in r.content and "b.md" not in r.content
    assert ".git" not in r.content
    assert "No files" in GlobTool(ws).execute(pattern="**/*.rs").content
