"""G6：截断全文落盘（序号/落盘/双上限清理）（设计 §6.1）。"""
import pathlib
import threading

import pytest


def _dump(workdir, text, unit=""):
    from wuxing.truncate_dump import dump_truncated
    return dump_truncated(workdir, text, unit=unit)


def _files(workdir):
    d = pathlib.Path(workdir) / ".wuxing" / "truncated"
    return sorted(p.name for p in d.iterdir() if p.is_file())


def test_dump_seq_monotonic_and_content(tmp_path):
    """序号单调递增；内容字节一致；返回 posix 相对路径。"""
    p1 = _dump(tmp_path, "第一份全文", unit="F-0001")
    p2 = _dump(tmp_path, "第二份全文", unit="F-0002")
    p3 = _dump(tmp_path, "第三份", unit="F-0001")
    assert p1 == ".wuxing/truncated/000001-F-0001.txt"
    assert p2 == ".wuxing/truncated/000002-F-0002.txt"
    assert p3 == ".wuxing/truncated/000003-F-0001.txt"
    assert (tmp_path / p1).read_text(encoding="utf-8") == "第一份全文"


def test_dump_prune_by_count_oldest_first(tmp_path):
    """数量上限：超限时从最旧（最小序号）先删。"""
    from wuxing import truncate_dump as td
    for i in range(td.MAX_FILES + 5):
        _dump(tmp_path, f"内容{i}", unit="F-a")
    names = _files(tmp_path)
    assert len(names) == td.MAX_FILES
    assert names[0] == "000006-F-a.txt"  # 最早 5 个被删
    assert names[-1] == f"{td.MAX_FILES + 5:06d}-F-a.txt"


def test_dump_prune_by_bytes(tmp_path, monkeypatch):
    """字节上限：超限时从最旧先删直至满足。"""
    from wuxing import truncate_dump as td
    monkeypatch.setattr(td, "MAX_BYTES", 12)
    for i in range(6):
        _dump(tmp_path, "0123456789", unit="F-a")  # 每个 10 字节
    d = tmp_path / ".wuxing" / "truncated"
    total = sum(p.stat().st_size for p in d.iterdir() if p.is_file())
    assert total <= 12
    assert _files(tmp_path) == ["000006-F-a.txt"]


def test_dump_ignores_bad_names(tmp_path):
    """坏名文件：不参与序号分配、不被清理误删。"""
    d = tmp_path / ".wuxing" / "truncated"
    d.mkdir(parents=True)
    (d / "junk.txt").write_text("x", encoding="utf-8")
    (d / "00000x-bad.txt").write_text("x", encoding="utf-8")
    p = _dump(tmp_path, "正文", unit="F-a")
    assert p is not None and p.endswith("000001-F-a.txt")
    assert (d / "junk.txt").exists() and (d / "00000x-bad.txt").exists()


def test_dump_failure_returns_none(tmp_path):
    """.wuxing 预置为文件（mkdir 失败）→ 返回 None 不抛。"""
    (tmp_path / ".wuxing").write_text("not a dir", encoding="utf-8")
    assert _dump(tmp_path, "正文") is None


def test_dump_concurrent_no_duplicate_seq(tmp_path):
    """并发落盘：序号唯一（O_EXCL + 目录锁）。"""
    results = []
    lock = threading.Lock()

    def _work(i):
        p = _dump(tmp_path, f"并发内容{i}", unit="F-a")
        with lock:
            results.append(p)

    threads = [threading.Thread(target=_work, args=(i,)) for i in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seqs = [p.split("/")[-1].split("-")[0] for p in results if p is not None]
    assert len(seqs) == 12
    assert len(set(seqs)) == 12


# ---- Task 2：context 回调（压缩前全文 → 落盘）----

def _msg(content):
    return [{"role": "user", "content": content}]


def test_compress_callback_only_on_truncation():
    """未截断不回调；截断回调收到压缩前全文；注记含返回路径。"""
    from wuxing.context import compress_tool_results
    calls = []

    def cb(full):
        calls.append(full)
        return ".wuxing/truncated/000001-F-a.txt"

    small = '<tool_result source="read_file">短内容</tool_result>'
    compress_tool_results(_msg(small), max_chars=1000, on_truncate=cb)
    assert calls == []
    big = '<tool_result source="read_file">' + "大" * 200 + "</tool_result>"
    out = compress_tool_results(_msg(big), max_chars=100, on_truncate=cb)
    assert len(calls) == 1 and calls[0] == big
    assert "全文：.wuxing/truncated/000001-F-a.txt" in out[0]["content"]


def test_compress_callback_failure_keeps_note():
    """回调抛异常 → 压缩照常、注记不含路径（落盘失败不阻断）。"""
    from wuxing.context import compress_tool_results

    def cb(full):
        raise RuntimeError("disk full")

    big = '<tool_result source="read_file">' + "大" * 200 + "</tool_result>"
    out = compress_tool_results(_msg(big), max_chars=100, on_truncate=cb)
    text = out[0]["content"]
    assert "已压缩" in text and "全文：" not in text


def test_compress_callback_returns_none():
    """回调返回 None（落盘失败）→ 注记不带路径。"""
    from wuxing.context import compress_tool_results
    big = '<tool_result source="read_file">' + "大" * 200 + "</tool_result>"
    out = compress_tool_results(_msg(big), max_chars=100,
                                on_truncate=lambda full: None)
    assert "已压缩" in out[0]["content"] and "全文：" not in out[0]["content"]


def test_compress_no_callback_unchanged():
    """无回调 → 既有压缩注记字节不变（零回归）。"""
    from wuxing.context import compress_tool_results
    big = '<tool_result source="read_file">' + "大" * 200 + "</tool_result>"
    a = compress_tool_results(_msg(big), max_chars=100)
    b = compress_tool_results(_msg(big), max_chars=100, on_truncate=None)
    assert a[0]["content"] == b[0]["content"]
    assert "全文：" not in a[0]["content"]


# ---- Task 3：守卫例外 + runner 接线 ----

def test_safe_path_allows_truncated_dir(tmp_path):
    """守卫例外：.wuxing/truncated 可读；其余 .wuxing 仍拒；逃逸仍拒。"""
    from wuxing.workspace import Workspace
    ws = Workspace(tmp_path)
    rel = _dump(tmp_path, "正文", unit="F-a")
    assert rel is not None
    assert ws._safe_path(rel).is_file()
    (tmp_path / ".wuxing" / "task_state.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError):
        ws._safe_path(".wuxing/task_state.json")
    with pytest.raises(ValueError):
        ws._safe_path("../outside.txt")


def test_read_file_can_read_dump(tmp_path):
    """读回：read_file 可读落盘全文（既有段读能力不变）。"""
    from wuxing.tools.fs_tools import ReadFileTool
    from wuxing.workspace import Workspace
    ws = Workspace(tmp_path)
    rel = _dump(tmp_path, "全文内容", unit="F-a")
    res = ReadFileTool(ws).execute(path=rel)
    assert res.status == "ok" and res.content == "全文内容"


def test_append_round_history_dumps_and_traces(tmp_path):
    """接线：大工具结果 → 全文落盘（字节级）+ 注记含路径 + trace 记录。"""
    from wuxing.config import EngineConfig
    from wuxing.runner import Runner
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace
    ws = Workspace(tmp_path)
    trace = TraceLogger(tmp_path / ".wuxing" / "trace.jsonl")
    runner = Runner(EngineConfig(), None, ws, None, [], trace=trace)
    runner._max_tool_chars = 200
    runner._messages = []
    big = "[tool] ext_tool: " + "x" * 5000  # 未列专属上限 → 走 max_chars
    runner._append_round_history("本轮文本", [big], unit_id="F-0001")
    files = sorted((tmp_path / ".wuxing" / "truncated").glob("*.txt"))
    assert len(files) == 1
    full = files[0].read_text(encoding="utf-8")
    assert "x" * 5000 in full  # 压缩前全文
    combined = "\n".join(str(m.get("content", "")) for m in runner._messages)
    assert "全文：.wuxing/truncated/" in combined
    rows = trace.load()
    assert any(r["event"] == "truncate_dump" and r.get("path")
               and r.get("chars") for r in rows)
