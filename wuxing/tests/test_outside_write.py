"""BOX-1：bash 面工作区外写入监控——静态检测（保守；审计不硬阻断）。

口径（2026-09-30）：检测 + 可见提示（不硬阻断——bash 合法依赖外部写入，
硬拦误伤成本高；危险类命令仍由 danger_guard 硬拦截）。
盲区（如实声明）：变量展开（$TMP/%TEMP%）、脚本内动态写入、管道下游。
"""
from wuxing.outside_write import detect_outside_writes


def test_inside_relative_write_not_flagged(tmp_path):
    assert detect_outside_writes("echo hi > out.txt", tmp_path) == []


def test_parent_escape_flagged(tmp_path):
    assert detect_outside_writes("echo hi > ../escape.txt", tmp_path)


def test_append_redirect_flagged(tmp_path):
    assert detect_outside_writes("printf x >> ../log.txt", tmp_path)


def test_absolute_outside_flagged(tmp_path):
    outside = tmp_path.parent / "x.txt"
    assert detect_outside_writes(f"echo hi > {outside}", tmp_path)


def test_absolute_inside_not_flagged(tmp_path):
    inside = tmp_path / "in.txt"
    assert detect_outside_writes(f"echo hi > {inside}", tmp_path) == []


def test_quoted_target_flagged(tmp_path):
    assert detect_outside_writes('echo hi > "../quoted x.txt"', tmp_path)


def test_null_targets_excluded(tmp_path):
    assert detect_outside_writes("echo x > /dev/null", tmp_path) == []
    assert detect_outside_writes("echo x > NUL", tmp_path) == []


def test_write_command_absolute_path_flagged(tmp_path):
    outside = tmp_path.parent / "y.txt"
    assert detect_outside_writes(f"cp a.txt {outside}", tmp_path)


def test_mkdir_parent_flagged(tmp_path):
    assert detect_outside_writes("mkdir ../newdir", tmp_path)


def test_powershell_set_content_flagged(tmp_path):
    assert detect_outside_writes(
        'Set-Content -Path "../x.txt" -Value hi', tmp_path)


def test_compound_command_flagged(tmp_path):
    assert detect_outside_writes("echo a && echo b > ../x.txt", tmp_path)


def test_quoted_literal_gt_not_flagged(tmp_path):
    """C4（E0-4）：引号内字面 `>` 不误报（审计噪声边界）。"""
    assert detect_outside_writes("echo 'a > /outside'", tmp_path) == []
    assert detect_outside_writes('echo "b > /tmp/xx"', tmp_path) == []


def test_no_space_redirect_flagged(tmp_path):
    """C4：无空格重定向（x>/path）不得漏报。"""
    outside = tmp_path.parent / "nospace.txt"
    assert detect_outside_writes(f"echo x>{outside}", tmp_path)
    assert detect_outside_writes("printf x>>../nospace2.txt", tmp_path)


def test_fd_duplicate_not_flagged(tmp_path):
    """C4：`2>&1` 等 fd 复制不是路径写入——不误报。"""
    assert detect_outside_writes("echo hi > out.txt 2>&1", tmp_path) == []
    assert detect_outside_writes("cmd >out.txt 2>&1", tmp_path) == []


def test_variable_expansion_is_documented_blind_spot(tmp_path):
    """变量展开静态不可知——不误报（如实声明为盲区）。"""
    assert detect_outside_writes("echo x > $TEMP/x.txt", tmp_path) == []
    assert detect_outside_writes('echo x > "%TEMP%\\x.txt"', tmp_path) == []
