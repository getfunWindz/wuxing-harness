"""R3-2：bash 原生沙箱——开关语义（环境剥离 / 关闭继承）。"""

from wuxing.tools.bash_tool import BashTool


class _WS:
    def __init__(self, root):
        self.root = root


def test_sandbox_on_scrubs_env(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "sk-should-not-pass")
    t = BashTool(_WS(tmp_path), sandbox_enabled=True)
    env = t._clean_env()
    assert "SECRET_TOKEN" not in env


def test_sandbox_on_runs_command(tmp_path):
    t = BashTool(_WS(tmp_path), sandbox_enabled=True)
    r = t.execute("echo hi")
    assert r.status == "ok" and "hi" in r.content


def test_sandbox_off_keeps_flag_and_description(tmp_path):
    t = BashTool(_WS(tmp_path), sandbox_enabled=False)
    assert t._sandbox_enabled is False
    assert "关闭" in t.description()


def test_description_modes(tmp_path):
    desc = BashTool(_WS(tmp_path)).description()
    assert "开启" in desc and "网络允许" in desc
