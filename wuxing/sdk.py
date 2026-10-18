"""G4 最小运行时 SDK（设计 2026-09-26）：显式装配 + 无隐式继承。

进程内门面：``build_runtime()`` → ``Runtime``（run / resume / cancel）。
隔离语义由 ``Engine(isolated=True)`` 单一实现（设计 §3/§5）：
- 读：不读文件配置 / 用户级技能、扩展、凭据存储；凭据仅显式 provider 或环境变量；
- 写：只落显式 workdir（未给 → 临时目录）；
- 装配：核心五件工具；技能/扩展/MCP/FSC/智脑/设计域全剥离；安全机制保留。

传输无关：Runtime 的公开方法即 B 期 stdio/JSON-RPC 的服务端语义面
（设计 §8）——无全局单例、无 UI 依赖、on_event 可直接映射为协议通知。
"""
import pathlib
from dataclasses import dataclass

from wuxing.config import EngineConfig
from wuxing.engine import Engine
from wuxing.protocols import TaskResult

__all__ = ["CORE_TOOLS", "Runtime", "RuntimeStateError", "SdkResult",
           "build_runtime"]

#: 最小工具面（设计 Q5=A；顺序即默认装配顺序）
CORE_TOOLS = ("bash", "read_file", "write_file", "write_artifact",
              "read_dependency")

#: config_overrides 允许清单（数值/上下文调优；越权键 → ValueError——设计 §6）
_OVERRIDE_ALLOWLIST = frozenset({
    "max_loop_rounds", "max_loop_rounds_hard", "max_unit_budget",
    "max_unit_budget_hard", "fragment_max_attempts", "max_parallel_units",
    "max_parallel_tools", "llm_max_retries", "llm_timeout",
    "context_budget_tokens", "context_max_chars", "task_context_max_chars",
    "conversation_max_chars", "context_golden_pct", "context_managed_pct",
    "model_context_windows", "default_context_window",
    "auto_trim_enabled", "auto_trim_reserve_tokens",
    "auto_compact_llm_enabled", "auto_compact_keep_recent_tokens",
})


class RuntimeStateError(RuntimeError):
    """无可恢复断点（workdir 内无 task_state.json）。"""


@dataclass(frozen=True)
class SdkResult:
    """SDK 任务结果（不可变快照；task_result 为底层引擎结果的逃生舱）。"""

    status: str
    task: str
    report: str
    artifacts: tuple[str, ...]
    workspace: str
    task_result: TaskResult


class Runtime:
    """最小运行时门面（隔离态 Engine 的唯一公开调用面）。"""

    def __init__(self, engine: Engine):
        self.engine = engine
        self.workspace = engine.workdir

    def run(self, task_text, references=None, on_event=None) -> SdkResult:
        """运行任务（同步）；任务失败经 ``status`` 表达，不抛异常。"""
        tr = self.engine.run_task(task_text, on_event=on_event,
                                  references=references)
        return _wrap(tr, self.workspace)

    def resume(self, on_event=None) -> SdkResult:
        """断点续跑；无断点 → :class:`RuntimeStateError`。"""
        if not (self.workspace / "task_state.json").exists():
            raise RuntimeStateError(
                f"无断点可恢复：{self.workspace} 内无 task_state.json")
        tr = self.engine.resume_task(on_event=on_event)
        return _wrap(tr, self.workspace)

    def cancel(self) -> bool:
        """取消活动任务（幂等）；无活动任务 → False。"""
        return bool(self.engine.cancel_task())


def _wrap(tr: TaskResult, workdir: pathlib.Path) -> SdkResult:
    return SdkResult(
        status=str(getattr(tr, "status", "") or ""),
        task=str(getattr(tr, "task_text", "") or ""),
        report=str(getattr(tr, "report", "") or ""),
        artifacts=tuple(str(a) for a in (getattr(tr, "artifacts", None) or [])),
        workspace=str(workdir),
        task_result=tr,
    )


def _validate_tool_names(tool_names) -> tuple[str, ...]:
    if tool_names is None:
        return CORE_TOOLS
    names = tuple(dict.fromkeys(str(n) for n in tool_names))  # 去重保序
    if not names:
        raise ValueError("tool_names 不能为空（省略 = 核心五件）")
    unknown = [n for n in names if n not in CORE_TOOLS]
    if unknown:
        raise ValueError(
            f"未知/越权工具名：{unknown}（允许：{list(CORE_TOOLS)}）")
    return names


def _validate_overrides(config_overrides) -> dict:
    overrides = dict(config_overrides or {})
    bad = sorted(k for k in overrides if k not in _OVERRIDE_ALLOWLIST)
    if bad:
        raise ValueError(
            f"config_overrides 含越权键：{bad}（允许清单见 wuxing.sdk 模块）")
    return overrides


def build_runtime(*, llm=None, workdir=None, auto_confirm=True,
                  tool_names=None, config_overrides=None) -> Runtime:
    """显式装配最小运行时（设计 §6）。

    - ``llm``："type:model" spec / dict spec / provider 对象；None 或 "mock" →
      MockLlmProvider（真实形状化同时关闭）；
    - ``workdir``：显式工作目录；None → 临时目录（``Runtime.workspace`` 可查）；
    - ``tool_names``：核心五件子集；None → 全部核心五件；
    - ``config_overrides``：仅允许清单内的数值/上下文调优键；越权 → ValueError。
    """
    names = _validate_tool_names(tool_names)
    overrides = _validate_overrides(config_overrides)
    if isinstance(llm, str):
        use_real_shape = llm.strip().lower() != "mock"
    elif llm is None:
        use_real_shape = False
    else:  # dict spec / provider 对象 = 显式真实模型
        use_real_shape = True
    cfg = EngineConfig(
        use_real_shape=use_real_shape,
        extension_enabled=False,
        extension_dirs=[],
        fsc_enabled=False,
        skill_evolution_enabled=False,
        brain_enabled=False,
        mcp_servers=[],
        default_tools=tuple(names),
        confirm_auto=bool(auto_confirm),
    )
    for key, value in overrides.items():
        setattr(cfg, key, value)
    engine = Engine(cfg=cfg,
                    workdir=pathlib.Path(workdir) if workdir else None,
                    llm=llm,
                    auto_confirm=bool(auto_confirm),
                    isolated=True)
    return Runtime(engine)
