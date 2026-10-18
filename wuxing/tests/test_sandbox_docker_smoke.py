"""BOX-M3：真实 Docker 冒烟（门控——不可用跳过，诚实标注）。

本机 Docker 可用且守护进程运行时：容器模板端到端（workdir 挂载 + cmd_b64 解码
+ 容器内执行 + 产物落回工作区）；不可用（CLI 缺失/守护未启/镜像不可运行）→ skip。
"""
import pathlib
import shutil
import subprocess

import pytest

from wuxing.tools.bash_tool import BashTool

DOCKER_TEMPLATE = ("docker run --rm -i -v {workdir}:/ws -w /ws "
                   "alpine sh -c \"echo {cmd_b64} | base64 -d | sh\"")


def _docker_ready() -> bool:
    exe = shutil.which("docker")
    if exe is None:
        return False
    try:
        r = subprocess.run([exe, "info"], capture_output=True, timeout=30,
                           check=False)
    except Exception:
        # Docker 不可用（未装/未启/超时）→ False：冒烟跳过语义
        return False
    return r.returncode == 0


class _WS:
    def __init__(self, root):
        self.root = root


@pytest.mark.skipif(not _docker_ready(), reason="Docker 不可用（CLI/守护进程）")
def test_docker_container_roundtrip(tmp_path):
    """端到端：命令经模板路由进容器；容器写文件经挂载落回工作区。"""
    exe = shutil.which("docker") or "docker"
    probe = subprocess.run([exe, "run", "--rm", "alpine", "true"],
                           capture_output=True, timeout=300, check=False)
    if probe.returncode != 0:
        pytest.skip(f"容器运行探测失败（镜像/网络/权限）："
                    f"{probe.stderr.decode('utf-8', 'replace')[:200]}")
    ws = _WS(tmp_path)
    tool = BashTool(ws, sandbox_mode="container",
                    container_template=DOCKER_TEMPLATE, timeout=180)
    r = tool.execute("echo BOX-M3-OK > /ws/smoke.txt && cat /ws/smoke.txt")
    assert r.status == "ok", r.error
    assert "BOX-M3-OK" in r.content
    out = pathlib.Path(tmp_path) / "smoke.txt"
    assert out.exists(), "容器内写文件必须经挂载落回工作区"
    assert "BOX-M3-OK" in out.read_text(encoding="utf-8")
    assert tool.route_info()["sandbox_route"] == "container"
