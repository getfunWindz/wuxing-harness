"""壳协议契约（单一事实来源——TS 类型生成的基础，见 scripts/gen_protocol_ts.py）。

- `ENGINE_EVENT_TYPE_MAP`：引擎事件 dataclass 名 → 事件类型名
  （原 `manager._EVENT_TYPE` 迁移至此：生成器与运行时共用同一份映射）；
- `SHELL_EVENT_PAYLOADS`：壳侧自有事件载荷（与 manager 的 emit data 对齐）。

纪律：新增/改名事件必须先改本文件（或 wuxing/events.py），再运行
`python -m scripts.gen_protocol_ts` 重新生成 TS——禁止手改 generated.ts。
"""
from dataclasses import dataclass, field

ENGINE_EVENT_TYPE_MAP: dict[str, str] = {
    "UnitStarted": "unit_started",
    "UnitDone": "unit_done",
    "UnitAutoRetry": "unit_auto_retry",
    "ArtifactWritten": "artifact_written",
    "TaskDone": "task_done",
    "TaskCancelled": "task_cancelled",
    "ProgressReport": "progress",
    "UnitNeedsConfirm": "unit_needs_confirm",
    "UnitNeedsAnswer": "unit_needs_answer",
    "QuestionAnswered": "question_answered",
    "UnitStateChanged": "unit_state_changed",
    "UnitConfirmed": "unit_confirmed",
    "SafetyBlocked": "safety_blocked",
    "FscAudit": "fsc_audit",
    "FscSwitch": "fsc_switch",
    "UnitReasoning": "unit_reasoning",
    "UnitReasoningDelta": "unit_reasoning_delta",
    "NeedsDesign": "needs_design",
    "DesignPhaseChanged": "design_phase_changed",
    "MapWritten": "map_written",
    "DecisionTicketChanged": "decision_ticket_changed",
    "SpecWritten": "spec_written",
    "ImplTicketChanged": "impl_ticket_changed",
    # E3-2（P1）：生命周期事件（扩展钩子时机面——壳中继按需消费）
    "SubagentStarted": "subagent_started",
    "SubagentStopped": "subagent_stopped",
    "PreCompact": "pre_compact",
    "PostCompact": "post_compact",
    "UserPromptSubmit": "user_prompt_submit",
}


@dataclass
class TaskSubmittedData:
    task_text: str
    # 串台修复（2026-09-25）：任务所属会话——前端据此把任务流限定到所属会话
    session: str = ""


@dataclass
class TaskFailedData:
    error: str


@dataclass
class ConfirmErrorData:
    error: str


@dataclass
class ResumeErrorData:
    error: str


@dataclass
class AnswerErrorData:
    """E2-5（A10）：答复处理失败（引擎异常——壳可见）。"""
    error: str


@dataclass
class WorktreeReadyData:
    """E3-1/R5（T5）：隔离 run 终态——worktree 就绪（Review 面板入口）。"""
    path: str = ""


@dataclass
class WorktreeAppliedData:
    """E3-1/R5（T5）：变更已应用到主检出。"""
    files: int = 0


@dataclass
class WorktreeApplyErrorData:
    """E3-1/R5（T5）：应用失败（冲突可见——不自动消解）。"""
    error: str = ""


@dataclass
class WorktreeDiscardedData:
    """E3-1/R5（T5）：worktree 已丢弃（主检出零改动）。"""
    path: str = ""


SHELL_EVENT_PAYLOADS: dict[str, type] = {
    "task_submitted": TaskSubmittedData,
    "task_failed": TaskFailedData,
    "confirm_error": ConfirmErrorData,
    "resume_error": ResumeErrorData,
    "answer_error": AnswerErrorData,
    # E3-1/R5（T5）：worktree 生命周期事件（隔离 run 的 Review/Apply 链路）
    "worktree_ready": WorktreeReadyData,
    "worktree_applied": WorktreeAppliedData,
    "worktree_apply_error": WorktreeApplyErrorData,
    "worktree_discarded": WorktreeDiscardedData,
}


# ---- REST DTO（响应契约——TS 生成的另一半；与 handler 实际输出对拍）----


@dataclass
class HealthDto:
    status: str
    version: str
    pid: int
    epoch: str


@dataclass
class FolderDto:
    id: str
    name: str
    collapsed: bool


@dataclass
class WorkspaceDto:
    id: str
    path: str
    name: str
    auto_confirm: bool
    status: str
    folder: str | None


@dataclass
class WorkspaceListDto:
    workspaces: list[WorkspaceDto]
    folders: list[FolderDto]


@dataclass
class ArtifactDto:
    path: str
    kind: str
    # A6（W1）：直通展示筛选/排序用——工作区内 stat；缺失/越界 = 0.0
    mtime: float


@dataclass
class ResultDto:
    status: str
    report: str
    artifacts: list[ArtifactDto]
    metrics: dict


@dataclass
class ConfirmDto:
    unit_id: str
    domain_id: str
    reason: str
    # M7 #7（A2）：影响清单（tools/deliverables/depends/summary）——旧壳无、新壳补全
    impact: dict = field(default_factory=dict)
    # 重大优化清单 #2（A′）：结构化四要素视图（壳侧统一渲染）
    view: dict = field(default_factory=dict)


@dataclass
class AskQuestionDto:
    """E2-5（A10）：单题（壳问题卡渲染用；首选项=推荐答案语义）。"""
    title: str
    options: list[str]
    multi: bool = False


@dataclass
class QuestionListDto:
    """E2-5（A10）：待答问题组（快照/答复回执共用形状）。"""
    unit_id: str
    domain_id: str
    question_id: str
    questions: list[AskQuestionDto]
    # 重大优化清单 #2：来源分型（""=模型 / "browser_access"=机制）
    kind: str = ""


@dataclass
class RunDto:
    run_id: str
    workspace_id: str
    status: str
    error: str
    task_text: str
    pending_confirms: list[ConfirmDto]
    pending_answers: list[QuestionListDto]
    result: ResultDto | None
    # 串台修复（2026-09-25）：run 所属会话（快照/运行记录→前端会话隔离）
    session: str = ""
    # E3-1/R5（T4）：隔离运行——worktree 执行档（壳 Review/Apply 据路径与状态呈现）
    isolated: bool = False
    worktree_path: str = ""


@dataclass
class UnitDto:
    unit_id: str
    domain_id: str
    status: str
    failure_class: str = ""   # S1-C：失败分类（快照还原用）


@dataclass
class SnapshotDto:
    workspace: WorkspaceDto
    active_run: RunDto | None
    result: ResultDto | None
    task_text: str
    run_id: str
    units: list[UnitDto]
    pending_confirms: list[ConfirmDto]
    pending_answers: list[QuestionListDto]
    last_seq: int
    # 串台修复（2026-09-25）：最近 run 所属会话（前端任务流按会话隔离）
    session: str = ""
    # M7 #8（A3）：重启后挂起确认的可发现性（无内存 run 时读 task_state.json）
    pending_resume: dict | None = None


@dataclass
class AssemblyDegradedDto:
    """G5：装配降级项（可降级失败带原因；观察层）。"""
    component: str
    name: str
    reason: str


@dataclass
class AssemblyDto:
    """G5：工作区当前装配代（内容指纹 id + 降级项）。"""
    workspace_id: str
    path: str
    id: str
    computed_at: float
    degraded: list[AssemblyDegradedDto]


@dataclass
class AssemblyPresetDto:
    """E2-4/E2-UI：装配预设（name/description/builtin + 解析态 chain/hash/error）。"""
    name: str
    description: str
    builtin: bool
    chain: list[str] = field(default_factory=list)
    hash: str = ""
    error: str = ""


@dataclass
class AssemblyPresetListDto:
    presets: list[AssemblyPresetDto]


@dataclass
class SessionPresetDto:
    """E2-4：会话装配绑定（name 空 = 跟随默认）。"""
    session: str
    name: str


@dataclass
class ExtCommandArgDto:
    """E2-UI：扩展命令参数声明（UI 逐字段表单；default 与 type 相符）。"""
    name: str
    label: str
    type: str
    required: bool
    default: str | int | float | bool | None


@dataclass
class ExtCommandDto:
    """E2-3/E2-UI：扩展命令（名称/说明/来源/参数声明——命令面板与 CLI 用）。"""
    name: str
    description: str
    source: str
    args: list[ExtCommandArgDto] = field(default_factory=list)


@dataclass
class ExtCommandListDto:
    commands: list[ExtCommandDto]


@dataclass
class ExtCommandRunDto:
    """E2-3：扩展命令执行结果。"""
    status: str
    text: str = ""
    error: str = ""


@dataclass
class AboutDto:
    """M7 C1（MG-15）：关于与诊断（只读——版本/环境/路径；G5 增装配代）。"""
    shell_version: str
    api_version: int
    python: str
    platform: str
    data_dir: str
    log_dir: str
    workspace_count: int
    assemblies: list[AssemblyDto]


@dataclass
class SubmitDto:
    run_id: str
    workspace_id: str
    # 修复①（2026-09-20）：本次任务所属会话文件（自动新建/续写）
    session: str = ""
    # 碎片会话后半程（2026-09-22）：碎片内提交的绑定身份（空 = 主会话提交）
    unit: str = ""


# ---- 设置面 DTO（P2-S1：模型与供应商 / 机制调优数据源）----


@dataclass
class ConfigDto:
    values: dict
    sources: dict
    revision: str


@dataclass
class CredentialDto:
    ref: str
    configured: bool
    source: str | None
    writable: bool
    shadowed: bool


@dataclass
class ProviderCatalogDto:
    providers: list[dict]


@dataclass
class DiscoverModelsDto:
    models: list[dict]


# ---- 观测面 DTO（P2-S10：dock 技能/MCP 视图）----


@dataclass
class SkillDto:
    name: str
    description: str
    level: str
    enabled: bool = True
    # E2-1（B5）：调用策略——壳选择器按 user_invocable 过滤；
    # model_invocable=false 的技能由壳在提交时注入正文（模型不可 load_skill）。
    model_invocable: bool = True
    user_invocable: bool = True
    # A14：allowed-tools 声明（Phase 1——只声明不授权）
    allowed_tools: list[str] = field(default_factory=list)


@dataclass
class SkillListDto:
    skills: list[SkillDto]


@dataclass
class McpServerToolDto:
    name: str
    permissions: dict


@dataclass
class McpServerStatsDto:
    connections: int
    calls: int


@dataclass
class McpServerDto:
    name: str
    command: str
    args: list[str]
    tools: list[McpServerToolDto]
    stats: McpServerStatsDto


@dataclass
class McpStatusDto:
    enabled: bool
    servers: list[McpServerDto]


@dataclass
class RecycleEntryDto:
    id: str
    kind: str
    name: str
    state: str


@dataclass
class RecycleListDto:
    entries: list[RecycleEntryDto]


@dataclass
class SessionDto:
    name: str
    size: int
    mtime: float
    path: str
    title: str = ""
    branched_from: dict | None = None


@dataclass
class SessionTitleDto:
    name: str
    title: str


@dataclass
class ConversationBranchResultDto:
    """G1：对话分支创建结果（POST /conversations/branch）。"""
    created: bool
    session: str
    path: str
    source: str
    from_round: int
    mode: str
    summary_mode_requested: str
    summary_mode: str
    summary: str
    prefix_rounds: int
    abandoned_rounds: int
    redo_text: str | None = None


@dataclass
class SessionListDto:
    sessions: list[SessionDto]


# ---- 工作区域轮次化/碎片会话/轨迹 DTO（2026-09-21）----


@dataclass
class RoundFragmentDto:
    unit_id: str
    domain: str
    goal: str
    status: str
    ts: float
    artifacts: list[str]
    duration_ms: int | None
    tool_calls: int
    key: str
    reuse: int
    session_file: str
    parallel: bool


@dataclass
class SessionRoundDto:
    round: int
    user_text: str
    summary: str
    ts: float
    artifacts: list[str]
    parallel: bool
    fragments: list[RoundFragmentDto]


@dataclass
class SessionRoundsDto:
    name: str
    rounds: list[SessionRoundDto]


@dataclass
class UnitSessionGroupDto:
    file: str
    round: int
    state: str
    status: str
    ts: float
    messages: list[dict]


@dataclass
class ContextSegmentDto:
    """上下文投影段（B 期）。"""
    key: str
    label: str
    chars: int
    est_tokens: int
    reference: bool
    detail: str = ""


@dataclass
class ContextRoundDto:
    round: int
    summary: str
    chars: int
    est_tokens: int
    omitted: bool
    replaced: bool
    unit_marked: bool = False
    compacted: bool = False


@dataclass
class ContextUnknownDto:
    key: str
    label: str


@dataclass
class ContextSourcesDto:
    """上下文来源开关（A 期 · 会话级持久；默认全开）。"""
    history: bool = True
    digest: bool = True
    skills: bool = True
    prefix: bool = True
    budget_tokens: int = 0


@dataclass
class ContextTrimmedDto:
    """预算裁剪记录（段 key + 被裁字符数）。"""
    key: str
    chars: int


@dataclass
class ContextMessageDto:
    """碎片会话消息明细（A2 三键：index + 双指纹 + 编辑状态）。"""
    index: int
    role: str
    text: str
    fp_in: str
    fp_out: str
    omitted: bool = False
    replaced: bool = False


@dataclass
class ContextPreviewDto:
    """会话「下次运行注入」投影（窗口/分段/轮次/消息/实测锚点/来源开关）。"""
    session: str
    unit_id: str
    window: int
    est_tokens: int
    percent: float
    band: str
    golden_pct: float
    managed_pct: float
    segments: list[ContextSegmentDto]
    rounds: list[ContextRoundDto]
    anchor_tokens: int | None
    anchor_ts: float | None
    anchor_unit: str
    unknown: list[ContextUnknownDto]
    sources: ContextSourcesDto
    available: bool
    reason: str
    messages: list[ContextMessageDto] = field(default_factory=list)
    budget_tokens: int = 0
    trimmed: list[ContextTrimmedDto] = field(default_factory=list)
    budget_auto: bool = False


@dataclass
class ContextPreviewRowDto:
    session: str
    window: int
    est_tokens: int
    percent: float
    available: bool


@dataclass
class ContextPreviewListDto:
    items: list[ContextPreviewRowDto]


@dataclass
class ContextEditDto:
    ok: bool
    preview: ContextPreviewDto


@dataclass
class ContextSourcesAckDto:
    """来源开关读取/写入响应（含刷新后的投影——口径同步）。"""
    ok: bool
    sources: ContextSourcesDto
    preview: ContextPreviewDto


@dataclass
class SessionModeDto:
    """会话模式（双模式批 1）：mode/variant + 来源与可编辑性
    （editable = 空白会话才可切——机制守卫，设计 §3.1/§8）。"""
    mode: str
    variant: str
    source: str
    editable: bool
    picker_enabled: bool
    default_mode: str


@dataclass
class DesignQuestionDto:
    """循迹设计问题（双模式批 3）：问题 + 推荐答案。"""
    q: str
    recommend: str


@dataclass
class DesignDecisionTicketDto:
    """决策票据（二期批 2 · 设计 §6.1）：open 票据 + frontier（无未决阻塞）。"""
    id: str
    statement: str
    recommend: str
    blocked_by: list[str]
    status: str
    resolution: str
    frontier: bool


@dataclass
class DesignDriftDto:
    """设计流漂移记录（C5）：机械校验结果（unknown-ticket /
    dangling-blocked-by / spec-with-open-tickets）。"""
    round: int
    kind: str
    id: str
    detail: str
    ts: float


@dataclass
class ImplTicketDto:
    """实施票据（二期批 4 · 设计 §8.1）：垂直切片执行清单。

    G8（2026-09-26）：认领可见——claimed_by 为会话名（空 = 无认领）。
    """
    id: str
    title: str
    goal: str
    acceptance: list[str]
    deps: list[str]
    status: str
    spec: str
    artifacts: list[str]
    fragment_ids: list[str]
    error: str
    claimed_by: str = ""
    claimed_at: float | None = None
    stale: bool = False


@dataclass
class TicketListDto:
    tickets: list[ImplTicketDto]
    spec: str


@dataclass
class SpecDto:
    """规格指针（二期批 3 · 设计 §7）：临时物——ready=文件在场。"""
    slug: str
    path: str
    hash: str
    ready: bool


@dataclass
class DesignStateDto:
    """循迹设计态（双模式批 3 · 设计 §5.3/§7）：阶段/轮次/问题/事实/地图指针。"""
    session: str
    phase: str
    round: int
    questions: list[DesignQuestionDto]
    tickets: list[DesignDecisionTicketDto]
    facts: list[str]
    map_path: str
    map_hash: str
    map_changed: bool
    map_ready: bool
    available: bool
    spec: SpecDto | None = None
    drift: list[DesignDriftDto] = field(default_factory=list)


@dataclass
class MapDecisionDto:
    """结构化决策（二期批 2 · 设计 §6.2）：分岔 DAG 节点（旧自由文本→id=""）。"""
    id: str
    date: str
    text: str
    why: str
    upstream: list[str]
    supersedes: list[str]
    source: str


@dataclass
class MapViewDto:
    """工作区地图只读视图（双模式批 3 · 设计 §5.4）：受控段 + 哈希。"""
    available: bool
    project: str
    destination: str
    route: list[str]
    decisions: list[MapDecisionDto]
    fog: list[str]
    out_of_scope: list[str]
    hash: str


@dataclass
class HandoffBriefDto:
    """新会话承接简报（双模式批 4 · 设计 §6）：确定性拼装（无 LLM）。"""
    available: bool
    source_session: str
    rounds: int
    brief: str


@dataclass
class BoundRoundDto:
    """碎片绑定轮次（碎片会话内提交的会话轮——设计 §3.3/§4）。"""
    round: int
    user_text: str
    summary: str
    ts: float
    artifacts: list[str]


@dataclass
class UnitSessionDto:
    unit_id: str
    files: list[str]
    groups: list[UnitSessionGroupDto]
    meta: dict
    # 碎片会话后半程（2026-09-22）：该 unit 的绑定轮次（空列表恒在——DTO 对拍口径）
    bound_rounds: list[BoundRoundDto] = field(default_factory=list)


@dataclass
class TrajectoryRoundDto(SessionRoundDto):
    session: str = ""


@dataclass
class TrajectoryDto:
    rounds: list[TrajectoryRoundDto]
    sessions: list[str]


# ---- 数据与维护面 DTO（设置中心「数据」分区——GET /api/v1/maintenance）----


@dataclass
class MaintenanceSkillsDto:
    path: str
    count: int


@dataclass
class MaintenanceEventsDto:
    path: str
    size: int


@dataclass
class MaintenanceCacheDto:
    name: str
    size: int


@dataclass
class MaintenanceWorkspaceDto:
    id: str
    path: str
    caches: list[MaintenanceCacheDto]
    has_state: bool


@dataclass
class MaintenanceDto:
    user_dir: str
    shell_dir: str
    skills: MaintenanceSkillsDto
    events: MaintenanceEventsDto
    workspaces: list[str]
    workspace: MaintenanceWorkspaceDto | None = None


@dataclass
class MaintenanceCleanDto:
    ok: bool
    removed: list[str]


# ---- 浏览器允许条目 DTO（O2-2 P3 §11.3：设置「数据」分区运维面）----


@dataclass
class BrowserAllowEntryDto:
    address: str
    label: str
    fingerprint: str
    exe: str
    reason: str
    first_approved_at: str
    last_confirmed_at: str
    last_seen_at: str
    kind: str = "loopback"              # §11.5-③：loopback | lan
    resolved_ips: list = field(default_factory=list)


@dataclass
class BrowserAllowListDto:
    entries: list[BrowserAllowEntryDto]


@dataclass
class BrowserAllowRevokeDto:
    removed: int


# ---- 域提示词 DTO（重大优化清单 #3：设置「域提示词」分区）----


@dataclass
class DomainPromptEntryDto:
    domain: str
    title: str
    builtin_notes: str
    notes_user: str
    notes_workspace: str
    notes_effective: str
    notes_source: str
    addendum_user: str
    addendum_workspace: str
    addendum_effective: str
    addendum_source: str


@dataclass
class DomainPromptsDto:
    entries: list[DomainPromptEntryDto]
    problems: list[str]


@dataclass
class DomainPromptsSaveDto:
    entries: list[DomainPromptEntryDto]
    problems: list[str]


# ---- 交互偏好 DTO（#2 Phase 1.5：设置「交互与文案」块）----


@dataclass
class InteractionPrefsDto:
    """#2 Phase 1.5：交互偏好（两层原值 + 生效值 + 来源 + 诊断）。"""
    user: dict = field(default_factory=dict)
    workspace: dict = field(default_factory=dict)
    effective: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


@dataclass
class InteractionSaveDto:
    """保存回执（与 prefs DTO 同形）。"""
    user: dict = field(default_factory=dict)
    workspace: dict = field(default_factory=dict)
    effective: dict = field(default_factory=dict)
    sources: dict = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


# ---- 决策历史 DTO（#2 T-5：设置「决策历史」只读块）----


@dataclass
class DecisionEntryDto:
    """#2 T-5：单条决策（trace 审计对还原）。"""
    kind: str
    ts: float
    asked_ts: float
    unit_id: str
    domain: str
    object: str
    status: str
    reason: str
    source: str


@dataclass
class DecisionListDto:
    entries: list[DecisionEntryDto]
    problems: list[str]


# ---- 浏览器身份 DTO（O2-2 §11.5-①：设置「浏览器身份」块）----


@dataclass
class BrowserIdentityEntryDto:
    key: str
    workspace: str
    mode: str
    first_used_at: str
    last_used_at: str


@dataclass
class BrowserStorageStateDto:
    path: str
    valid: bool
    cookies: int
    origins: int
    error: str


@dataclass
class BrowserIdentityDto:
    mode: str
    current_key: str
    entries: list[BrowserIdentityEntryDto]
    problems: list[str]
    storage_state: "BrowserStorageStateDto | None" = None


@dataclass
class BrowserIdentityClearDto:
    removed_key: str
    entries: list[BrowserIdentityEntryDto]
    problems: list[str]


# ---- 观测面 DTO（P2-M4：dock 任务/使用/溯源/日志/通知/智脑/报告）----


@dataclass
class TaskHistoryRowDto:
    run_id: str
    ws_id: str
    task_text: str
    status: str
    started_at: float
    ended_at: float
    artifacts: int
    error: str
    # E3-1/R5（T4）：隔离运行标记（重启后 Review/Apply 入口）
    isolated: bool = False
    worktree_path: str = ""


@dataclass
class WorktreeFileDto:
    """E3-1/R5（T5）：worktree 变更文件条目。"""
    status: str
    path: str


@dataclass
class WorktreeReviewDto:
    """E3-1/R5（T5）：Review 视图（文件清单 + diff）。"""
    run_id: str
    path: str
    status: str
    files: list[WorktreeFileDto]
    diff: str


@dataclass
class WorktreeActionResultDto:
    """E3-1/R5（T5）：Apply/Discard 回执。"""
    ok: bool
    files: int = 0
    path: str = ""


@dataclass
class TaskHistoryDto:
    history: list[TaskHistoryRowDto]


@dataclass
class NotificationDto:
    seq: int
    ts: float
    type: str
    level: str
    workspace_id: str
    workspace_name: str
    run_id: str
    status: str
    reason: str
    tool: str


@dataclass
class NotificationListDto:
    items: list[NotificationDto]
    unread: int
    last_seq: int


@dataclass
class BrainTierStatsDto:
    high: int
    normal: int
    low: int


@dataclass
class BrainCaseDto:
    key: str
    domain: str
    model: str
    tier: str
    attempts: int
    success_rate: float
    last_at: float


@dataclass
class BrainStatsDto:
    cases: int
    attempts: int
    success_count: int
    success_rate: float
    tiers: BrainTierStatsDto
    capacity: int
    enabled: bool
    recent: list[BrainCaseDto]


@dataclass
class ReportEntryDto:
    name: str
    path: str
    size: int
    mtime: float


@dataclass
class ReportListDto:
    reports: list[ReportEntryDto]


@dataclass
class ProvenanceListDto:
    rows: list[dict]


@dataclass
class TraceListDto:
    rows: list[dict]


@dataclass
class EventLogDto:
    rows: list[dict]


# ---- 管理面 DTO（P2-M5：dock 技能/MCP 管理）----


@dataclass
class SkillDetailDto:
    name: str
    content: str
    scripts: dict
    builtin: bool
    level: str
    allowed_tools: list[str] = field(default_factory=list)
    allowed_tools_missing: list[str] = field(default_factory=list)


@dataclass
class SkillInstallDto:
    ok: bool
    name: str
    path: str


@dataclass
class SkillRemoveDto:
    ok: bool
    name: str


@dataclass
class SkillDiscoverDto:
    ok: bool
    items: list[dict]
    error: str


@dataclass
class McpReloadDto:
    ok: bool
    reloaded: int


# ---- 主视图面 DTO（P2-M6：搜索 / 系统对话框桥）----


@dataclass
class SearchTaskDto:
    kind: str
    ws_id: str
    ws_name: str
    run_id: str
    text: str
    status: str
    ts: float


@dataclass
class SearchSessionDto:
    kind: str
    ws_id: str
    ws_name: str
    name: str
    snippet: str
    mtime: float


@dataclass
class SearchResultDto:
    tasks: list[SearchTaskDto]
    sessions: list[SearchSessionDto]


@dataclass
class DialogPickDto:
    paths: list[str]


REST_DTOS: dict[str, type] = {
    "HealthDto": HealthDto,
    "FolderDto": FolderDto,
    "WorkspaceDto": WorkspaceDto,
    "WorkspaceListDto": WorkspaceListDto,
    "ArtifactDto": ArtifactDto,
    "ResultDto": ResultDto,
    "ConfirmDto": ConfirmDto,
    "AskQuestionDto": AskQuestionDto,
    "QuestionListDto": QuestionListDto,
    "RunDto": RunDto,
    "WorktreeFileDto": WorktreeFileDto,
    "WorktreeReviewDto": WorktreeReviewDto,
    "WorktreeActionResultDto": WorktreeActionResultDto,
    "UnitDto": UnitDto,
    "SnapshotDto": SnapshotDto,
    "SubmitDto": SubmitDto,
    "ConfigDto": ConfigDto,
    "CredentialDto": CredentialDto,
    "ProviderCatalogDto": ProviderCatalogDto,
    "DiscoverModelsDto": DiscoverModelsDto,
    "SkillDto": SkillDto,
    "SkillListDto": SkillListDto,
    "McpServerToolDto": McpServerToolDto,
    "McpServerStatsDto": McpServerStatsDto,
    "McpServerDto": McpServerDto,
    "McpStatusDto": McpStatusDto,
    "RecycleEntryDto": RecycleEntryDto,
    "RecycleListDto": RecycleListDto,
    "SessionDto": SessionDto,
    "SessionListDto": SessionListDto,
    "SessionTitleDto": SessionTitleDto,
    "ConversationBranchResultDto": ConversationBranchResultDto,
    "RoundFragmentDto": RoundFragmentDto,
    "SessionRoundDto": SessionRoundDto,
    "SessionRoundsDto": SessionRoundsDto,
    "UnitSessionGroupDto": UnitSessionGroupDto,
    "BoundRoundDto": BoundRoundDto,
    "UnitSessionDto": UnitSessionDto,
    "ContextSegmentDto": ContextSegmentDto,
    "ContextRoundDto": ContextRoundDto,
    "ContextUnknownDto": ContextUnknownDto,
    "ContextSourcesDto": ContextSourcesDto,
    "ContextTrimmedDto": ContextTrimmedDto,
    "ContextMessageDto": ContextMessageDto,
    "ContextPreviewDto": ContextPreviewDto,
    "ContextPreviewRowDto": ContextPreviewRowDto,
    "ContextPreviewListDto": ContextPreviewListDto,
    "ContextEditDto": ContextEditDto,
    "ContextSourcesAckDto": ContextSourcesAckDto,
    "SessionModeDto": SessionModeDto,
    "DesignQuestionDto": DesignQuestionDto,
    "DesignDecisionTicketDto": DesignDecisionTicketDto,
    "DesignDriftDto": DesignDriftDto,
    "DesignStateDto": DesignStateDto,
    "SpecDto": SpecDto,
    "ImplTicketDto": ImplTicketDto,
    "TicketListDto": TicketListDto,
    "MapDecisionDto": MapDecisionDto,
    "MapViewDto": MapViewDto,
    "HandoffBriefDto": HandoffBriefDto,
    "TrajectoryRoundDto": TrajectoryRoundDto,
    "TrajectoryDto": TrajectoryDto,
    "MaintenanceDto": MaintenanceDto,
    "MaintenanceCleanDto": MaintenanceCleanDto,
    "BrowserAllowEntryDto": BrowserAllowEntryDto,
    "BrowserAllowListDto": BrowserAllowListDto,
    "BrowserAllowRevokeDto": BrowserAllowRevokeDto,
    "BrowserStorageStateDto": BrowserStorageStateDto,
    "DomainPromptEntryDto": DomainPromptEntryDto,
    "DomainPromptsDto": DomainPromptsDto,
    "DomainPromptsSaveDto": DomainPromptsSaveDto,
    "InteractionPrefsDto": InteractionPrefsDto,
    "InteractionSaveDto": InteractionSaveDto,
    "DecisionEntryDto": DecisionEntryDto,
    "DecisionListDto": DecisionListDto,
    "BrowserIdentityEntryDto": BrowserIdentityEntryDto,
    "BrowserIdentityDto": BrowserIdentityDto,
    "BrowserIdentityClearDto": BrowserIdentityClearDto,
    "MaintenanceSkillsDto": MaintenanceSkillsDto,
    "MaintenanceEventsDto": MaintenanceEventsDto,
    "MaintenanceCacheDto": MaintenanceCacheDto,
    "MaintenanceWorkspaceDto": MaintenanceWorkspaceDto,
    "AboutDto": AboutDto,
    "ExtCommandDto": ExtCommandDto,
    "ExtCommandArgDto": ExtCommandArgDto,
    "AssemblyPresetDto": AssemblyPresetDto,
    "AssemblyPresetListDto": AssemblyPresetListDto,
    "SessionPresetDto": SessionPresetDto,
    "ExtCommandListDto": ExtCommandListDto,
    "ExtCommandRunDto": ExtCommandRunDto,
    "AssemblyDto": AssemblyDto,
    "AssemblyDegradedDto": AssemblyDegradedDto,
    "TaskHistoryRowDto": TaskHistoryRowDto,
    "TaskHistoryDto": TaskHistoryDto,
    "NotificationDto": NotificationDto,
    "NotificationListDto": NotificationListDto,
    "BrainTierStatsDto": BrainTierStatsDto,
    "BrainCaseDto": BrainCaseDto,
    "BrainStatsDto": BrainStatsDto,
    "ReportEntryDto": ReportEntryDto,
    "ReportListDto": ReportListDto,
    "ProvenanceListDto": ProvenanceListDto,
    "TraceListDto": TraceListDto,
    "EventLogDto": EventLogDto,
    "SkillDetailDto": SkillDetailDto,
    "SkillInstallDto": SkillInstallDto,
    "SkillRemoveDto": SkillRemoveDto,
    "SkillDiscoverDto": SkillDiscoverDto,
    "McpReloadDto": McpReloadDto,
    "SearchTaskDto": SearchTaskDto,
    "SearchSessionDto": SearchSessionDto,
    "SearchResultDto": SearchResultDto,
    "DialogPickDto": DialogPickDto,
}
