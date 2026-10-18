"""系统对话框桥（R1-1/R2-1）：子进程不弹控制台窗口（pythonw + CREATE_NO_WINDOW）。

用户反馈（2026-09-19）：点「参考文件」先闪命令行再弹资源管理器 → 修复口径：
1) Windows 下优先同目录 pythonw.exe（无控制台子系统）；
2) 始终带 CREATE_NO_WINDOW 创建标志（双保险——python.exe 也不弹窗）。
"""
import pathlib
import subprocess
import sys
from types import SimpleNamespace

from wuxing.shell.web import native_dialog


def test_pick_prefers_pythonw_and_no_window(monkeypatch):
    captured = {}

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return SimpleNamespace(stdout="/tmp/a.md\n/tmp/b.md\n", stderr="", returncode=0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    paths = native_dialog.pick("files")
    assert paths == ["/tmp/a.md", "/tmp/b.md"]
    exe = captured["argv"][0]
    if sys.platform == "win32":
        pythonw = pathlib.Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            assert exe == str(pythonw), "应优先 pythonw.exe（不弹控制台）"
        assert captured["kwargs"].get("creationflags", 0) & 0x08000000, \
            "必须带 CREATE_NO_WINDOW"
    else:
        assert exe == sys.executable


def test_pick_unknown_kind_raises():
    try:
        native_dialog.pick("nope")
    except ValueError:
        # 期望 ValueError：走到本分支即通过（无异常则上行 raise 失败）
        return
    raise AssertionError("expected ValueError")
