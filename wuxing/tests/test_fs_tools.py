import pathlib
import tempfile

from wuxing.tools.fs_tools import ReadFileTool, WriteFileTool
from wuxing.workspace import Workspace


def _mk():
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return ws, WriteFileTool(ws), ReadFileTool(ws)

def test_write_read_roundtrip():
    ws, w, r = _mk()
    w.execute(path="a.txt", content="hello")
    assert r.execute(path="a.txt").content == "hello"
    assert (ws.root / "a.txt").read_text(encoding="utf-8") == "hello"

def test_write_creates_parent_dirs():
    ws, w, _r = _mk()
    w.execute(path="sub/dir/b.txt", content="x")
    assert (ws.root / "sub/dir/b.txt").exists()

def test_read_missing_returns_none_marker():
    _ws, _w, r = _mk()
    assert r.execute(path="nope.txt").content == "not found"

def test_path_escape_blocked():
    _ws, w, r = _mk()
    # 逃逸：../ 越出工作区 → 写被阻断
    out = w.execute(path="../escape.txt", content="x")
    assert out.status == "blocked"
    out2 = r.execute(path="../../proc/self/cmdline")
    assert out2.status == "blocked"  # 逃逸读=blocked（结构化）


def test_read_file_offset_limit_segmented():
    """D：大文件分段读——offset（1 起）/limit（行数）+ 范围头（模型有方位感）。"""
    _ws, w, r = _mk()
    w.execute(path="lines.txt", content="\n".join(f"L{i}" for i in range(1, 11)))
    seg = r.execute(path="lines.txt", offset=3, limit=2)
    assert seg.status == "ok"
    assert seg.content.startswith("[lines 3-4 of 10]"), seg.content[:60]
    assert "L3" in seg.content and "L4" in seg.content
    assert "L5" not in seg.content


def test_read_file_offset_beyond_eof_clear_message():
    """越界给出明确提示（不是静默空内容——防模型猜）。"""
    _ws, w, r = _mk()
    w.execute(path="lines.txt", content="L1\nL2")
    seg = r.execute(path="lines.txt", offset=5, limit=2)
    assert "no lines" in seg.content, seg.content[:80]


def test_read_file_full_without_offset_unchanged():
    """不传 offset/limit 时行为不变（零扰动——向后兼容）。"""
    _ws, w, r = _mk()
    w.execute(path="a.txt", content="hello")
    assert r.execute(path="a.txt").content == "hello"
