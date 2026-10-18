"""TDD · Wave-1 Task B3：bash 体验优化（PATH 注入 / 描述改口 / 超限落盘）。

用户裁决 2026-10-01：不切换默认 shell（保持 shell=True/cmd），只做
PATH 注入（git-bash unix 工具 + rg 目录）+ 描述改口 + 超限落盘（复用 G6）。
"""
from wuxing.workspace import Workspace


def test_bash_env_injects_unix_tools_and_rg(tmp_path, monkeypatch):
    from wuxing.tools import bash_tool
    monkeypatch.setattr(bash_tool, "_unix_tool_dirs",
                        lambda: [r"C:\Program Files\Git\usr\bin"])
    t = bash_tool.BashTool(Workspace(tmp_path), sandbox_enabled=True)
    env = t._clean_env()
    assert env.get("PATH", "").startswith(r"C:\Program Files\Git\usr\bin")


def test_bash_description_mentions_posix_and_grep(tmp_path):
    from wuxing.tools import bash_tool
    t = bash_tool.BashTool(Workspace(tmp_path))
    desc = t.description()
    assert "grep" in desc and "bash" in desc and "勿用" not in desc


def test_bash_spills_truncated_output(tmp_path):
    from wuxing.tools import bash_tool
    t = bash_tool.BashTool(Workspace(tmp_path))
    big = "x" * (bash_tool.MAX_OUTPUT + 500)
    content, note = t._truncate_with_spill(big, unit="")
    assert note and ".wuxing/truncated/" in note
    assert len(content) <= bash_tool.MAX_OUTPUT + 200


def test_env_whitelist_case_insensitive(tmp_path):
    from wuxing.tools import bash_tool
    t = bash_tool.BashTool(Workspace(tmp_path))
    env = t._clean_env(environ={"SYSTEMROOT": r"C:\Windows", "PATH": r"C:\x",
                                "SECRET_TOKEN": "sk-leak"})
    assert any(k.upper() == "SYSTEMROOT" for k in env)   # 变体保留（不丢弃）
    assert "SECRET_TOKEN" not in env                      # 敏感仍剥离


def test_env_fallback_systemroot_not_duplicated(tmp_path):
    from wuxing.tools import bash_tool
    t = bash_tool.BashTool(Workspace(tmp_path))
    env = t._clean_env(environ={"systemroot": r"C:\WIN", "PATH": r"C:\x"})
    assert [k for k in env if k.lower() == "systemroot"] == ["systemroot"]
