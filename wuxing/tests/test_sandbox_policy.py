"""R3-2：原生沙箱策略——开关 + 策略行（字节稳定）。"""
from wuxing.sandbox import INTEGRITY_NATIVE, NETWORK_POLICY, describe, policy_line


def test_policy_line_on():
    line = policy_line(True, "C:/ws")
    assert line.startswith("sandbox: on")
    assert "partial" in line
    assert NETWORK_POLICY in line
    assert "C:/ws" in line


def test_policy_line_off():
    assert policy_line(False, "C:/ws") == "sandbox: off"


def test_policy_line_byte_stable():
    assert policy_line(True, "C:/ws") == policy_line(True, "C:/ws")


def test_describe():
    assert "partial" in describe(True)
    assert "开启" in describe(True)
    assert "关闭" in describe(False)
    assert INTEGRITY_NATIVE == "partial"


def test_container_policy_line_network_runtime_controlled():
    """CU5（E2-4）：容器档网络文案诚实化——由模板/运行时决定（非 allowed）。"""
    line = policy_line(True, "C:/ws", mode="container",
                       template="docker run --network none -v {workdir}:/ws {cmd_b64}")
    assert "mode: container" in line
    assert "network: runtime-controlled" in line
    assert NETWORK_POLICY in policy_line(True, "C:/ws")  # 原生档如实 allowed
