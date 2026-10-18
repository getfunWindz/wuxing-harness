from wuxing.danger_guard import guard_command


def test_rm_rf_blocked():
    assert guard_command("rm -rf /") == False
    assert guard_command("rm -rf C:/Windows") == False

def test_rm_normal_allowed():
    assert guard_command("rm tmp.txt") == True
    assert guard_command("rm -rf build/") == True   # 工作区相对路径放行

def test_sudo_blocked():
    assert guard_command("sudo rm -rf /") == False
    assert guard_command("sudo apt install x") == False  # 保守：sudo 一律拦

def test_mkdir_echo_allowed():
    assert guard_command("mkdir -p a/b") == True
    assert guard_command("echo hi") == True


# ── BOX-M3（2026-09-28）：持续沉淀——非删除类破坏命令 ──

def test_m3_destructive_commands_blocked():
    assert guard_command("format C: /q") == False
    assert guard_command("shutdown /s /t 0") == False
    assert guard_command("shutdown -h now") == False
    assert guard_command("reg delete HKLM\\Software\\Foo /f") == False
    assert guard_command("mkfs.ext4 /dev/sda1") == False
    assert guard_command("dd if=/dev/zero of=/dev/sda bs=1M") == False


def test_m3_non_destructive_commands_allowed():
    """防误伤：无参数形态的系统词（文案/提交信息）不得拦。"""
    assert guard_command("echo shutdown later") == True
    assert guard_command("git commit -m 'fix reboot handling'") == True
    assert guard_command("python -m pip install black && black --check .") == True

def test_windows_drive_write_blocked():
    assert guard_command("del /q C:\\Users") == False

def test_rm_relative_slash_paths_allowed():
    # 审查发现（实弹复现）：旧正则误拦相对路径——rm build/、rm src/old.py 被拦
    assert guard_command("rm build/") == True
    assert guard_command("rm src/old.py") == True
    assert guard_command("rm -rf dist/tmp.txt") == True

def test_rm_tilde_home_blocked():
    # 保守新增：~ 家目录删除同样危险（cwd 沙箱无法兜住）
    assert guard_command("rm -rf ~") == False
    assert guard_command("rm -rf ~/x") == False


# ── 2026-09-27 四因素审查补齐：守卫覆盖缺口（实弹验证后加固）──

def test_rm_relative_traversal_blocked():
    """相对路径逃逸（.. 段）——cwd 沙箱兜不住，必须拦。

    原版仅拦绝对路径且注释声称「相对删除无逃逸风险」——实为不成立：
    `rm -rf ../..` 以相对形态删除工作区之外。"""
    assert guard_command("rm -rf ..") == False
    assert guard_command("rm -rf ../..") == False
    assert guard_command("rm -rf ../../outside") == False
    assert guard_command("rm -rf ..\\..\\..") == False
    assert guard_command("rm -rf ./../x") == False
    assert guard_command("rm -rf a/../b") == False


def test_rm_double_dot_filename_allowed():
    """文件名中的连续点不是 .. 路径段——不得误伤。"""
    assert guard_command("rm notes..txt") == True
    assert guard_command("rm a..b/c.txt") == True


def test_cd_and_navigation_allowed():
    """导航（cd ..）不属危险删除——不得误伤。"""
    assert guard_command("cd ..") == True
    assert guard_command("cd ../other") == True
    assert guard_command("dir ..") == True


def test_windows_del_recursive_any_flag_order_blocked():
    """del 递归/静默标志任意顺序。

    原模式 `del\\s+/q` 仅匹配 /q 紧跟 del——常见写法 `del /s /q` 被放行。"""
    assert guard_command("del /s /q somedir") == False
    assert guard_command("del /q /s somedir") == False
    assert guard_command("del /s somedir") == False


def test_windows_rd_alias_blocked():
    """rd 是 rmdir 的别名——递归删除同样拦。"""
    assert guard_command("rd /s /q somedir") == False
    assert guard_command("rd /s somedir") == False


def test_powershell_remove_item_blocked():
    """PowerShell 删除（-Recurse/-Force）——原规则完全未覆盖。"""
    assert guard_command('powershell -Command "Remove-Item -Recurse -Force ."') == False
    assert guard_command("Remove-Item -Recurse x") == False
    assert guard_command("Remove-Item -Force x") == False


def test_plain_del_and_rmdir_allowed():
    """无递归/静默标志的相对删除与 rm 同宽（历史口径保持）。"""
    assert guard_command("del file.txt") == True
    assert guard_command("rmdir emptydir") == True


def test_full_access_allows_traversal_delete():
    """SEC3：(i)——full-access 放宽路径类约束（相对逃逸删除放行）。"""
    from wuxing.danger_guard import check_command
    assert check_command("rm ../x") is not None
    assert check_command("rm ../x", profile="full-access") is None
    assert guard_command("rm ../x", profile="full-access") is True


def test_full_access_blacklist_still_blocked():
    """危险命令黑名单不豁免（设计 §4.1）。"""
    from wuxing.danger_guard import check_command
    for cmd in ("rm -rf /", "sudo x", "format C:", "shutdown /s",
                "reg delete HKCU\\x /f", "mkfs.ext4 /dev/sda1",
                "dd if=x of=/dev/sda"):
        assert check_command(cmd, profile="full-access") is not None, cmd
