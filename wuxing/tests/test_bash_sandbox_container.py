"""BOX-2（沙箱与外置容器设计 §3/§4 · M1）：外置容器自定义路径。

覆盖：配置双写校验（container 需模板·占位符强制）· 模板渲染（cmd/cmd_b64/workdir）
· 路由（假运行时证明命令经模板执行）· 失败可见（不回退 native）· 超时杀树 ·
容器档 env 剥离 · route_info（trace/装配可见）。
"""
import base64
import pathlib

import pytest

from wuxing.config import EngineConfig
from wuxing.config_schema import validate_config
from wuxing.sandbox import policy_line, render_container_command, template_hash
from wuxing.tools.bash_tool import BashTool


class _WS:
    def __init__(self, root):
        self.root = root


# 假「容器运行时」：python 解释器 + base64 解码（cmd_b64 无引号难题；{workdir} 仅作尾部占位参数）
PY_ECHO_TPL = ("python -c \"import base64,sys;"
               "print('B64:'+base64.b64decode(sys.argv[1]).decode())\" {cmd_b64} -- {workdir}")


# ---------- 配置面 ----------

def test_default_mode_native_zero_behavior():
    cfg = EngineConfig()
    assert cfg.sandbox_mode == "native"
    assert cfg.sandbox_container_template == ""


def test_validate_config_container_requires_template():
    errors = validate_config({"sandbox_mode": "container"})
    assert any("sandbox_container_template" in e for e in errors), errors


def test_validate_config_template_requires_placeholders():
    errors = validate_config({"sandbox_mode": "container",
                              "sandbox_container_template": "docker run {workdir}"})
    assert any("cmd" in e for e in errors), errors


def test_validate_config_accepts_valid_template():
    errors = validate_config({
        "sandbox_mode": "container",
        "sandbox_container_template":
            "docker run --rm -i -v {workdir}:/ws -w /ws img "
            "sh -c \"echo {cmd_b64} | base64 -d | sh\"",
    })
    assert errors == []


def test_validate_config_rejects_unknown_mode():
    errors = validate_config({"sandbox_mode": "docker"})
    assert any("sandbox_mode" in e for e in errors), errors


def test_load_config_raises_config_error(tmp_path):
    """容器档无模板——load 即校验（ConfigError loud，不静默回退）。"""
    from wuxing.config_loader import ConfigError, load_config
    (tmp_path / "config.jsonc").write_text(
        '{"sandbox_mode": "container"}', encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path, global_config_dir=tmp_path / "_none")


# ---------- 模板面 ----------

def test_render_cmd_b64_roundtrip_unicode_quotes():
    cmd = 'echo "你好 world" && dir'
    out = render_container_command("run -- {cmd_b64} @ {workdir}", "/ws", cmd)
    expected = base64.b64encode(cmd.encode("utf-8")).decode()
    assert out == "run -- " + expected + " @ /ws"


def test_render_workdir_and_cmd_literal():
    assert render_container_command("c={cmd} w={workdir}", "/ws", "ls") == "c=ls w=/ws"


def test_render_rejects_bad_template():
    with pytest.raises(ValueError):
        render_container_command("no placeholders", "/ws", "ls")
    with pytest.raises(ValueError):
        render_container_command("has {workdir} but no cmd", "/ws", "ls")


def test_policy_line_container_mentions_mode_and_hash():
    line = policy_line(True, "/ws", mode="container", template=PY_ECHO_TPL)
    assert "container" in line and template_hash(PY_ECHO_TPL) in line


# ---------- 工具路由面 ----------

def test_container_routes_command_through_template(tmp_path):
    t = BashTool(_WS(tmp_path), sandbox_mode="container",
                 container_template=PY_ECHO_TPL)
    r = t.execute("echo 路由 测试")
    assert r.status == "ok", r.error
    assert "B64:echo 路由 测试" in r.content


def test_container_failure_is_visible_no_fallback(tmp_path):
    tpl = "definitely_missing_runtime_xyz -- {cmd_b64} -- {workdir}"
    t = BashTool(_WS(tmp_path), sandbox_mode="container", container_template=tpl)
    r = t.execute("echo fallback_probe > should_not_exist.txt")
    assert r.status == "error"
    assert r.error.startswith("container:"), r.error
    assert not (tmp_path / "should_not_exist.txt").exists()  # 原生命令未被兜底执行


def test_container_requires_template_in_ctor(tmp_path):
    with pytest.raises(ValueError):
        BashTool(_WS(tmp_path), sandbox_mode="container", container_template="")


def test_container_timeout_kills_and_reports(tmp_path):
    tpl = "python -c \"import time;time.sleep(30)\" {cmd_b64} -- {workdir}"
    t = BashTool(_WS(tmp_path), timeout=1, sandbox_mode="container",
                 container_template=tpl)
    r = t.execute("ignored")
    assert r.status == "error" and "timeout" in r.error


def test_container_strips_env_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("SECRET_TOKEN", "sk-should-not-pass")
    tpl = ("python -c \"import os;"
           "print('SEC='+os.environ.get('SECRET_TOKEN',''))\" {cmd_b64} -- {workdir}")
    t = BashTool(_WS(tmp_path), sandbox_mode="container", container_template=tpl)
    r = t.execute("x")
    assert r.status == "ok", r.error
    assert "SEC=" in r.content and "sk-should-not-pass" not in r.content


def test_route_info_modes(tmp_path):
    info = BashTool(_WS(tmp_path)).route_info()
    assert info["sandbox_route"] == "native" and "shell" in info
    t = BashTool(_WS(tmp_path), sandbox_mode="container",
                 container_template=PY_ECHO_TPL)
    info = t.route_info()
    assert info["sandbox_route"] == "container"
    assert info["sandbox_template_hash"] == template_hash(PY_ECHO_TPL)


def test_default_native_runs_command(tmp_path):
    t = BashTool(_WS(tmp_path))
    r = t.execute("echo hi")
    assert r.status == "ok" and "hi" in r.content


# ---------- runner trace 接线 ----------
def test_assembly_fingerprint_includes_sandbox_config():
    """G5 装配代际：sandbox_mode / 模板进入配置指纹（跨工作区可复现差异）。"""
    from wuxing.assembly import collect_components, fingerprint

    base = EngineConfig()
    boxed = EngineConfig(sandbox_mode="container",
                         sandbox_container_template=PY_ECHO_TPL)
    comp_a = collect_components(base, isolated=False,
                                tool_names=["bash"], skills=None)
    comp_b = collect_components(boxed, isolated=False,
                                tool_names=["bash"], skills=None)
    assert fingerprint(comp_a) != fingerprint(comp_b)


def test_runner_trace_records_sandbox_route(tmp_path):
    """bash 工具的 tool_call trace 应带 sandbox_route（M1 可见性）。"""
    import tempfile

    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.loader import load_tools
    from wuxing.trace import TraceLogger
    from wuxing.workspace import Workspace

    class _BashProbe:
        def __init__(self):
            self.calls = 0

        def name(self):
            return "probe"

        def chat(self, messages, tools=None):
            from wuxing.llm.tool_results import ToolCallResult
            self.calls += 1
            if self.calls == 1:
                return ToolCallResult(text="试 bash", tool_calls=[
                    {"name": "bash", "arguments": {"command": "echo hi"}}])
            return "完成收口"

    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    trace = TraceLogger(tmp_path / "trace.jsonl")
    tools = load_tools(ws, sandbox_mode="container",
                       sandbox_container_template=PY_ECHO_TPL)
    cfg = EngineConfig(max_loop_rounds=4, max_unit_budget=3)
    r = Runner(cfg, DomainRegistry(cfg), ws, _BashProbe(), tools, trace=trace)
    r.run_unit("U-1", "execute", {"goal": "跑一条命令"})
    rows = [x for x in trace.load()
            if x.get("event") == "tool_call" and x.get("name") == "bash"
            and x.get("status") == "ok"]
    assert rows, trace.load()
    assert rows[-1].get("sandbox_route") == "container"
    assert rows[-1].get("sandbox_template_hash") == template_hash(PY_ECHO_TPL)
