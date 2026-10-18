"""Shell Protocol（Q2/Q11：壳-引擎协议化边界）。

壳只允许：
  1. 构造 Engine（workdir 等）
  2. run_task(task_text, on_event) 提交任务并消费事件
  3. 读取 TaskResult（report/artifacts）
不 import 引擎内部模块（registry/runner/orchestrator...）——接口即边界。
"""
from abc import ABC

#: 壳允许依赖的引擎公开面（边界纪律**唯一事实来源**）。
#: tests/test_shell_protocol.py 与 tests/test_shell_boundary.py 共用本表——
#: 新增壳依赖需在此处登记（集中评审），避免两处白名单漂移。
SHELL_ALLOWED_IMPORTS = (
    "wuxing.engine",
    "wuxing.events",
    "wuxing.config_contract",
    "wuxing.atomic_write",
    "wuxing.credentials",
    "wuxing.providers_catalog",
    # M7 #8（A3）：重启后挂起恢复——壳需读 task_state.json（state.py 的
    # save/load 数据模型，公开产物；经集中评审登记）
    "wuxing.state",
    # A 期（2026-09-22，A1）：上下文来源 sidecar 为壳写/引擎读的共享契约
    # （context-sources.json：resolve 读取 + save 写入——跨边界格式单源）
    "wuxing.context_sources",
    # 双模式批 1（2026-09-23）：会话模式 sidecar 为壳写/引擎读的共享契约
    # （session-modes.json：resolve 读取 + save 写入 + 空白判据——跨边界格式单源）
    "wuxing.session_modes",
    # 双模式批 3（2026-09-24）：循迹设计态与工作区地图为壳读/引擎写共享契约
    # （design-state.json：load/infer + WUXING.md：read/file_hash——跨边界格式单源）
    "wuxing.design_state",
    "wuxing.map_doc",
    # 双模式批 4（2026-09-25）：承接简报为壳读/引擎生成的跨边界格式（确定性拼装）
    "wuxing.handoff",
    # 二期批 3（2026-09-25）：规格为壳读/引擎写共享契约（specs/*.md + 指针）
    "wuxing.spec_doc",
    # 二期批 4（2026-09-25）：实施票据为壳读/写与引擎读的共享契约
    # （tickets.jsonl：load/publish——跨边界格式单源）
    "wuxing.tickets",
    # E2-4：装配预设（组合树/会话绑定——跨边界格式单源）
    "wuxing.presets",
    # E3-1/R5（worktree 隔离运行）：worktree 生命周期 + run↔worktree 绑定标记
    # 为壳（manager 提交/恢复路由/Review-Apply）与引擎共享契约——跨边界格式单源
    "wuxing.worktrees",
    # O2-2 P3（2026-10-08）：浏览器允许条目为跨边界格式单源（引擎动态授权写/读
    # + 壳设置面查看/撤销）——browser_guard 提供 load/save fail-closed 口径
    "wuxing.browser_guard",
    # 重大优化清单 #3（2026-10-09）：域提示词为壳读/写与引擎读共享契约
    # （domain_prompts.json 两层本机存档——跨边界格式单源）
    "wuxing.domain_prompts",
    # 重大优化清单 #2 Phase 1.5（2026-10-14）：交互偏好为壳读/写共享契约
    # （interaction.json 两层本机存档——跨边界格式单源）
    "wuxing.interaction_prefs",
    # 重大优化清单 #2 T-5（2026-10-14）：决策历史为壳读的 trace 还原
    # （只读 trace.jsonl → 审计对条目）
    "wuxing.decision_log",
    # O2-2 §11.5-①（身份基线）：身份键/注册表读（跨边界格式单源）
    # + 控制通道客户端（壳设置面「身份清除」经通道下发）
    "wuxing.browser_identity",
    "wuxing.browser_channel",
)


class ShellProtocol(ABC):
    """壳可以依赖的引擎契约（鸭子类型，不强制继承）。"""
    def submit_task(self, task_text: str, on_event=None): ...
