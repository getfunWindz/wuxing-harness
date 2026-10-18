import os
import pathlib
import subprocess
import sys
import tempfile


def _isolated_env(home: str) -> dict:
    """子进程隔离（测试确定性）：屏蔽真实 ~/.wuxing 全局配置与凭据。

    真测发现：子进程若不隔离 HOME，会读到用户全局配置（真实模型/智脑）→
    形状化真实 LLM 非确定（有时含 verify 节点 → 无 --auto 时确认门 pending）——
    测试结果依赖用户环境（且会消耗真实 API）。"""
    return {**os.environ, "HOME": home, "USERPROFILE": home,
            "PYTHONIOENCODING": "utf-8"}


def test_cli_headless_runs(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    with tempfile.TemporaryDirectory() as tmp:
        # 显式 utf-8：Windows GBK locale 下 text=True 默认解码器会
        # 无法解码子进程 UTF-8 输出（历史基线漂移——审查报告 A8）
        # --auto：headless 全链路断言（verify 域 always-confirm；无 --auto 时
        # 正确结果就是 pending——确认流程另有专项测试）
        r = subprocess.run(
            [sys.executable, "-m", "wuxing.cli", "run", "写一篇请假邮件",
             "--workdir", tmp, "--auto"],
            capture_output=True, text=True, check=False,
            encoding="utf-8", errors="replace",
            env=_isolated_env(str(home)),
            cwd=str(pathlib.Path(__file__).resolve().parents[2]))
        assert r.returncode == 0, r.stderr
        assert "done" in r.stdout or "任务完成" in r.stdout

def test_cli_tui_subcommand_removed():
    """TUI 彻底删除（用户裁决 2026-09-20）：CLI 无 tui 子命令、wuxing.shell.tui 包不存在。"""
    import importlib.util
    import os
    assert importlib.util.find_spec("wuxing.shell.tui") is None, \
        "TUI 包必须已删除——不得再存在 wuxing.shell.tui"
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    r = subprocess.run(
        [sys.executable, "-m", "wuxing.cli", "--help"],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace", env=env,
        cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert r.returncode == 0, r.stderr
    assert "tui" not in (r.stdout or ""), \
        f"CLI 不得再注册 tui 子命令：{(r.stdout or '')[:300]}"


def test_cli_chat_help_and_single_turn():
    """G4/Task5：chat 子命令（会话式交互——真实测试载体）——help 含会话；单轮 stdin 冒烟。"""
    import os
    import pathlib
    import subprocess
    import sys
    import tempfile
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    # help 存在
    r = subprocess.run([sys.executable, "-m", "wuxing.cli", "chat", "--help"],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=60, env=env, check=False)
    assert r.returncode == 0
    assert "会话" in (r.stdout or ""), f"chat help 必须说明会话语义：{(r.stdout or '')[:200]}"
    # 单轮冒烟（mock LLM——stdin 一行后 EOF 退出；HOME 隔离免串真实配置）
    wd = tempfile.mkdtemp()
    home = tempfile.mkdtemp()
    r2 = subprocess.run(
        [sys.executable, "-m", "wuxing.cli", "chat", "--workdir", wd],
        input="编写一个函数\n", capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
        env=_isolated_env(home), check=False)
    assert r2.returncode == 0, r2.stderr[-400:]
    assert (pathlib.Path(wd) / ".wuxing" / "conversation.jsonl").exists(), \
        "chat 必须持久化会话轮次"


def test_cli_tickets_lists_claims(tmp_path):
    """G8-M1：wuxing tickets 列出票据与认领者。"""
    from wuxing import tickets as tk
    tk.create(tmp_path, title="甲")
    t = tk.create(tmp_path, title="乙")
    tk.publish(tmp_path)
    tk.claim(tmp_path, t["id"], by="sess-a")
    r = subprocess.run(
        [sys.executable, "-m", "wuxing.cli", "tickets",
         "--workdir", str(tmp_path)],
        capture_output=True, text=True, check=False,
        encoding="utf-8", errors="replace",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert r.returncode == 0, r.stderr
    assert "T-2" in r.stdout
    assert "认领：sess-a" in r.stdout


def test_cli_skills_near_dup(tmp_path):
    """技能运维：近义报告（人读 + JSON 双格式；--dir 可指定）。"""
    import json
    sdir = tmp_path / "skills"
    body = "步骤一：先写失败测试。步骤二：最小实现。步骤三：回归。"
    for name in ("pytest-minimal-function", "pytest-minimal-smoke"):
        d = sdir / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: d\n---\n{body}\n",
            encoding="utf-8")
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    base = [sys.executable, "-m", "wuxing.cli", "skills", "near-dup",
            "--dir", str(sdir)]
    r = subprocess.run(base, capture_output=True, text=True, check=False,
                       encoding="utf-8", errors="replace", env=env,
                       cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert r.returncode == 0, r.stderr
    assert "近义簇 1 组" in r.stdout
    assert "pytest-minimal-function" in r.stdout
    r2 = subprocess.run(base + ["--json"], capture_output=True, text=True,
                        check=False, encoding="utf-8", errors="replace",
                        env=env,
                        cwd=str(pathlib.Path(__file__).resolve().parents[2]))
    assert r2.returncode == 0, r2.stderr
    data = json.loads(r2.stdout)
    assert data["skills_total"] == 2 and len(data["clusters"]) == 1
