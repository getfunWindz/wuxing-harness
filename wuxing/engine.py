"""引擎顶层 API（Q2：壳层通过此处与引擎对话；接口即形态）。"""
import logging

logger = logging.getLogger(__name__)
import pathlib
import tempfile

from wuxing.artifacts import result_artifacts
from wuxing.config import EngineConfig
from wuxing.config_schema import FIELD_SPECS
from wuxing.context_window import resolve_context_window
from wuxing.engine_cmds import EngineCmdsMixin
from wuxing.engine_metrics import EngineMetricsMixin
from wuxing.engine_session import EngineSessionMixin
from wuxing.engine_shape import (  # noqa: F401 (P4 兼容转出：既有导入点)
    EngineShapeMixin,
    _shape_quality,
    _shape_quality_note,
)
from wuxing.engine_skills import EngineSkillsMixin
from wuxing.llm.mock import MockLlmProvider
from wuxing.orchestrator import Orchestrator
from wuxing.protocols import CancellationToken, TaskResult, UnitResult
from wuxing.registry import DomainRegistry
from wuxing.router import route_fragment
from wuxing.session_plan import (
    session_plan,  # noqa: F401 (壳兼容转出：manager.py 经 engine 公开面取用)
)
from wuxing.tools.loader import ToolLoaderConfig, load_tools
from wuxing.workspace import Workspace


def _ticket_error_summary(units) -> str:
    """S1-C：票据回写错误串（失败分类短标 + 验收不通过；≤300 截断）。"""
    short = {"provider": "基础设施", "budget": "预算", "stalled": "停滞"}
    parts = []
    for u in units or []:
        item = f"{getattr(u, 'unit_id', '')}:{getattr(u, 'status', '')}"
        fc = getattr(u, "failure_class", "") or ""
        if fc in short:
            item += f"({short[fc]})"
        if getattr(u, "verdict_fail", False):
            item += "(验收不通过)"
        parts.append(item)
    return "；".join(parts)[:300]


class Engine(EngineSkillsMixin, EngineMetricsMixin, EngineShapeMixin, EngineSessionMixin, EngineCmdsMixin):
    def __init__(self, cfg: EngineConfig | None = None,
                 workdir: pathlib.Path | None = None,
                 state_root: pathlib.Path | None = None,
                 llm=None, router=None,
                 auto_confirm: bool | None = None,
                 isolated: bool = False,
                 run_id: str | None = None,
                 preset_session: str | None = None):
        """P3 T1：人工介入默认化——auto_confirm=None → 从配置 confirm_auto 读（默认 False）。

        知识库企业级标准：interrupt on——该问人就问人；headless/CI 显式 --auto。

        G4（2026-09-26）：isolated=True 显式装配——零隐式继承（不读文件配置/
        用户级技能/扩展/凭据存储）+ 外围子系统剥离；供最小运行时 SDK 使用。
        G8-M3：run_id 显式指定 → 任务状态写入 `.wuxing/runs/<run_id>/`
        （并行执行隔离）；缺省 = 根级旧路径（单 run 兼容）。
        E3-1/R5（T2）：state_root 显式指定 → run 账本（runs/trace/provenance/
        sessions/manifest/缓存）写 state_root；交付物与命令执行留 workdir；
        缺省 None = workdir（行为零变化）。
        """
        # workdir 最先（配置加载需读取 workdir 下的 config.jsonc）
        self.isolated = bool(isolated)
        self.workdir = (pathlib.Path(workdir) if workdir else
                        pathlib.Path(tempfile.mkdtemp(prefix="wuxing-")))
        # E3-1/R5（T2）：状态根分离——run 账本写 state_root（缺省=workdir，零变化）；
        # worktree 只承载交付物文件与命令执行（W3）。
        self.state_root = (pathlib.Path(state_root) if state_root
                           else self.workdir)
        # G8-M3：run 作用域任务状态路径
        self.run_id = str(run_id) if run_id else None
        # §11.5-②（Q1=B）：会话绑定（浏览器身份 overlay）+ run 落盘域
        self.preset_session = str(preset_session or "")
        if self.run_id:
            from wuxing.state import run_state_path as _run_state_path
            self._state_path = _run_state_path(self.state_root, self.run_id)
        else:
            self._state_path = self.state_root / "task_state.json"
        # E2-4：装配预设解析（会话 sidecar > 配置默认；失败回退 standard）
        from wuxing import presets as _presets
        self.preset = _presets.resolve_for_session(
            self.state_root, session=str(preset_session or ""),
            default=str(getattr(cfg, "assembly_preset", "standard")
                        or "standard"))
        self._preset_resolved = self.preset["resolved"]
        # P11：配置形态——文件（JSONC 三层）优先，未提供 cfg 或 cfg 为默认时装载；
        # 程序化 cfg 显式传入优先于文件（workdir 单次创建——审查修正：此前重复赋值泄漏临时目录）
        # G4：isolated 未显式传 cfg → EngineConfig 默认（不触碰文件配置）；
        # 工具面由 CORE_TOOLS 固定——不随 default_tools 默认值漂移（既有契约：
        # 核心五件；显式 cfg 仍按 cfg.default_tools 装配）
        if cfg is None:
            if self.isolated:
                from wuxing.sdk import CORE_TOOLS
                cfg = EngineConfig(default_tools=tuple(CORE_TOOLS))
            else:
                cfg = self._load_config_from_files()
        self.cfg = cfg
        # P3 T1：人工介入默认化——auto_confirm 显式覆盖 > cfg.confirm_auto > False
        if auto_confirm is None:
            auto_confirm = bool(getattr(cfg, "confirm_auto", False))
        self.auto_confirm = auto_confirm
        # 壳 P1 对齐项②：活动任务的取消令牌（None=无活动任务）
        self._cancel_token = None
        # 真实形状化降级提示（每任务清空——报告尾注；见 _shape_or_cached）
        self._shape_notice = ""
        self._shape_quality_note = ""  # P0-2 B：拆分质量注记（报告可见）
        # resources 生态：外部资源声明校验（非 optional 缺失=配置早报；optional 缺失=warn）
        from wuxing.resources import ResourceRegistry
        self.resources = ResourceRegistry(getattr(cfg, "resources", None)
                                          or {}, workdir=self.workdir)
        for w in self.resources.check():
            logger.warning("%s", w)
        self.registry = DomainRegistry(self.cfg)
        self.ws = Workspace(self.workdir,
                            permission_profile=self.cfg.permission_profile,
                            manifest_root=self.state_root)
        # P11：llm/router 优先显式参数；否则从 cfg（文件配置）装配——工厂转换
        # L4 冒烟发现：llm 参数须规范化——spec（str/dict）→ 工厂装配
        if isinstance(llm, (str, dict)):
            from wuxing.llm.factory import create_provider
            llm = create_provider(llm, max_retries=self.cfg.llm_max_retries,
                                  timeout=self.cfg.llm_timeout,
                                  providers=getattr(self.cfg, "providers", None),
                                  allow_stored_credentials=not self.isolated)
        elif llm is None and self.cfg.llm and self.cfg.llm != "mock":
            from wuxing.llm.factory import create_provider
            llm = create_provider(self.cfg.llm, max_retries=self.cfg.llm_max_retries,
                                  timeout=self.cfg.llm_timeout,
                                  providers=getattr(self.cfg, "providers", None),
                                  allow_stored_credentials=not self.isolated)
        self.llm = llm or MockLlmProvider()
        # Pi 同款（2026-09-10）：会话亲和缓存键（工作区标识——同工作区稳定）
        import hashlib as _hashlib
        self._cache_key = _hashlib.sha256(
            str(self.state_root).encode("utf-8")).hexdigest()[:48]
        try:
            self.llm._cache_key = self._cache_key  # 鸭子类型（假 LLM 无害）
        except Exception as exc:
            logger.debug("缓存键注入失败（鸭子类型不阻断）：%s", exc)
        # 智脑三级参照表（用户裁决 2026-09-06）：记忆常建——收集常开（完善评判能力）；
        # brain_enabled 仅控制『决策注入』（router 使用记忆）——默认关
        self.brain_enabled = (False if self.isolated
                              else getattr(self.cfg, "brain_enabled", False))
        if self.isolated:
            # G4：智脑关闭（决策 + 收集）——最小运行时无隐式记忆面
            self.brain_memory = None
        else:
            from wuxing.llm.brain import BrainMemory
            self.brain_memory = BrainMemory(self.state_root / "brain_memory.json",
                                            getattr(self.cfg, "brain_max_cases", 500))
        if router is None and self.cfg.router:
            from wuxing.llm.router import ModelRouter
            router = ModelRouter(self.cfg.router,
                                 brain=self.brain_memory if self.brain_enabled else None,
                                 max_retries=self.cfg.llm_max_retries,
                                 timeout=self.cfg.llm_timeout,
                                 cache_key=self._cache_key,
                                 providers=getattr(self.cfg, "providers", None))
        elif router is None and self.brain_enabled:
            # 智脑模式：Router 装配 brain（无显式 router 时默认配置）
            from wuxing.llm.router import ModelRouter
            _auto_spec = dict(getattr(self.cfg, "router", None) or {})
            # 真测修复（REAL-2）：未列出域回退引擎默认模型——此前 `{}` 使
            # `_resolve_candidates` 钉死 "mock"（brain 开启 + 未配 router 时
            # 四域全部静默 mock，真实任务却报 done）
            _auto_spec.setdefault("_default", str(self.cfg.llm or "mock"))
            router = ModelRouter(_auto_spec,
                                 brain=self.brain_memory,
                                 providers=getattr(self.cfg, "providers", None))
        self.router = router
        # 2026-09-18（用户裁决）：真实形状化默认开——无凭据不再构造期 fail-fast，
        # 由 _shape_or_cached 降级 mock + 报告引导提示（不阻断机制运行）。
        # SK：技能注册表（内置层 + 用户级 ~/.wuxing/skills + 项目级 workdir/.skills）——渐进披露
        from wuxing.skills import SkillRegistry
        if self.isolated:
            # G4：技能三层全剥离（用户级/内置/项目级都不扫描）
            self.skills = SkillRegistry(user_dir=None, project_dir=None,
                                        builtin_dir=None)
        else:
            self.skills = SkillRegistry(
                project_dir=self.workdir / ".skills",
                builtin_dir=pathlib.Path(__file__).parent / "builtin_skills")
        # L2-1（审查 A3）：MCP 配置面接线——config.jsonc mcp_servers → 工具装载；
        # 权限未声明 → 工具默认拦截（最小权限——显式解锁）
        from wuxing.tools.mcp_bridge import McpServerConfig
        mcp_cfgs = [] if self.isolated else [McpServerConfig(
            name=c["name"], command=c["command"],
            args=list(c.get("args") or []),
            permissions=dict(c.get("permissions") or {}),
            env=dict(c.get("env") or {}))  # E4：环境白名单（值=环境变量名）
            for c in (getattr(self.cfg, "mcp_servers", None) or [])]
        # E1（企业级审查）：MCP 常驻连接池——工具调用复用连接（秒级→毫秒级）
        from wuxing.tools.mcp_bridge import _make_pool
        self._mcp_pool = _make_pool() if mcp_cfgs else None
        self._mcp_cfgs = mcp_cfgs  # B5（技术债收口）：子 Runner（delegate）继承用
        _web_fetch = None
        if getattr(cfg, "web_fetch_enabled", False):
            from wuxing.tools.web_tool import WebFetchTool
            _web_fetch = WebFetchTool(self.ws, cfg)  # E2-5：启用才注册
        _code_mode = None
        if getattr(cfg, "code_mode_enabled", False):
            from wuxing.tools.code_mode import RunScriptTool
            _code_mode = RunScriptTool(self.ws, cfg)  # A4：启用才注册
        _browser = None
        if getattr(cfg, "browser_enabled", False):
            from wuxing.tools.browser_tool import (
                BrowserClickTool,
                BrowserEvaluateTool,
                BrowserNavigateTool,
                BrowserScreenshotTool,
                BrowserSnapshotTool,
                BrowserTypeTool,
                BrowserWaitTool,
            )
            # §11.5-②：会话/run 绑定（identity overlay + 落盘域）
            _binding = {"session": self.preset_session,
                        "run": str(self.run_id or "")}
            _browser = [BrowserNavigateTool(
                            self.ws, cfg, binding=_binding,
                            trace_getter=lambda: getattr(self, "trace", None)),
                        BrowserSnapshotTool(self.ws, cfg, binding=_binding),
                        BrowserClickTool(self.ws, cfg, binding=_binding),
                        BrowserTypeTool(self.ws, cfg, binding=_binding),
                        BrowserWaitTool(self.ws, cfg, binding=_binding),
                        BrowserScreenshotTool(self.ws, cfg,
                                              binding=_binding)]  # O2-2：启用才注册
            if getattr(cfg, "browser_evaluate_enabled", False):
                # O2-2 P3：evaluate 显式档——双闸（browser_enabled + 本开关）
                _browser.append(BrowserEvaluateTool(self.ws, cfg,
                                                    binding=_binding))
        self.tools = load_tools(self.ws, ToolLoaderConfig(mcp_servers=mcp_cfgs),
                                skills=self.skills,
                                web_fetch=_web_fetch,
                                code_mode=_code_mode,
                                browser=_browser,
                                sandbox_enabled=getattr(cfg, "sandbox_enabled", True),
                                sandbox_mode=getattr(cfg, "sandbox_mode", "native"),
                                sandbox_container_template=getattr(
                                    cfg, "sandbox_container_template", ""),
                                bash_shell_path=getattr(cfg, "bash_shell_path", ""),
                                bash_timeout_s=getattr(cfg, "bash_timeout_s", 120.0),
                                mcp_pool=self._mcp_pool,
                                tool_search_enabled=getattr(
                                    cfg, "tool_search_enabled", True),
                                tool_search_threshold=getattr(
                                    cfg, "tool_search_threshold", 20),
                                mcp_always_load=getattr(
                                    cfg, "mcp_always_load", ()))
        # 配置补遗：全局工具白名单（pi defaultTools 参考）——引擎级工具（delegate/load_skill）
        # 与 MCP 工具（is_mcp——显式配置引入+permissions 闸+域白名单闸，不参与粗筛）不受过滤
        _preset_tools = self._preset_resolved.get("tools")
        _keep_src = (_preset_tools if _preset_tools is not None
                     else getattr(self.cfg, "default_tools", None))
        if _keep_src:
            keep = set(_keep_src)
            # G4：isolated → 无引擎级豁免（扩展工具仍可由域白名单合并——但扩展已零装载）
            engine_level = (set() if self.isolated
                            else {"delegate", "load_skill", "write_map", "write_spec",
                                  "web_fetch", "run_script",
                                  # E2-5（A10）：ask_user 引擎级（域白名单为闸——
                                  # 防 default_tools 粗筛剔除）
                                  "ask_user",
                                  # O2-2（P1）：浏览器工具（域白名单为闸——防
                                  # default_tools 粗筛剔除；browser_enabled 为注册闸）
                                  "browser_navigate", "browser_snapshot",
                                  "browser_screenshot",
                                  "browser_click", "browser_type", "browser_wait",
                                  "browser_evaluate"})
            self.tools._tools = {n: t for n, t in self.tools._tools.items()
                                 if n in keep or n in engine_level
                                 or getattr(t, "is_mcp", False)}
        if self.isolated:
            # 无条件剥离（default_tools 可能被显式配置保留 load_skill）
            self.tools._tools.pop("load_skill", None)
        # P9 R1：执行单元回复缓存（重试/恢复/相似碎片复用）
        from wuxing.cache import ReplyCache, ShapeCache
        self.reply_cache = ReplyCache(self.state_root / "reply_cache.json",
                                      similar_threshold=getattr(
                                          self.cfg, "cache_similar_threshold", 0.75))
        # P9 R2：形状化持久缓存（跨会话同任务零调用）
        self.shape_cache = ShapeCache(self.state_root / "shape_cache.json")
        # 3c：溯源链 + delegate 装配（深度计数初始化在 __init__ 起始）
        from wuxing.provenance import ProvenanceLedger
        self.provenance = ProvenanceLedger(self.state_root / ".wuxing" / "provenance.jsonl")
        if not self.isolated:
            self.tools.register(self._make_delegate_tool())
            # 批 3：write_map/write_spec（循迹设计工具——引擎级注册；仅 design 域白名单可及）
            # G8：unclaim_ticket（认领释放——同上）
            from wuxing.tools.design_tools import (
                UnclaimTicketTool,
                WriteMapTool,
                WriteSpecTool,
            )
            self.tools.register(WriteMapTool(self.ws))
            self.tools.register(WriteSpecTool(self.ws))
            self.tools.register(UnclaimTicketTool(self.ws))
        # P5：确认关口（分层把关）
        from wuxing.confirm_gate import ConfirmGate
        self.confirm_gate = ConfirmGate(self.cfg, registry=self.registry)
        # L3：任务级共享区（碎片间协作——已完成碎片三要素 → 后续碎片有向注入）
        from wuxing.shared_context import FileCache, SharedContext
        self.shared = SharedContext()
        self.file_cache = FileCache()
        # L1-1：trace 采集器（评测原料——观测层；与 session/provenance 并置）
        from wuxing.trace import TraceLogger
        self.trace = TraceLogger(self.state_root / ".wuxing" / "trace.jsonl")
        # E0-A 扩展机制（设计 2026-09-26 · D2 默认开启）：
        # 构造时加载（用户级 → 项目级 → 附加目录）；工具经域白名单合并进受控面
        # （runner 侧 filter(domain_id)——不改域定义本体）；钩子只读分发（公开入口包装）。
        # 目录不存在 = 零行为；失败可见不阻断（broken → trace + 报告注记）。
        # 注：本段位于 default_tools 粗筛之后——扩展工具与引擎级工具同类
        # （域白名单为工具面唯一闸），不受全局粗筛（计划 §1 裁决 4）。
        from wuxing.extensions import load_extensions, resolve_extension_dirs
        if self.isolated:
            # G4：扩展零装载（不解析任何目录，包括用户级）
            self._ext_result = load_extensions(self.state_root, enabled=False,
                                               dirs=[], trace=self.trace,
                                               registry=self.tools)
        else:
            _preset = self._preset_resolved
            self._ext_result = load_extensions(
                self.state_root,
                enabled=bool(getattr(cfg, "extension_enabled", True)),
                dirs=resolve_extension_dirs(self.state_root,
                                            getattr(cfg, "extension_dirs", None)),
                trace=self.trace, registry=self.tools,
                enabled_names=(_preset["extensions"]["enable"] or None),
                disabled_names=_preset["extensions"]["disable"])
        # SEC3（修复 2026-09-30·golden 自测发现）：策略必须在**全部工具注册完成后**应用——
        # 旧序早于 delegate/设计工具/扩展注册，晚注册工具逃逸 read-only 过滤
        # （实测：read-only 下 delegate 可用且空烧预算、扩展写工具漏网）。
        from wuxing.permissions import apply_tool_policy
        self._tools_removed = apply_tool_policy(self.tools,
                                                self.cfg.permission_profile)
        self._ext_dispatcher = self._ext_result.dispatcher
        self._extension_note = self._ext_result.summary_note()
        # E2-2：tool_call 干预钩子接线（无钩子零行为；守卫在改参之后校验）
        self.tools.set_ext_interceptor(self._ext_tool_interceptor)
        # E2-4：预设过滤（提示词段/技能；"*"=全禁）
        _seg_disable = {str(x) for x in
                        (self._preset_resolved.get("prompt_segments", {})
                         .get("disable") or [])}
        if "*" in _seg_disable:
            self._ext_segments: list = []
        else:
            self._ext_segments = [
                s for s in self._ext_result.prompt_segments
                if str(s.get("source") or "") not in _seg_disable]
        self._skills_disabled = {str(x) for x in
                                 (self._preset_resolved.get("skills", {})
                                  .get("disable") or [])}
        # 分级放行（2026-09-11 用户裁决）：软 64/硬 100/25ms（可配）
        # 壳 P1 对齐项①（第七轮）：ensure 幂等——多工作区共享进程级限流器，
        # Engine 构造不重建/不丢统计；显式重配走 configure()（测试后门）
        from wuxing.concurrency import ensure_configured as _ensure_limiter
        _ensure_limiter(
            soft=int(getattr(self.cfg, "tool_concurrency_soft", 0) or 64),
            hard=int(getattr(self.cfg, "tool_concurrency_hard", 0) or 100),
            delay_ms=int(getattr(self.cfg, "tool_throttle_delay_ms", 25)))
        # FSC（2026-09-11 设计）：碎片会话延续池（opt-in——fsc_enabled）
        if getattr(self.cfg, "fsc_enabled", False) and not self.isolated:
            from wuxing.session_pool import SessionPool
            try:
                _spec = self.llm.spec() if hasattr(self.llm, "spec") else ""
            except Exception:
                _spec = ""
            _window = resolve_context_window(
                _spec,
                getattr(self.cfg, "model_context_windows", None),
                getattr(self.cfg, "default_context_window", 200_000))
            self.session_pool = SessionPool(
                retention_rounds=getattr(self.cfg, "fsc_retention_rounds", 4),
                max_session_chars=getattr(self.cfg, "fsc_max_session_chars", 65536),
                max_reuse=getattr(self.cfg, "fsc_max_reuse", 3),
                total_char_budget=getattr(self.cfg, "fsc_total_char_budget", 262144),
                context_window=_window,
                audit_ratio=getattr(self.cfg, "fsc_audit_ratio", 0.6),
                switch_ratio=getattr(self.cfg, "fsc_switch_ratio", 0.8))
        else:
            self.session_pool = None
        self.orchestrator = Orchestrator(self.cfg, self.registry, self.ws,
                                         self.llm, self.tools,
                                         llm_for=self.llm_for,
                                         llm_candidate_count=self.llm_candidate_count,
                                         confirm_gate=self.confirm_gate,
                                         auto_confirm=self.auto_confirm,
                                         reply_cache=self.reply_cache,
                                         brain_memory=self.brain_memory,
                                         provenance=self.provenance,
                                         skills=self.skills,
                                         shared=self.shared,
                                         trace=self.trace,
                                         file_cache=self.file_cache,
                                         session_pool=self.session_pool,
                                         ext_segments=self._ext_segments,
                                         skills_disabled=self._skills_disabled,
                                         state_root=self.state_root,
                                         hook_collect=self._ext_dispatcher.dispatch_collect)
        # G5：装配代际与失败可见（内容指纹 → trace → 工作区代际记录）
        self._wire_assembly()

    def _wire_assembly(self) -> None:
        """G5：装配指纹/代际记录接线（观察层 fail-safe——失败不阻断引擎构造）。"""
        from wuxing.assembly import (
            collect_components,
            degraded_items,
            fingerprint,
            record_generation,
        )
        self.assembly = {"id": "", "components": {}, "degraded": [],
                         "previous_id": None, "computed_at": None}
        try:
            if self.isolated:
                ext_dirs: list = []
            else:
                from wuxing.extensions import resolve_extension_dirs
                ext_dirs = resolve_extension_dirs(
                    self.state_root, getattr(self.cfg, "extension_dirs", None))
            loaded_mcp = sorted(
                str(getattr(t, "_server", ""))
                for t in self.tools._tools.values()
                if getattr(t, "is_mcp", False))
            components = collect_components(
                self.cfg, isolated=self.isolated,
                tool_names=list(self.tools._tools.keys()), skills=self.skills,
                extension_dirs=ext_dirs, mcp_cfgs=self._mcp_cfgs)
            # E2-4：预设进装配代际（预设变更 → 装配 id 变化）
            components["preset"] = {
                "name": str(self.preset.get("name") or ""),
                "chain": [str(x) for x in (self.preset.get("chain") or [])],
                "hash": str(self.preset.get("hash") or "")}
            degraded = degraded_items(self._ext_result,
                                      mcp_configured=self._mcp_cfgs,
                                      mcp_loaded_names=loaded_mcp)
            aid = fingerprint(components)
            self.assembly = {"id": aid, "components": components,
                             "degraded": degraded, "previous_id": None,
                             "computed_at": None}
            self.trace.log("assembly", "", "", id=aid, degraded=len(degraded))
            try:
                rec = record_generation(self.state_root, id=aid,
                                        components=components,
                                        degraded=degraded)
                self.assembly["previous_id"] = rec.get("previous_id")
                self.assembly["computed_at"] = rec.get("computed_at")
            except OSError as exc:
                self.trace.log("assembly_record_failed", "", "",
                               error=f"{type(exc).__name__}: {exc}")
        except Exception as exc:  # 装配观察层：失败不阻断引擎构造
            self.trace.log("assembly_failed", "", "",
                           error=f"{type(exc).__name__}: {exc}")

    def _ext_tool_interceptor(self, name, kwargs):
        """E3-2（P0）：tool_call 干预 v2——合并决策（deny>ask>allow）+ updated_input。

        deny/ask/改参 落 trace（可观测——不记参数值，只记工具名/原因/键名）。
        """
        from wuxing.extensions import ToolCallRequested
        res = self._ext_dispatcher.dispatch_merge(
            ToolCallRequested(name=str(name), args=dict(kwargs or {})))
        if isinstance(res, dict) and self.trace is not None:
            try:
                decision = str(res.get("decision") or "")
                if decision == "deny":
                    self.trace.log("extension_tool_denied", "", "",
                                   tool=str(name),
                                   reason=str(res.get("reason") or ""))
                elif decision == "ask":
                    self.trace.log("extension_tool_ask", "", "",
                                   tool=str(name),
                                   reason=str(res.get("reason") or ""))
                elif res.get("updated_input"):
                    self.trace.log(
                        "extension_tool_input_updated", "", "",
                        tool=str(name),
                        keys=",".join(sorted(str(k) for k in
                                             res["updated_input"])))
            except Exception as exc:
                logger.debug("扩展工具决策事件记录失败（观测不阻断）：%s", exc)
        return res

    def _delegate_runner(self, goal: str, domain=None, read_only: bool = False):
        """3c 委托工厂：子 Runner（工具集剔除 delegate 防递归）。

        L0-3（审查 B1/R2-A2）：深度护栏已移入 DelegateTool 实例（原子临界区 +
        try/finally 释放）——工厂不再持计数；release 保留为 no-op（接口兼容）。
        E3-1/R4（CU2）：read_only=True → 子工具集走 read-only 剖面（只读勘察）。
        """
        if domain is None:
            domain = route_fragment(goal)
        from wuxing.runner import Runner
        # A7（审查）：子 Runner 透传 trace/skills/shared——子任务必须产生
        # trace 事件（评测原料——与 child_calls 预算口径一致）、可用技能、
        # 可消费共享经验；此前子任务零观测（观测缺口）。
        _web_fetch_sub = None
        if getattr(self.cfg, "web_fetch_enabled", False):
            from wuxing.tools.web_tool import WebFetchTool
            _web_fetch_sub = WebFetchTool(self.ws, self.cfg)
        _code_mode_sub = None
        if getattr(self.cfg, "code_mode_enabled", False):
            from wuxing.tools.code_mode import RunScriptTool
            _code_mode_sub = RunScriptTool(self.ws, self.cfg)
        sub_tools = load_tools(
            self.ws, ToolLoaderConfig(mcp_servers=self._mcp_cfgs),
            skills=self.skills,
            web_fetch=_web_fetch_sub,
            code_mode=_code_mode_sub,
            sandbox_enabled=getattr(self.cfg, "sandbox_enabled", True),
            sandbox_mode=getattr(self.cfg, "sandbox_mode", "native"),
            sandbox_container_template=getattr(
                self.cfg, "sandbox_container_template", ""),
            bash_shell_path=getattr(self.cfg, "bash_shell_path", ""),
            bash_timeout_s=getattr(self.cfg, "bash_timeout_s", 120.0),
            mcp_pool=self._mcp_pool,
            tool_search_enabled=getattr(
                self.cfg, "tool_search_enabled", True),
            tool_search_threshold=getattr(
                self.cfg, "tool_search_threshold", 20),
            mcp_always_load=getattr(self.cfg, "mcp_always_load", ()))
        sub_tools.set_ext_interceptor(self._ext_tool_interceptor)
        # SEC3：子工具同策略（修复历史缺口——子路径此前未挂守卫）
        from wuxing.permissions import apply_tool_policy as _apply_policy
        # E3-1/R4（CU2）：只读派生——read_only 子任务强制 read-only 剖面
        _profile = "read-only" if read_only else self.cfg.permission_profile
        _apply_policy(sub_tools, _profile)
        sub = Runner(self.cfg, self.registry, self.ws, self.llm, sub_tools,
                     llm_for=self.llm_for, auto_confirm=True,
                     state_root=self.state_root,
                     reply_cache=self.reply_cache, brain_memory=self.brain_memory,
                     provenance=self.provenance, skills=self.skills,
                     shared=self.shared, trace=self.trace,
                     ext_segments=self._ext_segments,
                     skills_disabled=self._skills_disabled)
        sub._delegate_domain = domain
        return sub, (lambda: None)

    def _make_delegate_tool(self):
        """装配 delegate 工具（父溯源由 Runner 动态注入）。

        D1（2026-09-07）：子任务交付物语义注入回调——按目标域 artifact_kind
        机械映射（与主碎片 L4 修复对齐——子任务同样「不知交付类型→探索不止」）。
        """
        from wuxing.tools.delegate import DelegateTool
        return DelegateTool(self._delegate_runner, ledger=self.provenance,
                            deliverable_kinds=self._deliverable_kinds)

    def _deliverable_kinds(self, domain_id: str) -> list:
        """域→交付物类型（机械映射——registry 权威）。"""
        try:
            d = self.registry.get(domain_id)
            return [d.artifact_kind] if d.artifact_kind else []
        except KeyError:
            return []

    def llm_for(self, domain_id: str, fragment_key: str | None = None,
                candidate_index: int = 0):
        """域级模型路由（Q7 多模型协作）：router 存在用 router，否则单一 LLM。

        fragment_key 透传——智脑需要碎片文本检索记忆（for_domain 不带 key 则
        brain 读路径断头）。candidate_index（S1-A/L2）：降级链候选序。
        """
        if self.router is not None:
            return self.router.for_domain(domain_id, fragment_key,
                                          candidate_index=candidate_index)
        return self.llm

    def llm_candidate_count(self, domain_id: str) -> int:
        """S1-A/L2：域候选数——无 router=1（零行为变化）。"""
        return (self.router.candidate_count(domain_id)
                if self.router is not None else 1)

    def _load_config_from_files(self) -> EngineConfig:
        """P11：从 JSONC 三层配置装载 EngineConfig（load 即校验——ConfigError 早报）。"""
        from wuxing.config_loader import load_config
        try:
            data = load_config(self.state_root)
        except FileNotFoundError:
            return EngineConfig()
        if not data:
            return EngineConfig()
        valid_keys = {f.name for f in FIELD_SPECS}
        kwargs = {k: v for k, v in data.items() if k in valid_keys}
        # JSON list → tuple（default_domains / minimal_pure_tools 等）
        for k in ("default_domains", "minimal_pure_tools"):
            if k in kwargs and isinstance(kwargs[k], list):
                kwargs[k] = tuple(kwargs[k])
        return EngineConfig(**kwargs)

    def _wrap_events(self, on_event):
        """E0-A：扩展钩子包装（扩展先、原 on_event 后；无钩子/已包装零行为）。"""
        dispatcher = getattr(self, "_ext_dispatcher", None)
        if dispatcher is None:
            return on_event
        return dispatcher.wrap(on_event)

    def generate_task_reply(self, res, task_text: str = "") -> str:
        """pi 式总体回复（Wave-1 Task A1）：终端状态后由模型生成一条面向用户的回复消息。

        纪律：失败/关闭/非终态/空输出 → ""（调用方回退：最后非空单元 reply
        → 机械摘要）；不阻断主流程；不含工具调用（纯文本生成）。
        """
        if not bool(getattr(self.cfg, "task_reply_enabled", True)):
            return ""
        if res is None:
            return ""
        status = str(getattr(res, "status", "") or "")
        if status not in ("done", "partial", "failed"):
            return ""
        cap = int(getattr(self.cfg, "task_reply_max_chars", 800) or 800)
        text = str(task_text or getattr(res, "task_text", "") or "")
        lines = []
        for u in (getattr(res, "units", None) or []):
            dl = [str(d) for d in (getattr(u, "deliverables", None) or [])]
            rep = str(getattr(u, "reply", "") or "").strip()
            lines.append(
                f"- {getattr(u, 'unit_id', '?')} [{getattr(u, 'domain_id', '?')}] "
                f"{getattr(u, 'status', '?')}"
                + (f"；产物：{', '.join(dl[:5])}" if dl else "")
                + (f"；小结：{rep[:120]}" if rep else ""))
        prompt = ("你是任务执行引擎的收口环节。任务已收束，请向用户输出一条简短"
                  "总体回复：做了什么、关键结果/产物、需注意的问题。"
                  f"不超过 {cap} 字，直接输出正文。\n\n"
                  f"——任务——\n{text[:1000]}\n\n"
                  "——执行摘要——\n" + "\n".join(lines)[:4000])
        try:
            out = self.llm.chat([{"role": "user", "content": prompt}])
        except Exception as exc:  # 生成失败不阻断（调用方回退）
            logger.debug("总体回复生成失败（回退）：%s", exc)
            self._log_task_reply("task_reply_fallback",
                                 error=f"{type(exc).__name__}: {exc}"[:300])
            return ""
        reply = out if isinstance(out, str) else str(getattr(out, "text", "") or "")
        reply = " ".join(str(reply or "").split())
        if not reply:
            self._log_task_reply("task_reply_fallback", error="empty output")
            return ""
        self._log_task_reply("task_reply_generated", chars=min(len(reply), cap))
        return reply[:cap]

    def _log_task_reply(self, event: str, **fields) -> None:
        """总体回复链路 trace（可观测——真机发现回退静默不可归因，2026-10-03）。"""
        trace = getattr(self, "trace", None)
        if trace is None:
            return
        try:
            trace.log(event, unit_id="", domain="", **fields)
        except Exception as exc:  # 观测不阻断
            logger.debug("task_reply trace 落盘失败：%s", exc)

    def run_task(self, task_text: str, on_event=None, conversation=None,
                 references=None, overrides=None) -> TaskResult:
        """公开入口：任务执行 + 取消令牌作用域（壳 P1 对齐项②）。

        references（阶段 5 · 对齐项⑧）：任务级参考文件（工作区内相对/绝对路径）；
        缺失/越界 → ValueError（早报，不启动执行）。
        overrides（二期批 1）：显式闸覆盖集（当前仅 "no_map"——无地图执行；
        报告注记，不静默）。
        """
        on_event = self._wrap_events(on_event)
        token = CancellationToken()
        self._cancel_token = token
        self._shape_notice = ""  # 新任务：清空形状化降级提示
        self._shape_quality_note = ""  # P0-2 B：拆分质量注记（新任务清空）
        try:
            res = self._run_task_impl(task_text, on_event, conversation, token,
                                      references=references,
                                      overrides=overrides)
            self._maybe_archive_reports(res)
            self._maybe_close_browser_views(res)
            return res
        finally:
            if self._cancel_token is token:
                self._cancel_token = None

    # §11.5-②（Q4=A）：终态才关浏览器视图（pending/running 保活——可 confirm/resume）
    _BROWSER_CLOSE_STATUSES = ("done", "failed", "cancelled", "partial")

    def _maybe_close_browser_views(self, status) -> None:
        """run 终态清理：best-effort 关闭本 run 绑定的浏览器视图 + trace。

        无通道/无视图/异常 → 静默（debug），不阻断任务收口（CU10 同轴）。
        """
        st = str(getattr(status, "status", status) or "").strip()
        if st not in self._BROWSER_CLOSE_STATUSES:
            return
        if not getattr(self.cfg, "browser_enabled", False):
            return
        try:
            from wuxing.browser_channel import ChannelClient
            client = ChannelClient.from_env()
            if client is None:
                return
            from wuxing.browser_identity import identity_for
            identity = identity_for(self.cfg, self.ws,
                                    session=getattr(self, "preset_session", ""))
            data = client.call("close", identity=identity)
            if self.trace is not None:
                self.trace.log("browser_view_closed", "", "",
                               key=identity["key"],
                               closed=bool(data.get("closed")))
        except Exception as exc:   # 清理不阻断收口（best-effort）
            logger.debug("浏览器视图终态清理跳过：%s", exc)

    # 契约报告类型（给模型看的完成记录——2026-10-01 用户裁决：不入用户工作面）
    _REPORT_KINDS = ("plan", "result", "verdict", "acceptance")

    def _maybe_archive_reports(self, res) -> None:
        """契约报告归档（pending 例外——真跑 T-5 误判根因，2026-10-03）。

        等待确认（pending）的任务随时会被 confirm 续跑，依赖注入仍需产物原位
        可读；此时归档会把产物移入 .wuxing/reports/，确认路径经 file_cache
        快照注入旧路径、机制 `_verify_deps_missing` 磁盘读全缺失 → 误判
        「产物缺失→不通过」。终态（done/failed/cancelled/partial）照常归档。
        """
        if str(getattr(res, "status", "")) == "pending":
            return
        self._archive_internal_reports(res)

    def _archive_internal_reports(self, res) -> None:
        """契约报告收纳到 .wuxing/reports/（用户裁决 2026-10-01）。

        plan/result/verdict/acceptance 类报告本质是给模型看的过程记录；
        用户工作区只应留真实交付物（write_file 产物）。归档同步：单元 artifacts
        路径、单元 deliverables 引用、workspace manifest 条目。
        失败不阻断（文件留在原处——宁可可见也不丢）。
        """
        import shutil
        for u in (getattr(res, "units", None) or []):
            for a in (getattr(u, "artifacts", None) or []):
                kind = str(getattr(a, "kind", "") or "")
                path = str(getattr(a, "path", "") or "")
                if not path or kind not in self._REPORT_KINDS:
                    continue
                if path.replace("\\", "/").startswith(".wuxing/"):
                    continue
                src = self.workdir / path
                if not src.is_file():
                    continue
                dst_rel = f".wuxing/reports/{path}"
                dst = self.workdir / dst_rel
                try:
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                except OSError as exc:
                    logger.debug("报告归档失败（不阻断）：%s", exc)
                    continue
                a.path = dst_rel
                dls = getattr(u, "deliverables", None) or []
                for i, d in enumerate(dls):
                    if str(d) == path:
                        dls[i] = dst_rel
                try:
                    self.ws.relocate_manifest_path(path, dst_rel)
                except Exception as exc:
                    logger.debug("清单重定位失败（不阻断）：%s", exc)
                # 真跑 T-5（2026-10-03）：移动后失效 file_cache 旧路径——
                # 防确认/续跑经陈旧快照注入已不存在路径（机制误判产物缺失）
                _fc = getattr(self, "file_cache", None)
                if _fc is not None:
                    try:
                        _fc.invalidate(path)
                        _fc.invalidate(dst_rel)
                    except Exception as exc:
                        logger.debug("归档缓存失效失败（不阻断）：%s", exc)

    def _run_task_impl(self, task_text: str, on_event, conversation,
                       token: CancellationToken, references=None,
                       overrides=None) -> TaskResult:
        # 阶段 5（⑧）：参考文件块（早报——缺失/越界直接抛，不启动执行）
        ref_text = self._build_references(references)
        # B 模式：会话历史段（run_task 期间不变——轮内一致；append 在轮次完成后）
        if conversation is not None:
            self.orchestrator.conversation = conversation
        gate_overrides = {str(o) for o in (overrides or []) if str(o)}
        # 双模式批 3（循迹）：引擎闸——地图不可用时本调用不进入执行管线；
        # 二期批 1：显式 override（"no_map"）可放行（放宽机械裁决）
        if (self._theroad_design_needed(conversation)
                and "no_map" not in gate_overrides):
            return self._run_design_round(task_text, on_event, token)
        _ov_note = ""
        if (conversation is not None and self._in_theroad(conversation)
                and "no_map" in gate_overrides):
            _ov_note = ("[循迹 override] 无地图执行（用户显式选择）"
                        "——本次未走设计会话")
        _shape_input = task_text
        _wf_note = ""
        if conversation is not None and self._in_theroad(conversation):
            from wuxing.map_doc import digest as _map_digest
            _dg = _map_digest(self.workdir)
            if _dg:
                _shape_input = "[工作区地图摘要]\n" + _dg + "\n\n" + task_text
        elif conversation is None:
            # headless 选循迹（无交互界面）——不拦截，执行照常 + 报告透明注记（设计 §8）
            if self._session_mode(None)["mode"] == "theroad":
                _wf_note = ("[循迹] headless 无交互界面——已按默认模式执行（设计 §8）；"
                            "循迹设计会话需 Web 界面")
        # P1 T4：缓存/用量快照（任务级差值——度量口径）；阶段 4：含 FSC 池基线
        snap = self._task_start_snapshot()
        # 批 5：票据编排（theroad + 活跃票据）——直建 DAG，不经形状化
        ticket_frags = None
        _ticket_seeds = None
        _ticket_note = ""
        if (conversation is not None and self._in_theroad(conversation)
                and "no_map" not in gate_overrides):
            from wuxing import design_state as _ds5
            from wuxing import spec_doc as _spec5
            from wuxing import tickets as _tickets5
            active_tickets = [t for t in _tickets5.load(self.workdir)
                              if t.get("status") in ("ready", "running")]
            # G8：认领守卫——跳过他人认领；未认领票自动认领（本 run 归属）
            _claim_note = ""
            _holder = self._claim_holder(conversation)
            _runnable: list = []
            for t in active_tickets:
                tid = str(t.get("id") or "")
                owner = str(t.get("claimed_by") or "")
                if owner and owner != _holder:
                    _claim_note += f"跳过 {tid}（认领者 {owner}）；"
                    continue
                if not owner:
                    try:
                        _tickets5.claim(self.workdir, tid, by=_holder)
                        _claim_note += f"认领 {tid}；"
                    except _tickets5.TicketClaimedError as exc:
                        _claim_note += f"跳过 {tid}（认领者 {exc.holder}）；"
                        continue
                _runnable.append(t)
            active_tickets = _runnable
            if active_tickets:
                spec_text = _spec5.read(
                    self.workdir,
                    str(_ds5.load(self.workdir).get("spec_slug") or ""))
                ticket_frags = _tickets5.to_fragments(active_tickets,
                                                      spec_text=spec_text)
                # 真测裁决 W4.5：外部依赖声明——活跃票 deps 中非活跃票据：
                #   done → seed 其验收碎片为 ok（外部已完成——按验收通过处理）；
                #   其余 → 悬空（执行期按未满足依赖失败，报告注记指引票据重置）
                all_tk = {str(t["id"]): t for t in _tickets5.load(self.workdir)}
                active_ids = {str(t["id"]) for t in active_tickets}
                _ticket_seeds = {}
                _ext_done: list[str] = []
                _dangling: list[str] = []
                for t in active_tickets:
                    for dep in (t.get("deps") or []):
                        dep = str(dep)
                        if dep in active_ids:
                            continue
                        dep_row = all_tk.get(dep)
                        if (dep_row is not None
                                and dep_row.get("status") == "done"):
                            fid = f"F-T{dep[2:]}-v"
                            _ticket_seeds.setdefault(fid, UnitResult(
                                unit_id=fid, domain_id="verify", status="ok"))
                            if dep not in _ext_done:
                                _ext_done.append(dep)
                        elif dep not in _dangling:
                            _dangling.append(dep)
                for t in active_tickets:
                    _tickets5.update(self.workdir, t["id"],
                                     {"status": "running"})
                _ticket_note = ("[票据编排] 按已发布实施票据构建执行 DAG"
                                f"（{len(active_tickets)} 票 / "
                                f"{len(ticket_frags)} 碎片；不经形状化）")
                if _claim_note:
                    _ticket_note += "\n[认领守卫] " + _claim_note
                if _ext_done:
                    _ticket_note += ("\n[票据依赖] 外部已完成依赖"
                                     "（按验收通过声明）：" + "、".join(_ext_done))
                if _dangling:
                    _ticket_note += (
                        "\n[票据依赖] 依赖票据未激活且未完成："
                        + "、".join(
                            f"{d}（{all_tk.get(d, {}).get('status') or '未知'}）"
                            for d in _dangling)
                        + "——请先执行票据重置（自动补齐依赖闭包）")
        # P1 引擎级简化：碎片构建由 router 关键词驱动（完整形态 =
        # golden_ratio 形状化→分割，Task 12 接入，接口签名不变）
        if ticket_frags is not None:
            frags = ticket_frags
            units = self.orchestrator.run(frags, task_text, on_event=on_event,
                                          cancel=token,
                                          references_text=ref_text,
                                          seed_done=_ticket_seeds or None)
            artifacts = result_artifacts(units)
            status = self._task_status(units)
            metrics = self._collect_metrics(units, snap)
            report = self._build_report(units, artifacts, metrics)
            report += "\n\n" + _ticket_note
            from wuxing.events import TaskCancelled, TaskDone
            self._writeback_and_emit(units, on_event)
            if status == "cancelled" and on_event:
                on_event(TaskCancelled())
            if on_event:
                on_event(TaskDone(status=status))
            self._save_state(task_text, frags, units, artifacts, status)
            self._skill_evolution_hook(task_text, units, status,
                                       metrics=metrics)
            return TaskResult(task_text=task_text, fragments=frags,
                              units=units, artifacts=artifacts, status=status,
                              report=report, metrics=metrics)
        try:
            frags = self._build_fragments(_shape_input)
        except Exception as e:
            # S6（真实测试 expert-2 暴露）：形状化校验失败兜底——叮嘱类文本
            # （非独立任务——DAG 不连通）不应任务全败；降级单碎片执行
            # （_ensure_plan 会补 plan 链——流程完整；透明标记）。
            # 原 graceful failed 保留为「兜底也失败」的极端（理论上不会）。
            frags = self._fallback_fragments(_shape_input)
            _shape_error = f"{type(e).__name__}: {e}"
            try:
                self._ensure_plan(frags, task_text)
            except Exception as exc:
                logger.debug("plan 补链失败（兜底路径不阻断）：%s", exc)
            # C5 修复（2026-09-11 审查）：删除死赋值（原第一份 report 立即被覆盖）
            units = self.orchestrator.run(frags, task_text, on_event=on_event,
                                          cancel=token, references_text=ref_text)
            artifacts = result_artifacts(units)
            status = self._task_status(units)
            metrics = self._collect_metrics(units, snap)
            report = self._build_report(units, artifacts, metrics)
            report += f"\n\n[形状化兜底] 原形状化失败：{_shape_error}（已降级单碎片执行）"
            if getattr(self, "_shape_notice", ""):
                report += "\n\n" + self._shape_notice
            if getattr(self, "_shape_quality_note", ""):
                report += "\n\n" + self._shape_quality_note
            if _wf_note:
                report += "\n\n" + _wf_note
            if _ov_note:
                report += "\n\n" + _ov_note
            if status == "cancelled" and on_event:
                from wuxing.events import TaskCancelled
                on_event(TaskCancelled())
            if on_event:
                from wuxing.events import TaskDone
                on_event(TaskDone(status=status))
            self._save_state(task_text, frags, units, artifacts, status)
            self._skill_evolution_hook(task_text, units, status,
                                       metrics=metrics)
            return TaskResult(task_text=task_text, fragments=frags, units=units,
                              artifacts=artifacts, status=status, report=report,
                              metrics=metrics)
        units = self.orchestrator.run(frags, task_text, on_event=on_event,
                                      cancel=token, references_text=ref_text)
        artifacts = result_artifacts(units)
        # L0-4（审查 B6）：任务状态聚合提取（run/resume/confirm 三处同源）
        status = self._task_status(units)
        metrics = self._collect_metrics(units, snap)
        report = self._build_report(units, artifacts, metrics)
        if getattr(self, "_shape_notice", ""):
            report += "\n\n" + self._shape_notice
        if getattr(self, "_shape_quality_note", ""):
            report += "\n\n" + self._shape_quality_note
        if _wf_note:
            report += "\n\n" + _wf_note
        if _ov_note:
            report += "\n\n" + _ov_note
        if status == "cancelled" and on_event:
            from wuxing.events import TaskCancelled
            on_event(TaskCancelled())
        if on_event:
            from wuxing.events import TaskDone
            on_event(TaskDone(status=status))
        # P6：任务状态自动保存（断点恢复数据）
        self._save_state(task_text, frags, units, artifacts, status)
        self._skill_evolution_hook(task_text, units, status, metrics=metrics)
        return TaskResult(task_text=task_text, fragments=frags, units=units,
                          artifacts=artifacts, status=status, report=report,
                          metrics=metrics)

    def cancel_task(self) -> bool:
        """取消活动任务（壳 P1 对齐项②）——幂等；无活动任务返回 False。

        仅置位令牌；协作式检查点（片段/轮次/工具批前）负责停下。
        """
        token = getattr(self, "_cancel_token", None)
        if token is None:
            return False
        token.set()
        return True

    # 阶段 5（对齐项⑧）：参考文件注入上限（单文件/总计字符——超出截断标注）
    REF_CHAR_CAP = 20000
    REF_TOTAL_CAP = 60000

    def _build_references(self, references) -> str:
        """任务级参考文件 → 注入块（空/None → 空串——旧行为逐字节一致）。

        纪律（用户裁决 B · 2026-09-15）：**显式绝对路径允许指向工作区外**
        （系统文件对话框选出的文件直接可用——注入块明示来源）；相对路径仍限
        工作区内；缺失文件明确报错；内容封顶截断标注。
        """
        if not references:
            return ""
        root = pathlib.Path(self.workdir).resolve()
        parts: list[str] = []
        seen: set[str] = set()
        total = 0
        for raw in references:
            p = pathlib.Path(str(raw))
            cand = (p if p.is_absolute() else root / p).resolve()
            inside = True
            try:
                cand.relative_to(root)
            except ValueError:
                inside = False
            if not inside and not p.is_absolute():
                # 相对路径越界仍拒绝（显式绝对路径才开放——用户裁决 B）
                raise ValueError(f"参考文件必须在工作区内：{raw}")
            outside = not inside
            if not cand.is_file():
                raise ValueError(f"参考文件不存在：{raw}")
            label = str(cand) if outside else cand.relative_to(root).as_posix()
            if label in seen:
                continue
            seen.add(label)
            try:
                text = cand.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise ValueError(f"参考文件读取失败：{raw}（{exc}）") from exc
            truncated = False
            if len(text) > self.REF_CHAR_CAP:
                text = text[:self.REF_CHAR_CAP]
                truncated = True
            remain = self.REF_TOTAL_CAP - total
            if len(text) > remain:
                text = text[:max(0, remain)]
                truncated = True
            total += len(text)
            head = f"--- 参考文件{'（工作区外）' if outside else ''}：{label} ---"
            parts.append(f"{head}\n{text}"
                         + ("\n（内容过长已截断）" if truncated else ""))
            if total >= self.REF_TOTAL_CAP:
                break
        return "【参考资料】\n" + "\n\n".join(parts)

    @staticmethod
    def _task_status(units: list) -> str:
        """任务状态聚合（L0-4 提取）——**验收语义为中心**（用户裁决 2026-09-07）：

        verify 域 = 验收权威：
          - 有 verify 单元：全部通过（无 verdict_fail/无自身失败）→ done
            （其他单元失败=降级——记录在报告，验收通过即交付完成）
          - verify 不通过（结论不通过/自动兜底）→ failed（验收未过——明确失败）
          - 无 verify 单元（小任务无验证碎片）→ 保守回落：全 ok=done；有失败=partial
        pending（人工确认挂起）优先。
        """
        # 壳 P1 对齐项②：同 unit_id 多次结果（resume 重跑）取最新——
        # 上一轮的 cancelled/failed 旧结果不得继续裁决当前状态
        latest = {}
        for u in units:
            latest[u.unit_id] = u
        units = list(latest.values())
        if any(u.status == "cancelled" for u in units):
            return "cancelled"  # 壳 P1 对齐项②：用户取消优先（挂起/验收均不再裁决）
        if any(u.status == "rejected" for u in units):
            return "failed"  # 壳 P1 对齐项③：用户驳回=终止（任务级保留 failed）
        if any(u.status in ("needs_confirm", "needs_answer") for u in units):
            return "pending"
        verifies = [u for u in units if u.domain_id == "verify"]
        if verifies:
            if any(getattr(u, "verdict_fail", False) for u in verifies):
                return "failed"  # 验收不通过 = 未完成（明确失败）
            if any(u.status != "ok" for u in verifies):
                return "failed"  # verify 自身失败（无结论）——验收未完成
            return "done"  # 验收通过 —— 单元失败可降级
        if any(u.status == "failed" for u in units):
            return "partial" if any(u.status == "ok" for u in units) else "failed"
        return "done"

    def _save_state(self, task_text, frags, units, artifacts, status):
        from wuxing.state import TaskState, save_state
        save_state(TaskState(task_text=task_text, fragments=frags,
                             units=units, artifacts=artifacts, status=status),
                   self._state_path)

    def resume_task(self, on_event=None) -> TaskResult:
        """公开入口：断点恢复 + 取消令牌作用域（壳 P1 对齐项②）。"""
        on_event = self._wrap_events(on_event)
        on_event, captured = self._with_thought_capture(on_event)
        token = CancellationToken()
        self._cancel_token = token
        try:
            res = self._resume_task_impl(on_event, token)
            self._maybe_archive_reports(res)
            self._sync_conversation_terminal(res, captured)
            self._maybe_close_browser_views(res)
            return res
        finally:
            if self._cancel_token is token:
                self._cancel_token = None

    def _external_done_seeds(self, fragments, exclude=None) -> dict:
        """P0-1 验证缺陷修复：外部已完成依赖 seed（done 票的验收碎片 F-Tx-v）。

        现场：初始 run 为 done 票建了 seed，但 seed 只活在内存；确认续跑/
        恢复后从 state.units 重建 done → 下游票（如 F-T5 依赖 F-T1-v）被
        `unsatisfied deps (cycle)` 误判失败（attempts=None——从未运行）。
        """
        from wuxing import tickets as _t
        exclude = set(exclude or ())
        try:
            all_tk = {str(t["id"]): t for t in _t.load(self.workdir)}
        except Exception:
            return {}
        seeds: dict[str, UnitResult] = {}
        for f in fragments or []:
            for dep in (f.get("deps") or []):
                dep = str(dep)
                if dep in exclude or dep in seeds:
                    continue
                tid = _t._ticket_of(dep)
                if (tid
                        and str(all_tk.get(tid, {}).get("status") or "") == "done"):
                    seeds[dep] = UnitResult(unit_id=dep, domain_id="verify",
                                            status="ok")
        return seeds

    def _resume_task_impl(self, on_event, token: CancellationToken,
                          skip_ids=None) -> TaskResult:
        """断点恢复（P6）：加载 task_state.json——已完成 unit 跳过，pending 继续。

        skip_ids（真测裁决 W3）：暂不参与的 unit（如仍挂起的 needs_confirm）——
        确认单个单元时不得连带重跑其他未确认单元。
        """
        from wuxing.state import load_state
        snap = self._task_start_snapshot()
        state = load_state(self._state_path)
        # E2-5（A10）：needs_answer 挂起单元不得自动重跑（无答复 → 保持挂起；
        # 答复经 answer_unit 显式续跑）
        _answer_pending = {u.unit_id for u in state.units
                           if str(getattr(u, "status", "")) == "needs_answer"}
        # 壳 P1 对齐项③：rejected 视为终态（不重跑）；ok 完成单元一并跳过
        done_ids = {u.unit_id for u in state.units
                    if u.status in ("ok", "rejected")} | set(skip_ids or ()) \
            | _answer_pending
        # W4.3（真测裁决）：重试上限——达上限的碎片不再调度，回退为只调度未尝试碎片
        cap = max(1, int(getattr(self.cfg, "fragment_max_attempts", 2) or 2))
        _all_pending = [f for f in state.fragments
                        if f["fragment_id"] not in done_ids]
        capped = [f for f in _all_pending
                  if int(f.get("attempts") or 0) >= cap]
        pending = [f for f in _all_pending if f not in capped]
        if capped:
            self._retry_cap_excluded = [f["fragment_id"] for f in capped]
            if self.trace is not None:
                self.trace.log("retry_cap_exhausted", "", "",
                               units=self._retry_cap_excluded, cap=cap)
        else:
            self._retry_cap_excluded = []
        units_list = list(state.units)
        ran_ids: set[str] = set()
        if pending:
            # P0 T5：seed 传完整 UnitResult（含 artifacts）——恢复链下游需读
            # 已产出物内容（否则 plan/result 为空 → prompt 变 → 缓存失效）
            seed_full = {u.unit_id: u for u in state.units if u.status == "ok"}
            # P0-1 验证缺陷修复：外部已完成依赖（done 票的验收碎片）跨恢复继续满足
            _planned = {f["fragment_id"] for f in pending}
            seed_full.update(self._external_done_seeds(
                state.fragments, exclude=set(seed_full) | _planned))
            # P4 T3：消息级断点——pending 单元若有 session 存档 → 从历史续跑
            resume_sessions = {}
            for frag in pending:
                hist = self._load_unit_session(frag["fragment_id"])
                if hist:
                    resume_sessions[frag["fragment_id"]] = hist
            remaining = self.orchestrator.run(pending, state.task_text,
                                              on_event=on_event,
                                              seed_done=seed_full,
                                              resume_sessions=resume_sessions,
                                              cancel=token)
            units_list += remaining
            ran_ids = {str(getattr(r, "unit_id", "")) for r in remaining}
        # W5.1（真测裁决）：未在本轮重新调度但仍挂起的单元补发挂起事件——
        # resume_workspace 以新 run 承接时界面必须可见可确认（壳按 unit_id 去重）；
        # 已调度单元的事件由 orchestrator._run_one 发出（此处不重发）。
        latest_view: dict[str, object] = {}
        for u in units_list:
            latest_view[u.unit_id] = u
        for uid, u in latest_view.items():
            if uid in ran_ids or on_event is None:
                continue
            st = str(getattr(u, "status", ""))
            if st == "needs_answer":
                # E2-5（A10）：提问挂起单元恢复态补发（壳问题卡可见可答；
                # 与 needs_confirm 同口径——W5.1）
                from wuxing.events import UnitNeedsAnswer
                _pq = dict(getattr(u, "pending_question", None) or {})
                on_event(UnitNeedsAnswer(
                    unit_id=uid,
                    domain_id=str(getattr(u, "domain_id", "")),
                    question_id=str(_pq.get("question_id", "")),
                    questions=list(_pq.get("questions") or []),
                    reason="待答复（恢复态）——请答复后继续",
                    kind=str(_pq.get("kind", ""))))
                continue
            if st != "needs_confirm":
                continue
            frag = next((f for f in state.fragments
                         if f["fragment_id"] == uid), None)
            if frag is None:
                continue
            from wuxing.events import UnitNeedsConfirm
            _ids = [str(f.get("fragment_id", "")) for f in state.fragments]
            _pos = ((_ids.index(uid) + 1, len(_ids)) if uid in _ids else None)
            on_event(UnitNeedsConfirm(
                unit_id=uid,
                domain_id=str(getattr(u, "domain_id", "")),
                reason="待确认（恢复态）——请确认后继续",
                view=self.orchestrator._confirm_view(frag, "recovered",
                                                     position=_pos),
                impact=self.orchestrator._confirm_impact(frag)))
        artifacts = result_artifacts(units_list)
        status = self._task_status(units_list)
        # C5 修复：metrics 只算一次（原 _collect_metrics 在 report 与 metrics 中重复调用）
        metrics = self._collect_metrics(units_list, snap)
        report = self._build_report(units_list, artifacts, metrics)
        if getattr(self, "_retry_cap_excluded", None):
            report += ("\n\n[重试上限] 以下碎片已达尝试上限"
                       f"（{cap}）未再调度（回退为只调度未尝试碎片）："
                       + "、".join(self._retry_cap_excluded))
        if status == "cancelled" and on_event:
            from wuxing.events import TaskCancelled
            on_event(TaskCancelled())
        self._save_state(state.task_text, state.fragments, units_list,
                         artifacts, status)
        # 审查 F1：断点续跑完成 → 票据状态必须收敛（回写 + 事件）
        self._writeback_and_emit(units_list, on_event)
        return TaskResult(task_text=state.task_text, fragments=state.fragments,
                          units=units_list, artifacts=artifacts, status=status,
                          report=report, metrics=metrics)

    def confirm_unit(self, unit_id: str, approve: bool,
                     reason: str = "", on_event=None) -> TaskResult:
        """P7：单单位确认恢复（P5 挂起 → 确认 → 续跑/驳回）。

        UI 重构阶段 2.5：恢复执行的事件必须可桥接到壳（on_event）——
        否则确认后的单元/产物/任务终态在界面上不可见。
        """
        on_event = self._wrap_events(on_event)
        from wuxing.state import TaskState, load_state, save_state
        snap = self._task_start_snapshot()
        state = load_state(self._state_path)
        frag = next((f for f in state.fragments
                     if f["fragment_id"] == unit_id), None)
        if frag is None:
            raise KeyError(f"unknown unit: {unit_id}")
        units_list = [u for u in state.units if u.unit_id != unit_id]
        if approve:
            # A2 修复（审查）：确认续跑参数完整重建——此前只传 goal/task/
            # fragment_key：verify 无 paths（机制自动兜底失效+盲探索）、
            # execute 无 plan/result（上下文丢失）。
            # 复用编排层依赖注入（同首次运行——done = 已完成单元）。
            done = {u.unit_id: u for u in state.units if u.status == "ok"}
            plan_text, result_text, paths_str = self.orchestrator._dep_context(
                done, frag)
            params = {
                "goal": frag.get("text", state.task_text),
                "task": state.task_text,
                "plan": plan_text,
                "result": result_text,
                "paths": paths_str,
                "granularity": frag.get("granularity"),
                "fragment_key": frag.get("text", state.task_text),
                "deliverables": frag.get("deliverables") or [],
            }
            # bypass_confirm：用户已单次放行——verify 域 always_confirm
            # 不得再次挂起（确认循环 deadlock）
            if on_event is not None:
                from wuxing.events import UnitStarted
                on_event(UnitStarted(unit_id=unit_id,
                                     domain_id=frag["domain"]))
            res = self.orchestrator.runner.run_unit(unit_id, frag["domain"],
                                                    params,
                                                    bypass_confirm=True)
        else:
            # 壳 P1 对齐项③：驳回 = rejected 终态（非 failed——UI 可区分
            # 「用户驳回」与「执行失败」；任务级仍为 failed）
            res = UnitResult(unit_id=unit_id, domain_id=frag["domain"],
                             status="rejected",
                             error=f"rejected by user: {reason}")
        # E2-4（B6）：审计对（decided）——与 confirm_asked 按 unit_id 配对
        if self.trace is not None:
            self.trace.log("confirm_decided", unit_id, frag["domain"],
                           decision=("approve" if approve else "reject"),
                           reason=str(reason or "")[:200],
                           surface="unit_confirm")
        if on_event is not None:
            from wuxing.events import ArtifactWritten, UnitDone, UnitNeedsConfirm
            if res.status == "needs_confirm":
                _ids = [str(f.get("fragment_id", "")) for f in state.fragments]
                _pos = ((_ids.index(unit_id) + 1, len(_ids))
                        if unit_id in _ids else None)
                on_event(UnitNeedsConfirm(
                    unit_id=unit_id,
                    domain_id=frag["domain"],
                    reason="关键碎片待确认",
                    view=self.orchestrator._confirm_view(
                        frag,
                        self.orchestrator.runner.confirm_trigger(
                            frag["domain"]),
                        position=_pos),
                    impact=self.orchestrator._confirm_impact(frag)))
            on_event(UnitDone(unit_id=unit_id, domain_id=frag["domain"],
                              status=res.status))
            for a in res.artifacts:
                on_event(ArtifactWritten(unit_id=unit_id, path=a.path,
                                         kind=a.kind))
        units_list.append(res)
        artifacts = result_artifacts(units_list)
        status = self._task_status(units_list)
        save_state(TaskState(task_text=state.task_text,
                             fragments=state.fragments, units=units_list,
                             artifacts=artifacts, status=status),
                   self._state_path)
        # 真测裁决 W3：批准后继续 DAG——未终结且非挂起的碎片自动续跑
        # （同 resume 机制；仍挂起单元留给各自的确认）
        from wuxing.protocols import CancellationToken
        terminal = {u.unit_id for u in units_list
                    if u.status in ("ok", "rejected")}
        still_pending = {u.unit_id for u in units_list
                         if u.status in ("needs_confirm", "needs_answer")}
        _cap = max(1, int(getattr(self.cfg, "fragment_max_attempts", 2) or 2))
        schedulable = [f for f in state.fragments
                       if f["fragment_id"] not in terminal | still_pending
                       and int(f.get("attempts") or 0) < _cap]
        if schedulable:
            res = self._resume_task_impl(on_event, CancellationToken(),
                                         skip_ids=still_pending)
            self._maybe_close_browser_views(res)
            return res
        # 审查 F1：无下游续跑 → 回写票据（挂起解除后状态收敛）
        self._writeback_and_emit(units_list, on_event)
        metrics = self._collect_metrics(units_list, snap)
        result = TaskResult(task_text=state.task_text, fragments=state.fragments,
                            units=units_list, artifacts=artifacts,
                            status=status,
                            report=self._build_report(units_list, artifacts,
                                                      metrics),
                            metrics=metrics)
        self._maybe_close_browser_views(result)
        return result

    def _load_unit_session(self, unit_id: str) -> list:
        """单元消息级存档（兼容新旧命名：{unit_id}.jsonl / {round}-{unit_id}.jsonl）。"""
        sess_dir = self.state_root / ".wuxing" / "sessions"
        if not sess_dir.exists():
            return []
        from wuxing.session import SessionLog
        cands = [sess_dir / f"{unit_id}.jsonl"] + \
            sorted(sess_dir.glob(f"*-{unit_id}.jsonl"))
        sp = next((c for c in reversed(cands) if c.exists()), None)
        return SessionLog(sp).last_messages() if sp is not None else []

    def _resolve_browser_access(self, domain_id: str, pq: dict,
                                answer_text: str, source_id: str,
                                unit_id: str) -> None:
        """O2-2（P1 T6）：回环确认答复 → 护栏决议（allow=写条目 / deny=拒绝）。

        fail-closed：标签不匹配（自由文本/歧义）按拒绝；待决丢失（进程重启等）
        不写条目并留痕（unknown_pending）——绝不默认放行。
        """
        from wuxing import browser_guard
        meta = dict(pq.get("meta") or {})
        approved = browser_guard.parse_access_decision(answer_text)
        trace_fn = None
        if self.trace is not None:
            def trace_fn(event, **fields):
                self.trace.log(event, unit_id, domain_id, **fields)
        out = browser_guard.resolve_pending(
            str(meta.get("pending_id", "") or ""), approved,
            note=f"source={source_id}", trace=trace_fn)
        if not out.get("resolved") and self.trace is not None:
            self.trace.log("browser_access_decided", unit_id, domain_id,
                           address=str(meta.get("address", "")),
                           approved=False,
                           note=str(out.get("reason", ""))[:120])

    def answer_unit(self, unit_id: str, question_id: str, answer: str,
                    source: str = "text", reason: str = "",
                    on_event=None) -> TaskResult:
        """E2-5（A10）：答复提问并续跑挂起单元（fail-closed/幂等/错配拒绝）。

        - 挂起态校验：单元最新结果必须为 needs_answer 且 question_id 匹配；
          错配 → ValueError（不改状态不重跑）；已答复/已终态 → 幂等忽略 + trace；
        - 答复注入：SessionLog 历史【尾附】答复消息（工具结果信封 + SEC1 净化）
          → runner.run_unit(resume_session=…, bypass_confirm=True) 续跑；
          无存档 → 报错可见（不静默重跑）；
        - 审计对：question_answered（与 question_asked 配对）；
        - 答复后继续 DAG（与 confirm 同口径：终态集 + 仍挂起集均不调度）。
        """
        on_event = self._wrap_events(on_event)
        from wuxing.state import TaskState, load_state, save_state
        snap = self._task_start_snapshot()
        state = load_state(self._state_path)
        frag = next((f for f in state.fragments
                     if f["fragment_id"] == unit_id), None)
        if frag is None:
            raise KeyError(f"unknown unit: {unit_id}")
        latest: dict = {}
        for u in state.units:
            latest[u.unit_id] = u
        cur = latest.get(unit_id)
        qid = str(question_id or "").strip()
        if cur is None or cur.status != "needs_answer":
            # 幂等：已答复/已终态 → 先到为准；不改状态不重跑（迟到答复可见）
            if self.trace is not None:
                self.trace.log("question_answer_ignored", unit_id,
                               str(getattr(cur, "domain_id", frag["domain"])),
                               question_id=qid, reason="already_resolved")
            metrics = self._collect_metrics(state.units, snap)
            result = TaskResult(task_text=state.task_text,
                                fragments=state.fragments, units=state.units,
                                artifacts=state.artifacts, status=state.status,
                                report=self._build_report(state.units,
                                                          state.artifacts,
                                                          metrics),
                                metrics=metrics)
            self._maybe_close_browser_views(result)
            return result
        pq = dict(getattr(cur, "pending_question", None) or {})
        if qid != str(pq.get("question_id", "")):
            raise ValueError(
                f"question_id 错配：期望 {pq.get('question_id', '')!r}，收到 {qid!r}")
        history = self._load_unit_session(unit_id)
        if not history:
            raise ValueError(f"答复失败：单元 {unit_id} 无会话存档（不静默重跑）")
        # 答复注入（SEC1：信封 + 净化——与工具结果同路径；模型可见）
        from wuxing.runner_support import _prepare_tool_result
        _sanitize = bool(getattr(self.cfg, "content_trust_sanitize", True))
        answer_text = str(answer or "").strip()
        source_id = str(source or "text").strip() or "text"
        # O2-2（P1 T6）：浏览器回环确认——先落护栏决议再注入答复续跑
        # （fail-closed：仅认选项标签；歧义/缺失/待决丢失一律按拒绝处理）
        if str(pq.get("kind", "") or "") == "browser_access":
            self._resolve_browser_access(frag["domain"], pq, answer_text,
                                         source_id, unit_id)
        wrapped, _findings = _prepare_tool_result(
            f"[answer] {qid} | 用户答复（{source_id}）：{answer_text}",
            sanitize=_sanitize)
        history = list(history) + [{"role": "user", "content": wrapped}]
        # 参数完整重建（同 confirm 续跑——依赖注入一致，不丢上下文）
        done = {u.unit_id: u for u in state.units if u.status == "ok"}
        plan_text, result_text, paths_str = self.orchestrator._dep_context(
            done, frag)
        params = {
            "goal": frag.get("text", state.task_text),
            "task": state.task_text,
            "plan": plan_text,
            "result": result_text,
            "paths": paths_str,
            "granularity": frag.get("granularity"),
            "fragment_key": frag.get("text", state.task_text),
            "deliverables": frag.get("deliverables") or [],
        }
        # 审计对（answered）——与 question_asked 按 question_id 配对
        if self.trace is not None:
            self.trace.log("question_answered", unit_id, frag["domain"],
                           question_id=qid, source=source_id,
                           answer_chars=len(answer_text),
                           answer=answer_text[:200],
                           reason=str(reason or "")[:200])
        if on_event is not None:
            from wuxing.events import UnitStarted
            on_event(UnitStarted(unit_id=unit_id, domain_id=frag["domain"]))
        res = self.orchestrator.runner.run_unit(
            unit_id, frag["domain"], params, resume_session=history,
            bypass_confirm=True)
        units_list = [u for u in state.units if u.unit_id != unit_id]
        units_list.append(res)
        artifacts = result_artifacts(units_list)
        status = self._task_status(units_list)
        save_state(TaskState(task_text=state.task_text,
                             fragments=state.fragments, units=units_list,
                             artifacts=artifacts, status=status),
                   self._state_path)
        if on_event is not None:
            from wuxing.events import (
                ArtifactWritten,
                QuestionAnswered,
                UnitDone,
                UnitNeedsAnswer,
            )
            on_event(QuestionAnswered(unit_id=unit_id, question_id=qid,
                                      answer=answer_text[:500],
                                      source=source_id))
            if res.status == "needs_answer":
                _pq2 = dict(getattr(res, "pending_question", None) or {})
                on_event(UnitNeedsAnswer(
                    unit_id=unit_id, domain_id=frag["domain"],
                    question_id=str(_pq2.get("question_id", "")),
                    questions=list(_pq2.get("questions") or []),
                    reason="继续提问——请答复后继续",
                    kind=str(_pq2.get("kind", ""))))
            on_event(UnitDone(unit_id=unit_id, domain_id=frag["domain"],
                              status=res.status))
            for a in res.artifacts:
                on_event(ArtifactWritten(unit_id=unit_id, path=a.path,
                                         kind=a.kind))
        # 答复后继续 DAG（同 confirm：终态集 + 仍挂起集均不调度）
        from wuxing.protocols import CancellationToken
        terminal = {u.unit_id for u in units_list
                    if u.status in ("ok", "rejected")}
        still_pending = {u.unit_id for u in units_list
                         if u.status in ("needs_confirm", "needs_answer")}
        _cap = max(1, int(getattr(self.cfg, "fragment_max_attempts", 2) or 2))
        schedulable = [f for f in state.fragments
                       if f["fragment_id"] not in terminal | still_pending
                       and int(f.get("attempts") or 0) < _cap]
        if schedulable:
            res = self._resume_task_impl(on_event, CancellationToken(),
                                         skip_ids=still_pending)
            self._maybe_close_browser_views(res)
            return res
        self._writeback_and_emit(units_list, on_event)
        metrics = self._collect_metrics(units_list, snap)
        result = TaskResult(task_text=state.task_text,
                            fragments=state.fragments, units=units_list,
                            artifacts=artifacts, status=status,
                            report=self._build_report(units_list, artifacts,
                                                      metrics),
                            metrics=metrics)
        self._maybe_archive_reports(result)
        self._maybe_close_browser_views(result)
        return result

    @staticmethod
    def _with_thought_capture(on_event):
        """旁路采集 UnitReasoning（确认/续跑终态重写——思维链补全数据面）。"""
        from wuxing.events import UnitReasoning
        captured: list = []

        def tapped(ev):
            if isinstance(ev, UnitReasoning):
                captured.append(ev)
            if on_event is not None:
                on_event(ev)
        return tapped, captured

    def _sync_conversation_terminal(self, res, captured=None) -> None:
        """对话行终态重写（v35 用户裁决·专项同批）：pending 快照 → 终态。

        确认/续跑完成后，send() 时写入的 pending 快照行不随续跑变化——历史
        卡片/导出只见机械旧摘要。此处按 task_text 定位未收口行并补全
        summary/reply/thoughts/artifacts（ConversationState.rewrite_turn）。
        失败静默（观测面不阻断主流程）。
        """
        try:
            conv = getattr(self.orchestrator, "conversation", None)
            if conv is None or res is None:
                return
            status = str(getattr(res, "status", "") or "")
            if status in ("", "pending", "needs_confirm"):
                return  # 仍挂起/未终态——不做重写
            from wuxing.session_api import (
                build_turn_summary,
                collect_turn_artifacts,
                collect_turn_thoughts,
                reply_for_turn,
            )
            from wuxing.state import load_state
            task_text = str(getattr(load_state(self._state_path),
                                    "task_text", "") or "")
            if task_text == "":
                return
            target = None
            # 锚点 = summary 的 pending 前缀（reply 可能来自挂起前已完成的单元——
            # 不能当作未收口标记：真机 run 2/4 即为此形状，首版少写了这条命中）
            for t in reversed(conv.turns):
                if (str(t.get("user_text", "")) == task_text
                        and str(t.get("summary", "")).startswith("pending")):
                    target = t
                    break
            if target is None:
                # 回退：最近一条同文本且未带 reply 的行（兼容非 pending 状态词）
                for t in reversed(conv.turns):
                    if (str(t.get("user_text", "")) == task_text
                            and not t.get("reply")):
                        target = t
                        break
            if target is None:
                return
            arts = collect_turn_artifacts(res)
            conv.rewrite_turn(
                int(target.get("round", 0) or 0),
                summary=build_turn_summary(res, arts),
                reply=reply_for_turn(self, res),
                thoughts=collect_turn_thoughts(captured or []),
                artifacts=arts)
        except Exception as exc:
            logger.debug("对话行终态重写失败（不阻断）：%s", exc)

    def confirm_units(self, items: list, reason: str = "",
                      on_event=None) -> TaskResult:
        """批量确认（壳 P1 对齐项④）——串行 + 幂等（多挂起场景）。

        items: [(unit_id, approve), ...]。预校验全部 unit_id（未知 → KeyError，
        零副作用）；已终态（非 needs_confirm）单元跳过（重复调用不双跑）。
        on_event：恢复执行的事件转发（UI 重构阶段 2.5）。
        """
        on_event = self._wrap_events(on_event)
        on_event, captured = self._with_thought_capture(on_event)
        from wuxing.state import load_state
        state = load_state(self._state_path)
        known = {u.unit_id for u in state.units}
        for uid, _approve in items:
            if uid not in known:
                raise KeyError(f"unknown unit: {uid}")
        result = None
        for uid, approve in items:
            cur_state = load_state(self._state_path)
            cur = next((u for u in cur_state.units if u.unit_id == uid), None)
            if cur is None or cur.status != "needs_confirm":
                continue  # 幂等：已处理/已终态 → 跳过（不双跑）
            result = self.confirm_unit(uid, approve, reason=reason,
                                       on_event=on_event)
            state = cur_state
        if result is None:
            # 全部跳过（幂等重入）——返回当前状态视图
            units, artifacts = state.units, state.artifacts
            metrics = self._collect_metrics(units, self._cache_snapshot())
            result = TaskResult(task_text=state.task_text,
                                fragments=state.fragments, units=units,
                                artifacts=artifacts, status=state.status,
                                report=self._build_report(units, artifacts,
                                                          metrics),
                                metrics=metrics)
        else:
            if on_event is not None:
                from wuxing.events import TaskDone
                on_event(TaskDone(status=result.status))
        # 确认/续跑路径同样收口归档（真机缺口：续跑单元的 F-* 报告留根目录）；
        # pending 例外见 _maybe_archive_reports（真跑 T-5 误判根因）
        self._maybe_archive_reports(result)
        self._sync_conversation_terminal(result, captured)
        return result

    def _writeback_and_emit(self, units, on_event) -> list[tuple[str, str]]:
        """_writeback_tickets + ImplTicketChanged 事件（回写可见，多路径复用）。"""
        changed = self._writeback_tickets(units)
        if changed and on_event is not None:
            from wuxing.events import ImplTicketChanged
            for tid, status in changed:
                on_event(ImplTicketChanged(id=tid, status=status, spec=""))
        return changed

    def _writeback_tickets(self, units) -> list[tuple[str, str]]:
        """票据执行回写（批 5 + 审查 F1）：状态/产物/碎片 id；返回 [(tid, status)]。

        纪律：
          - 同 unit_id 取最新（resume/确认重跑——旧 cancelled/failed 结果不参与裁决）；
          - 非终态（cancelled/needs_confirm）→ 不回写（票保持 running，断点可续）；
          - 任一单元失败/驳回/验收不通过（verdict_fail）→ failed，否则 done。
        """
        from wuxing import tickets as _tickets
        latest: dict[str, object] = {}
        for u in units or []:
            uid = str(getattr(u, "unit_id", "") or "")
            if uid:
                latest[uid] = u
        per: dict[str, list] = {}
        for u in latest.values():
            tid = _tickets._ticket_of(u.unit_id)
            if tid:
                per.setdefault(tid, []).append(u)
        changed: list[tuple[str, str]] = []
        for tid, us in per.items():
            statuses = {str(getattr(u, "status", "") or "") for u in us}
            if statuses & {"cancelled", "needs_confirm", "needs_answer"}:
                continue  # 断点/挂起：不判失败，保持 running 可续跑
            ok = all(getattr(u, "status", "") == "ok"
                     and not getattr(u, "verdict_fail", False) for u in us)
            status = "done" if ok else "failed"
            paths: list[str] = []
            for u in us:
                paths += [str(p) for p in
                          (getattr(u, "deliverables", None) or [])]
                paths += [str(getattr(a, "path", a))
                          for a in (getattr(u, "artifacts", None) or [])]
            seen: list[str] = []
            for p in paths:
                if p and p not in seen:
                    seen.append(p)
            patch = {"status": status, "artifacts": seen,
                     "fragment_ids": [str(getattr(u, "unit_id", ""))
                                      for u in us]}
            if not ok:
                patch["error"] = _ticket_error_summary(us)
            else:
                patch["error"] = ""  # W4.5：复跑成功清理上轮残留（防误导）
            _tickets.update(self.workdir, tid, patch)
            changed.append((tid, status))
        return changed

    def _build_report(self, units, artifacts, metrics=None) -> str:
        """P5 拆分：委托 reporting.build_report（报告职责内聚——engine 瘦身）。

        E0-A：扩展加载问题注记（broken 可见——不阻断任务结果）。
        """
        from wuxing.reporting import build_report
        report = build_report(units, artifacts, metrics)
        if getattr(self, "_extension_note", ""):
            report += "\n\n" + self._extension_note
        from wuxing.assembly import format_report_note
        _tools = getattr(self, "tools", None)
        note = format_report_note(
            getattr(self, "assembly", None) or {},
            mode=str(getattr(self.cfg, "mode_default", "") or ""),
            tool_count=len(_tools._tools) if _tools is not None else 0)
        if note:
            report += "\n\n" + note
        return report