import pathlib
import tempfile

from wuxing.tools.bash_tool import BashTool
from wuxing.workspace import Workspace


def _mk():
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    return ws, BashTool(ws, timeout=10)

def test_bash_echo():
    _ws, b = _mk()
    out = b.execute(command="echo hello-wuxing")
    assert out.status == "ok"
    assert "hello-wuxing" in out.content

def test_bash_cwd_is_workspace():
    ws, b = _mk()
    out = b.execute(command="pwd")
    assert out.status == "ok"
    # Windows 下 git-bash 输出 POSIX 路径（/c/...），Python 侧为 C:\...
    # 统一比较：转成同构后验证 cwd 落在工作区内
    root_str = str(pathlib.Path(ws.root).resolve()).replace("\\", "/").lower()
    # 提取盘符后同时接受 /c/ 与 C: 两种前缀表示
    drive = root_str[0]  # 盘符字母
    norm_out = out.content.strip().replace("\\", "/").lower()
    candidates = [root_str, f"/{drive.lower()}" + root_str[root_str.index(":") + 1:]]
    assert any(c in norm_out for c in candidates)

def test_bash_timeout_kills():
    _ws, b = _mk()
    out = b.execute(command="python -c \"import time; time.sleep(30)\"")
    assert out.status == "error"
    assert "timeout" in (out.error or "").lower()

def test_bash_output_truncated():
    _ws, b = _mk()
    out = b.execute(command="python -c \"print('x'*100000)\"")
    assert out.status == "ok"
    from wuxing.tools import bash_tool
    assert len(out.content) <= bash_tool.MAX_OUTPUT + 200  # 截断护栏（+落盘注记）


def test_bash_tool_handles_utf8_output():
    """G3：bash 工具必须宽容解码子进程输出——Windows 默认 GBK 读取 UTF-8 中文
    输出会 UnicodeDecodeError 崩溃（评测实测：任务中途工具崩溃→超时浪费）。"""
    import pathlib
    import tempfile

    from wuxing.tools.bash_tool import BashTool
    from wuxing.workspace import Workspace

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    tool = BashTool(ws)
    # Python 子进程输出 UTF-8 中文（PYTHONIOENCODING=utf-8 在 env 白名单）
    res = tool.execute(command='python -c "print(\'中文输出测试\')"')
    assert res.status == "ok", f"UTF-8 输出不得崩溃：{res.error}"
    assert "中文输出测试" in res.content, f"输出内容必须可读：{res.content[:120]!r}"


def test_bash_timeout_kills_process_tree(tmp_path):
    """2026-09-27 审查实锤：超时必须终止**进程树**。

    只杀 shell（cmd）会留下孤儿子进程继续改写工作区——原实现返回
    "command killed" 但子进程照常运行（proof 文件在超时后被写出）。"""
    import sys
    import time
    ws = Workspace(tmp_path)
    tool = BashTool(ws, timeout=1.2)
    proof = tmp_path / "tree_proof.txt"
    code = (f"import time; time.sleep(3.5); "
            f"open('{proof.as_posix()}', 'w', encoding='utf-8').write('alive')")
    out = tool.execute(command=f'"{sys.executable}" -c "{code}"')
    assert out.status == "error"
    assert "timeout" in (out.error or "").lower()
    time.sleep(4.0)  # 超时点 +1.2s → 合计 5.2s > 3.5s 写入点
    assert not proof.exists(), "超时后子进程仍存活（进程树未被终止）"


def test_bash_outside_write_warned(tmp_path):
    """BOX-1：工作区外写入 → 工具结果携带可见 warn（审计不硬阻断）。"""
    ws = Workspace(tmp_path / "ws")
    tool = BashTool(ws, timeout=10)
    res = tool.execute(command="echo hi > ../escape.txt")
    blob = (res.content or "") + (res.error or "")
    assert "[warn]" in blob and "工作区外" in blob, blob[:200]


def test_bash_inside_write_no_warn(tmp_path):
    ws = Workspace(tmp_path / "ws")
    tool = BashTool(ws, timeout=10)
    res = tool.execute(command="echo hi > in.txt")
    assert res.status == "ok"
    assert "[warn]" not in (res.content or "")


def test_bash_posix_shell_pipe_quotes(tmp_path):
    """命令面为 POSIX bash：单引号/管道按 bash 语义解析（E3-4 失败类回归）。"""
    from wuxing import shells
    if shells.resolve_shell().kind == "cmd":
        import pytest
        pytest.skip("环境无 bash（cmd 回退档）")
    from wuxing.workspace import Workspace as _W
    tool = BashTool(_W(tmp_path), timeout=10)
    res = tool.execute(command="printf '%s' 'a b c' | tail -1")
    assert res.status == "ok" and res.content.strip() == "a b c"


def test_bash_posix_expansion_semantics(tmp_path):
    """bash 展开语义（$(( ))）——cmd 下会原样输出字面量（判别性回归）。"""
    from wuxing import shells
    if shells.resolve_shell().kind == "cmd":
        import pytest
        pytest.skip("环境无 bash（cmd 回退档）")
    from wuxing.workspace import Workspace as _W
    tool = BashTool(_W(tmp_path), timeout=10)
    res = tool.execute(command="echo $((2+3))")
    assert res.status == "ok" and "5" in res.content
    assert "$((" not in res.content


def test_taskkill_cmd_absolute_system32():
    import os as _os

    from wuxing.tools import bash_tool
    cmd = bash_tool._taskkill_cmd(1234, system_root=r"C:\Windows")
    assert cmd[0] == _os.path.join(r"C:\Windows", "System32", "taskkill.exe")
    assert cmd[1:] == ["/F", "/T", "/PID", "1234"]


def test_bash_stdin_devnull_no_hang(tmp_path):
    """非交互纪律：继承 stdin 会挂起（cat 无输入）——DEVNULL 立即 EOF。"""
    from wuxing.workspace import Workspace as _W
    tool = BashTool(_W(tmp_path), timeout=5)
    res = tool.execute(command="cat")
    assert res.status == "ok" and "[stderr]" not in (res.content or "")


def test_bash_timeout_param_overrides_default(tmp_path):
    from wuxing.workspace import Workspace as _W
    tool = BashTool(_W(tmp_path), timeout=30)
    out = tool.execute(command='python -c "import time; time.sleep(3)"', timeout=1)
    assert out.status == "error" and "timeout" in (out.error or "").lower()


def test_effective_timeout_clamps():
    import pathlib
    import tempfile

    from wuxing.workspace import Workspace as _W
    tool = BashTool(_W(pathlib.Path(tempfile.mkdtemp())))
    assert tool._effective_timeout(9999) == 600.0
    assert tool._effective_timeout(0) == 1.0
    assert tool._effective_timeout("2.5") == 2.5
    assert tool._effective_timeout(None) == tool._timeout


def test_schema_exposes_timeout_bounds(tmp_path):
    from wuxing.workspace import Workspace as _W
    schema = BashTool(_W(tmp_path)).input_schema()
    t = schema["properties"]["timeout"]
    assert t["minimum"] == 1 and t["maximum"] == 600


def test_bash_config_fields_dual_write():
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS
    cfg = EngineConfig()
    assert cfg.bash_shell_path == "" and cfg.bash_timeout_s == 120.0
    names = {s.name for s in FIELD_SPECS}
    assert {"bash_shell_path", "bash_timeout_s"} <= names


def test_engine_bash_tool_honors_config(tmp_path):
    from wuxing.config import EngineConfig
    from wuxing.engine import Engine
    eng = Engine(cfg=EngineConfig(llm="mock", bash_timeout_s=77.0), workdir=tmp_path)
    assert eng.tools.get("bash")._timeout == 77.0


def test_bash_truncation_keeps_tail(tmp_path):
    from wuxing.workspace import Workspace as _W
    tool = BashTool(_W(tmp_path), timeout=15)
    out = tool.execute(command="python -c \"print('H'*30000); print('TAILMARK-END')\"")
    assert out.status == "ok"
    assert "TAILMARK-END" in out.content          # 末尾保留（构建/测试错误在尾部）
    assert out.content.lstrip().startswith("[")   # 截断注记前缀化


def test_bash_route_info_reports_shell(tmp_path):
    from wuxing.workspace import Workspace as _W
    info = BashTool(_W(tmp_path)).route_info()
    assert info["sandbox_route"] == "native" and "shell" in info


def test_description_mentions_timeout_param(tmp_path):
    from wuxing.workspace import Workspace as _W
    desc = BashTool(_W(tmp_path)).description()
    assert "timeout" in desc and "600" in desc


def test_powershell_utf8_preamble_applied(tmp_path, monkeypatch):
    """PowerShell 档：命令前置 UTF-8 输出编码前导（pi/dsh 双源参考）。"""
    from wuxing import shells as _sh
    from wuxing.tools import bash_tool
    ps = _sh.ShellSpec(path=r"C:\x\powershell.exe",
                       args=("-NoProfile", "-NonInteractive",
                             "-ExecutionPolicy", "Bypass", "-Command"),
                       kind="powershell")
    monkeypatch.setattr(_sh, "resolve_shell", lambda *a, **k: ps)
    t = bash_tool.BashTool(Workspace(tmp_path))
    assert t._compose_command("echo hi").startswith(
        "try { [Console]::OutputEncoding=[System.Text.Encoding]::UTF8 } catch {}")


def test_powershell_optional_live(tmp_path):
    """Windows + 有 PowerShell：显式 powershell 档可执行（参数适配 + 前导）。"""
    import os

    import pytest
    if os.name != "nt":
        pytest.skip("Windows only")
    from wuxing import shells
    try:
        spec = shells.resolve_shell("powershell")
    except ValueError:
        pytest.skip("no PowerShell")
    tool = BashTool(Workspace(tmp_path), shell_path=spec.path, timeout=60)
    res = tool.execute(command='Write-Output "ps_ok"')
    assert res.status == "ok" and "ps_ok" in res.content, res.error or res.content


def test_wsl_optional_live(tmp_path):
    """Windows + 有 WSL 发行版：显式 wsl 档可执行（-e bash -c 形式）。"""
    import os
    import subprocess

    import pytest
    if os.name != "nt":
        pytest.skip("Windows only")
    from wuxing import shells
    try:
        spec = shells.resolve_shell("wsl")
    except ValueError:
        pytest.skip("no wsl.exe")
    probe = subprocess.run([spec.path, "-l", "-q"], capture_output=True,
                           timeout=30, check=False)
    if probe.returncode != 0 or not probe.stdout.decode("utf-16le", "replace").strip():
        pytest.skip("no WSL distro")
    tool = BashTool(Workspace(tmp_path), shell_path="wsl", timeout=120)
    res = tool.execute(command="echo wsl_ok")
    assert res.status == "ok" and "wsl_ok" in res.content, res.error or res.content
