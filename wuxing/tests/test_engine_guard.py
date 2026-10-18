import pathlib
import tempfile

from wuxing.danger_guard import guard_command
from wuxing.engine import Engine
from wuxing.tools.base import ToolRegistry
from wuxing.tools.bash_tool import BashTool
from wuxing.workspace import Workspace


def test_registry_guard_blocks_dangerous_bash():
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = ToolRegistry([BashTool(ws)])
    # guard 注入：execute 前校验（registry.execute 统一入口）
    reg.set_guard(lambda name, kwargs: guard_command(kwargs.get("command", "")))
    out = reg.execute("bash", command="rm -rf /")
    assert out.status == "blocked"

def test_engine_installs_danger_guard():
    eng = Engine(workdir=pathlib.Path(tempfile.mkdtemp()), auto_confirm=True)
    # Engine 装配 guard：bash 通过 registry.execute 被拦
    assert eng.tools.get("bash") is not None
    assert eng.tools._guard is not None
    out = eng.tools.execute("bash", command="sudo rm -rf /")
    assert out.status == "blocked"
