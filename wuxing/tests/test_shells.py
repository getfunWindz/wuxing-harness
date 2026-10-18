"""O1/O4：shell 解析链单测（探测函数注入——不依赖真实机器状态）。"""
import pytest

from wuxing import shells


def test_windows_prefers_git_bash_bin():
    env = {"ProgramFiles": r"C:\Program Files"}
    exists = lambda p: p == r"C:\Program Files\Git\bin\bash.exe"
    spec = shells.resolve_shell(platform="nt", env=env, which=lambda n: None,
                                exists=exists)
    assert spec.path == r"C:\Program Files\Git\bin\bash.exe"
    assert spec.kind == "bash" and spec.args == ("-c",)


def test_windows_git_bash_usr_bin_second():
    env = {"ProgramFiles": r"C:\PF"}
    exists = lambda p: p == r"C:\PF\Git\usr\bin\bash.exe"
    spec = shells.resolve_shell(platform="nt", env=env, which=lambda n: None,
                                exists=exists)
    assert spec.path.endswith(r"usr\bin\bash.exe")


def test_windows_x86_candidates():
    env = {"ProgramFiles(x86)": r"C:\PF86"}
    exists = lambda p: p == r"C:\PF86\Git\bin\bash.exe"
    spec = shells.resolve_shell(platform="nt", env=env, which=lambda n: None,
                                exists=exists)
    assert spec.path == r"C:\PF86\Git\bin\bash.exe"


def test_windows_path_bash_msys2_accepted():
    spec = shells.resolve_shell(platform="nt", env={}, exists=lambda p: False,
                                which=lambda n: r"C:\msys64\usr\bin\bash.exe")
    assert spec.path == r"C:\msys64\usr\bin\bash.exe" and spec.kind == "bash"


@pytest.mark.parametrize("wsl", [
    r"C:\Windows\System32\bash.exe",
    r"C:\Windows\Sysnative\bash.exe",
    r"C:\Users\x\AppData\Local\Microsoft\WindowsApps\bash.exe",
])
def test_windows_wsl_excluded_falls_back_cmd(wsl):
    spec = shells.resolve_shell(platform="nt", env={}, exists=lambda p: False,
                                which=lambda n: wsl)
    assert spec.kind == "cmd" and spec.path == ""


def test_windows_no_bash_falls_back_cmd():
    spec = shells.resolve_shell(platform="nt", env={}, exists=lambda p: False,
                                which=lambda n: None)
    assert spec.kind == "cmd" and spec.path == ""


def test_posix_prefers_bin_bash():
    spec = shells.resolve_shell(platform="posix", which=lambda n: None,
                                exists=lambda p: p == "/bin/bash")
    assert spec.path == "/bin/bash" and spec.kind == "bash"


def test_posix_path_bash_then_sh():
    spec = shells.resolve_shell(platform="posix", exists=lambda p: False,
                                which=lambda n: "/usr/local/bin/bash")
    assert spec.path == "/usr/local/bin/bash"
    spec2 = shells.resolve_shell(platform="posix", exists=lambda p: False,
                                 which=lambda n: None)
    assert spec2.path == "/bin/sh" and spec2.kind == "posix"


def test_custom_path_missing_is_loud():
    with pytest.raises(ValueError, match="bash_shell_path"):
        shells.resolve_shell(choice=r"C:\nope\bash.exe", platform="nt",
                             exists=lambda p: False, which=lambda n: None)


def test_custom_path_ok_kind_from_name():
    spec = shells.resolve_shell(choice=r"C:\tools\bash.exe", platform="nt",
                                exists=lambda p: True, which=lambda n: None)
    assert spec.kind == "bash"
    spec2 = shells.resolve_shell(choice=r"C:\tools\cmd.exe", platform="nt",
                                 exists=lambda p: True, which=lambda n: None)
    assert spec2.kind == "cmd"


def test_is_wsl_bash_classifier():
    assert shells.is_wsl_bash(r"C:\Windows\System32\bash.exe")
    assert not shells.is_wsl_bash(r"C:\Program Files\Git\bin\bash.exe")


# ---------- Phase 1b（用户评审 2026-10-07）：macOS zsh 默认 + WSL/PowerShell/cmd 可选档 ----------

def test_darwin_prefers_zsh():
    spec = shells.resolve_shell(platform="darwin", which=lambda n: None,
                                exists=lambda p: p == "/bin/zsh")
    assert spec.path == "/bin/zsh" and spec.kind == "zsh" and spec.args == ("-c",)


def test_darwin_falls_back_bash_then_sh():
    spec = shells.resolve_shell(platform="darwin", which=lambda n: None,
                                exists=lambda p: p == "/bin/bash")
    assert spec.path == "/bin/bash" and spec.kind == "bash"
    spec2 = shells.resolve_shell(platform="darwin", which=lambda n: None,
                                 exists=lambda p: False)
    assert spec2.path == "/bin/sh" and spec2.kind == "posix"


def test_keyword_git_bash():
    env = {"ProgramFiles": r"C:\PF"}
    spec = shells.resolve_shell("git-bash", platform="win32", env=env,
                                which=lambda n: None,
                                exists=lambda p: p == r"C:\PF\Git\bin\bash.exe")
    assert spec.kind == "bash" and spec.path == r"C:\PF\Git\bin\bash.exe"


def test_keyword_git_bash_missing_loud():
    with pytest.raises(ValueError):
        shells.resolve_shell("git-bash", platform="win32", env={},
                             which=lambda n: None, exists=lambda p: False)


def test_keyword_wsl_locator_and_args():
    env = {"SystemRoot": r"C:\Windows"}
    spec = shells.resolve_shell("wsl", platform="win32", env=env,
                                which=lambda n: None,
                                exists=lambda p: p == r"C:\Windows\System32\wsl.exe")
    assert spec.kind == "wsl" and spec.args == ("-e", "bash", "-c")
    assert spec.command_argv("echo hi") == [
        r"C:\Windows\System32\wsl.exe", "-e", "bash", "-c", "echo hi"]


def test_keyword_powershell_prefers_pwsh():
    spec = shells.resolve_shell(
        "powershell", platform="win32", env={},
        which=lambda n: r"C:\Tools\pwsh.exe" if n in ("pwsh", "pwsh.exe") else None,
        exists=lambda p: True)
    assert spec.kind == "powershell"
    assert spec.args == ("-NoProfile", "-NonInteractive",
                         "-ExecutionPolicy", "Bypass", "-Command")


def test_keyword_powershell_ps51_fallback():
    env = {"SystemRoot": r"C:\Windows"}
    ps51 = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    spec = shells.resolve_shell("powershell", platform="win32", env=env,
                                which=lambda n: None, exists=lambda p: p == ps51)
    assert spec.kind == "powershell" and spec.path == ps51


def test_keyword_cmd_uses_comspec():
    env = {"COMSPEC": r"C:\Windows\system32\cmd.exe"}
    spec = shells.resolve_shell("cmd", platform="win32", env=env,
                                which=lambda n: None, exists=lambda p: True)
    assert spec.kind == "cmd" and spec.args == ("/d", "/s", "/c")


def test_keyword_zsh_bash_sh():
    spec = shells.resolve_shell("zsh", platform="linux", which=lambda n: None,
                                exists=lambda p: p == "/bin/zsh")
    assert spec.kind == "zsh"
    spec2 = shells.resolve_shell("bash", platform="linux", which=lambda n: None,
                                 exists=lambda p: p == "/bin/bash")
    assert spec2.kind == "bash"
    spec3 = shells.resolve_shell("sh", platform="linux", which=lambda n: None,
                                 exists=lambda p: p == "/bin/sh")
    assert spec3.kind == "posix"
    with pytest.raises(ValueError):
        shells.resolve_shell("zsh", platform="linux", which=lambda n: None,
                             exists=lambda p: False)


def test_path_kind_inference_new_kinds():
    spec = shells.resolve_shell(r"C:\x\pwsh.exe", platform="win32",
                                which=lambda n: None, exists=lambda p: True)
    assert spec.kind == "powershell"
    spec2 = shells.resolve_shell(r"C:\x\wsl.exe", platform="win32",
                                 which=lambda n: None, exists=lambda p: True)
    assert spec2.kind == "wsl"
    spec3 = shells.resolve_shell("/usr/local/bin/zsh", platform="linux",
                                 which=lambda n: None, exists=lambda p: True)
    assert spec3.kind == "zsh" and spec3.args == ("-c",)


def test_git_derived_bash_candidate():
    which = lambda n: r"C:\Program Files\Git\cmd\git.exe" if n == "git" else None
    spec = shells.resolve_shell(platform="win32", env={}, which=which,
                                exists=lambda p: p == r"C:\Program Files\Git\bin\bash.exe")
    assert spec.path == r"C:\Program Files\Git\bin\bash.exe"
