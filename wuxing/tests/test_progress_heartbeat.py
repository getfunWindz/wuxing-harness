"""TDD：进度心跳（壳 P1 对齐项⑤）——模型自报进度（progress 事件）。

语义（设计 §4.2）：引擎在长任务上下文注入一次性约定；模型按自定节奏输出
`进度心跳：<阶段>｜预计剩余：<...>` 行 → 解析为 ProgressReport 事件；
不设固定汇报定时器、不做假进度条；未自报则回退事件驱动进度。
"""
import pathlib
import tempfile

from wuxing.llm.tool_results import ToolCallResult


class HeartbeatLlm:
    def name(self):
        return "hb-test"

    def chat(self, messages, tools=None):
        return ToolCallResult(
            text=("进度心跳：编写单元测试｜预计剩余：2 轮\n"
                  "完成声明：任务已完成"),
            tool_calls=[])


def test_prompt_contains_heartbeat_contract_when_enabled():
    from wuxing.config import EngineConfig
    from wuxing.prompt_builder import build_prompt
    from wuxing.registry import DomainRegistry
    reg = DomainRegistry(EngineConfig())
    dom = reg.get("execute")
    p_on = build_prompt(dom, {"goal": "g"}, "任务", [], heartbeat=True)
    p_off = build_prompt(dom, {"goal": "g"}, "任务", [], heartbeat=False)
    assert "进度心跳" in p_on, "启用时必须注入约定"
    assert "进度心跳" not in p_off, "关闭时不得注入"
    # 确定性位置：附于 prompt 末尾（最后一段）
    last_line = [ln for ln in p_on.splitlines() if ln.strip()][-1]
    assert "进度心跳" in last_line, last_line


def test_runner_emits_progress_report_event():
    from wuxing.config import EngineConfig
    from wuxing.registry import DomainRegistry
    from wuxing.runner import Runner
    from wuxing.tools.builtin import BUILTIN_TOOLS
    from wuxing.workspace import Workspace
    events = []
    cfg = EngineConfig(max_loop_rounds=2, max_unit_budget=2)
    ws = Workspace(pathlib.Path(tempfile.mkdtemp()))
    reg = DomainRegistry(cfg)
    reg.activate(["user"])
    r = Runner(cfg, reg, ws, HeartbeatLlm(), BUILTIN_TOOLS(ws))
    r.emit_event = events.append
    r.run_unit("U-1", "user", {"goal": "g"})
    reports = [e for e in events if type(e).__name__ == "ProgressReport"]
    assert reports, [type(e).__name__ for e in events]
    assert reports[0].stage == "编写单元测试"
    assert reports[0].eta == "2 轮"
    assert reports[0].unit_id == "U-1"


def test_progress_heartbeat_config_doublewrite():
    from wuxing.config import EngineConfig
    from wuxing.config_schema import FIELD_SPECS
    assert EngineConfig().progress_heartbeat_enabled is True
    spec = {s.name: s for s in FIELD_SPECS}
    assert "progress_heartbeat_enabled" in spec, "schema 双写"
    assert spec["progress_heartbeat_enabled"].default is True
