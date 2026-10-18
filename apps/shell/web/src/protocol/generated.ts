/**
 * 本文件由脚本生成——禁止手改。
 *
 * 契约源：
 *   - wuxing/shell/web/version.py
 *   - wuxing/events.py
 *   - wuxing/shell/web/contracts.py
 * 生成命令：python -m scripts.gen_protocol_ts
 * 对拍检查：python -m scripts.gen_protocol_ts --check
 */
export const API_VERSION = 1 as const;
export const API_PREFIX = "/api/v1" as const;
export const SHELL_VERSION = "p1" as const;

/** 事件类型 → 载荷（信封 data 字段）映射。 */
export interface EventDataMap {
  unit_started: {
    unit_id: string;
    domain_id: string;
  };
  unit_done: {
    unit_id: string;
    domain_id: string;
    status: string;
    failure_class: string;
  };
  unit_auto_retry: {
    unit_id: string;
    domain_id: string;
    kind: string;
    attempt: number;
    candidate: number;
    model: string;
  };
  artifact_written: {
    unit_id: string;
    path: string;
    kind: string;
  };
  task_done: {
    status: string;
  };
  task_cancelled: {
  };
  progress: {
    unit_id: string;
    domain_id: string;
    stage: string;
    eta: string;
  };
  unit_needs_confirm: {
    unit_id: string;
    domain_id: string;
    reason: string;
    impact: Record<string, unknown>;
    view: Record<string, unknown>;
  };
  unit_needs_answer: {
    unit_id: string;
    domain_id: string;
    question_id: string;
    questions: unknown[];
    reason: string;
    kind: string;
  };
  question_answered: {
    unit_id: string;
    question_id: string;
    answer: string;
    source: string;
  };
  unit_state_changed: {
    unit_id: string;
    domain_id: string;
    state: string;
  };
  unit_confirmed: {
    unit_id: string;
    approve: boolean;
    reason: string;
  };
  safety_blocked: {
    unit_id: string;
    domain_id: string;
    tool: string;
    command: string;
    reason: string;
  };
  fsc_audit: {
    unit_id: string;
    domain_id: string;
    ratio: number;
  };
  fsc_switch: {
    unit_id: string;
    domain_id: string;
    ratio: number;
  };
  unit_reasoning: {
    unit_id: string;
    domain_id: string;
    round: number;
    text: string;
  };
  unit_reasoning_delta: {
    unit_id: string;
    domain_id: string;
    round: number;
    text: string;
  };
  needs_design: {
    phase: string;
    round: number;
    questions: unknown[];
    map_path: string;
    map_hash: string;
    reason: string;
  };
  design_phase_changed: {
    session: string;
    from_phase: string;
    to_phase: string;
    round: number;
  };
  map_written: {
    path: string;
    hash: string;
  };
  decision_ticket_changed: {
    session: string;
    id: string;
    status: string;
    statement: string;
  };
  spec_written: {
    path: string;
    slug: string;
    hash: string;
  };
  impl_ticket_changed: {
    id: string;
    status: string;
    spec: string;
  };
  subagent_started: {
    parent_unit_id: string;
    goal: string;
    domain: string;
  };
  subagent_stopped: {
    parent_unit_id: string;
    goal: string;
    domain: string;
    status: string;
    artifacts: number;
  };
  pre_compact: {
    unit_id: string;
    domain_id: string;
    from_round: number;
    to_round: number;
    source_tokens: number;
  };
  post_compact: {
    unit_id: string;
    domain_id: string;
    from_round: number;
    to_round: number;
    status: string;
    summary_tokens: number;
  };
  user_prompt_submit: {
    unit_id: string;
    domain_id: string;
    prompt: string;
  };
  task_submitted: {
    task_text: string;
    session: string;
  };
  task_failed: {
    error: string;
  };
  confirm_error: {
    error: string;
  };
  resume_error: {
    error: string;
  };
  answer_error: {
    error: string;
  };
  worktree_ready: {
    path: string;
  };
  worktree_applied: {
    files: number;
  };
  worktree_apply_error: {
    error: string;
  };
  worktree_discarded: {
    path: string;
  };
}

export type EventType = keyof EventDataMap;

/** 事件信封（EventHub §4.2 契约）。 */
export interface EventEnvelope<TType extends EventType = EventType> {
  v: number;
  epoch: string;
  seq: number;
  ts: number;
  workspace_id: string;
  run_id: string;
  type: TType;
  data: EventDataMap[TType];
}

/** 任意具体事件（判别联合）。 */
export type AnyEvent = { [K in EventType]: EventEnvelope<K> }[EventType];

// ---- REST DTO（响应契约）----

export interface HealthDto {
  status: string;
  version: string;
  pid: number;
  epoch: string;
}

export interface FolderDto {
  id: string;
  name: string;
  collapsed: boolean;
}

export interface WorkspaceDto {
  id: string;
  path: string;
  name: string;
  auto_confirm: boolean;
  status: string;
  folder: string | null;
}

export interface WorkspaceListDto {
  workspaces: WorkspaceDto[];
  folders: FolderDto[];
}

export interface ArtifactDto {
  path: string;
  kind: string;
  mtime: number;
}

export interface ResultDto {
  status: string;
  report: string;
  artifacts: ArtifactDto[];
  metrics: Record<string, unknown>;
}

export interface ConfirmDto {
  unit_id: string;
  domain_id: string;
  reason: string;
  impact: Record<string, unknown>;
  view: Record<string, unknown>;
}

export interface AskQuestionDto {
  title: string;
  options: string[];
  multi: boolean;
}

export interface QuestionListDto {
  unit_id: string;
  domain_id: string;
  question_id: string;
  questions: AskQuestionDto[];
  kind: string;
}

export interface RunDto {
  run_id: string;
  workspace_id: string;
  status: string;
  error: string;
  task_text: string;
  pending_confirms: ConfirmDto[];
  pending_answers: QuestionListDto[];
  result: ResultDto | null;
  session: string;
  isolated: boolean;
  worktree_path: string;
}

export interface WorktreeFileDto {
  status: string;
  path: string;
}

export interface WorktreeReviewDto {
  run_id: string;
  path: string;
  status: string;
  files: WorktreeFileDto[];
  diff: string;
}

export interface WorktreeActionResultDto {
  ok: boolean;
  files: number;
  path: string;
}

export interface UnitDto {
  unit_id: string;
  domain_id: string;
  status: string;
  failure_class: string;
}

export interface SnapshotDto {
  workspace: WorkspaceDto;
  active_run: RunDto | null;
  result: ResultDto | null;
  task_text: string;
  run_id: string;
  units: UnitDto[];
  pending_confirms: ConfirmDto[];
  pending_answers: QuestionListDto[];
  last_seq: number;
  session: string;
  pending_resume: Record<string, unknown> | null;
}

export interface SubmitDto {
  run_id: string;
  workspace_id: string;
  session: string;
  unit: string;
}

export interface ConfigDto {
  values: Record<string, unknown>;
  sources: Record<string, unknown>;
  revision: string;
}

export interface CredentialDto {
  ref: string;
  configured: boolean;
  source: string | null;
  writable: boolean;
  shadowed: boolean;
}

export interface ProviderCatalogDto {
  providers: Record<string, unknown>[];
}

export interface DiscoverModelsDto {
  models: Record<string, unknown>[];
}

export interface SkillDto {
  name: string;
  description: string;
  level: string;
  enabled: boolean;
  model_invocable: boolean;
  user_invocable: boolean;
  allowed_tools: string[];
}

export interface SkillListDto {
  skills: SkillDto[];
}

export interface McpServerToolDto {
  name: string;
  permissions: Record<string, unknown>;
}

export interface McpServerStatsDto {
  connections: number;
  calls: number;
}

export interface McpServerDto {
  name: string;
  command: string;
  args: string[];
  tools: McpServerToolDto[];
  stats: McpServerStatsDto;
}

export interface McpStatusDto {
  enabled: boolean;
  servers: McpServerDto[];
}

export interface RecycleEntryDto {
  id: string;
  kind: string;
  name: string;
  state: string;
}

export interface RecycleListDto {
  entries: RecycleEntryDto[];
}

export interface SessionDto {
  name: string;
  size: number;
  mtime: number;
  path: string;
  title: string;
  branched_from: Record<string, unknown> | null;
}

export interface SessionListDto {
  sessions: SessionDto[];
}

export interface SessionTitleDto {
  name: string;
  title: string;
}

export interface ConversationBranchResultDto {
  created: boolean;
  session: string;
  path: string;
  source: string;
  from_round: number;
  mode: string;
  summary_mode_requested: string;
  summary_mode: string;
  summary: string;
  prefix_rounds: number;
  abandoned_rounds: number;
  redo_text: string | null;
}

export interface RoundFragmentDto {
  unit_id: string;
  domain: string;
  goal: string;
  status: string;
  ts: number;
  artifacts: string[];
  duration_ms: number | null;
  tool_calls: number;
  key: string;
  reuse: number;
  session_file: string;
  parallel: boolean;
}

export interface SessionRoundDto {
  round: number;
  user_text: string;
  summary: string;
  ts: number;
  artifacts: string[];
  parallel: boolean;
  fragments: RoundFragmentDto[];
}

export interface SessionRoundsDto {
  name: string;
  rounds: SessionRoundDto[];
}

export interface UnitSessionGroupDto {
  file: string;
  round: number;
  state: string;
  status: string;
  ts: number;
  messages: Record<string, unknown>[];
}

export interface BoundRoundDto {
  round: number;
  user_text: string;
  summary: string;
  ts: number;
  artifacts: string[];
}

export interface UnitSessionDto {
  unit_id: string;
  files: string[];
  groups: UnitSessionGroupDto[];
  meta: Record<string, unknown>;
  bound_rounds: BoundRoundDto[];
}

export interface ContextSegmentDto {
  key: string;
  label: string;
  chars: number;
  est_tokens: number;
  reference: boolean;
  detail: string;
}

export interface ContextRoundDto {
  round: number;
  summary: string;
  chars: number;
  est_tokens: number;
  omitted: boolean;
  replaced: boolean;
  unit_marked: boolean;
  compacted: boolean;
}

export interface ContextUnknownDto {
  key: string;
  label: string;
}

export interface ContextSourcesDto {
  history: boolean;
  digest: boolean;
  skills: boolean;
  prefix: boolean;
  budget_tokens: number;
}

export interface ContextTrimmedDto {
  key: string;
  chars: number;
}

export interface ContextMessageDto {
  index: number;
  role: string;
  text: string;
  fp_in: string;
  fp_out: string;
  omitted: boolean;
  replaced: boolean;
}

export interface ContextPreviewDto {
  session: string;
  unit_id: string;
  window: number;
  est_tokens: number;
  percent: number;
  band: string;
  golden_pct: number;
  managed_pct: number;
  segments: ContextSegmentDto[];
  rounds: ContextRoundDto[];
  anchor_tokens: number | null;
  anchor_ts: number | null;
  anchor_unit: string;
  unknown: ContextUnknownDto[];
  sources: ContextSourcesDto;
  available: boolean;
  reason: string;
  messages: ContextMessageDto[];
  budget_tokens: number;
  trimmed: ContextTrimmedDto[];
  budget_auto: boolean;
}

export interface ContextPreviewRowDto {
  session: string;
  window: number;
  est_tokens: number;
  percent: number;
  available: boolean;
}

export interface ContextPreviewListDto {
  items: ContextPreviewRowDto[];
}

export interface ContextEditDto {
  ok: boolean;
  preview: ContextPreviewDto;
}

export interface ContextSourcesAckDto {
  ok: boolean;
  sources: ContextSourcesDto;
  preview: ContextPreviewDto;
}

export interface SessionModeDto {
  mode: string;
  variant: string;
  source: string;
  editable: boolean;
  picker_enabled: boolean;
  default_mode: string;
}

export interface DesignQuestionDto {
  q: string;
  recommend: string;
}

export interface DesignDecisionTicketDto {
  id: string;
  statement: string;
  recommend: string;
  blocked_by: string[];
  status: string;
  resolution: string;
  frontier: boolean;
}

export interface DesignDriftDto {
  round: number;
  kind: string;
  id: string;
  detail: string;
  ts: number;
}

export interface DesignStateDto {
  session: string;
  phase: string;
  round: number;
  questions: DesignQuestionDto[];
  tickets: DesignDecisionTicketDto[];
  facts: string[];
  map_path: string;
  map_hash: string;
  map_changed: boolean;
  map_ready: boolean;
  available: boolean;
  spec: SpecDto | null;
  drift: DesignDriftDto[];
}

export interface SpecDto {
  slug: string;
  path: string;
  hash: string;
  ready: boolean;
}

export interface ImplTicketDto {
  id: string;
  title: string;
  goal: string;
  acceptance: string[];
  deps: string[];
  status: string;
  spec: string;
  artifacts: string[];
  fragment_ids: string[];
  error: string;
  claimed_by: string;
  claimed_at: number | null;
  stale: boolean;
}

export interface TicketListDto {
  tickets: ImplTicketDto[];
  spec: string;
}

export interface MapDecisionDto {
  id: string;
  date: string;
  text: string;
  why: string;
  upstream: string[];
  supersedes: string[];
  source: string;
}

export interface MapViewDto {
  available: boolean;
  project: string;
  destination: string;
  route: string[];
  decisions: MapDecisionDto[];
  fog: string[];
  out_of_scope: string[];
  hash: string;
}

export interface HandoffBriefDto {
  available: boolean;
  source_session: string;
  rounds: number;
  brief: string;
}

export interface TrajectoryRoundDto {
  round: number;
  user_text: string;
  summary: string;
  ts: number;
  artifacts: string[];
  parallel: boolean;
  fragments: RoundFragmentDto[];
  session: string;
}

export interface TrajectoryDto {
  rounds: TrajectoryRoundDto[];
  sessions: string[];
}

export interface MaintenanceDto {
  user_dir: string;
  shell_dir: string;
  skills: MaintenanceSkillsDto;
  events: MaintenanceEventsDto;
  workspaces: string[];
  workspace: MaintenanceWorkspaceDto | null;
}

export interface MaintenanceCleanDto {
  ok: boolean;
  removed: string[];
}

export interface BrowserAllowEntryDto {
  address: string;
  label: string;
  fingerprint: string;
  exe: string;
  reason: string;
  first_approved_at: string;
  last_confirmed_at: string;
  last_seen_at: string;
  kind: string;
  resolved_ips: unknown[];
}

export interface BrowserAllowListDto {
  entries: BrowserAllowEntryDto[];
}

export interface BrowserAllowRevokeDto {
  removed: number;
}

export interface BrowserStorageStateDto {
  path: string;
  valid: boolean;
  cookies: number;
  origins: number;
  error: string;
}

export interface DomainPromptEntryDto {
  domain: string;
  title: string;
  builtin_notes: string;
  notes_user: string;
  notes_workspace: string;
  notes_effective: string;
  notes_source: string;
  addendum_user: string;
  addendum_workspace: string;
  addendum_effective: string;
  addendum_source: string;
}

export interface DomainPromptsDto {
  entries: DomainPromptEntryDto[];
  problems: string[];
}

export interface DomainPromptsSaveDto {
  entries: DomainPromptEntryDto[];
  problems: string[];
}

export interface InteractionPrefsDto {
  user: Record<string, unknown>;
  workspace: Record<string, unknown>;
  effective: Record<string, unknown>;
  sources: Record<string, unknown>;
  problems: string[];
}

export interface InteractionSaveDto {
  user: Record<string, unknown>;
  workspace: Record<string, unknown>;
  effective: Record<string, unknown>;
  sources: Record<string, unknown>;
  problems: string[];
}

export interface DecisionEntryDto {
  kind: string;
  ts: number;
  asked_ts: number;
  unit_id: string;
  domain: string;
  object: string;
  status: string;
  reason: string;
  source: string;
}

export interface DecisionListDto {
  entries: DecisionEntryDto[];
  problems: string[];
}

export interface BrowserIdentityEntryDto {
  key: string;
  workspace: string;
  mode: string;
  first_used_at: string;
  last_used_at: string;
}

export interface BrowserIdentityDto {
  mode: string;
  current_key: string;
  entries: BrowserIdentityEntryDto[];
  problems: string[];
  storage_state: BrowserStorageStateDto | null;
}

export interface BrowserIdentityClearDto {
  removed_key: string;
  entries: BrowserIdentityEntryDto[];
  problems: string[];
}

export interface MaintenanceSkillsDto {
  path: string;
  count: number;
}

export interface MaintenanceEventsDto {
  path: string;
  size: number;
}

export interface MaintenanceCacheDto {
  name: string;
  size: number;
}

export interface MaintenanceWorkspaceDto {
  id: string;
  path: string;
  caches: MaintenanceCacheDto[];
  has_state: boolean;
}

export interface AboutDto {
  shell_version: string;
  api_version: number;
  python: string;
  platform: string;
  data_dir: string;
  log_dir: string;
  workspace_count: number;
  assemblies: AssemblyDto[];
}

export interface ExtCommandDto {
  name: string;
  description: string;
  source: string;
  args: ExtCommandArgDto[];
}

export interface ExtCommandArgDto {
  name: string;
  label: string;
  type: string;
  required: boolean;
  default: string | number | boolean | null;
}

export interface AssemblyPresetDto {
  name: string;
  description: string;
  builtin: boolean;
  chain: string[];
  hash: string;
  error: string;
}

export interface AssemblyPresetListDto {
  presets: AssemblyPresetDto[];
}

export interface SessionPresetDto {
  session: string;
  name: string;
}

export interface ExtCommandListDto {
  commands: ExtCommandDto[];
}

export interface ExtCommandRunDto {
  status: string;
  text: string;
  error: string;
}

export interface AssemblyDto {
  workspace_id: string;
  path: string;
  id: string;
  computed_at: number;
  degraded: AssemblyDegradedDto[];
}

export interface AssemblyDegradedDto {
  component: string;
  name: string;
  reason: string;
}

export interface TaskHistoryRowDto {
  run_id: string;
  ws_id: string;
  task_text: string;
  status: string;
  started_at: number;
  ended_at: number;
  artifacts: number;
  error: string;
  isolated: boolean;
  worktree_path: string;
}

export interface TaskHistoryDto {
  history: TaskHistoryRowDto[];
}

export interface NotificationDto {
  seq: number;
  ts: number;
  type: string;
  level: string;
  workspace_id: string;
  workspace_name: string;
  run_id: string;
  status: string;
  reason: string;
  tool: string;
}

export interface NotificationListDto {
  items: NotificationDto[];
  unread: number;
  last_seq: number;
}

export interface BrainTierStatsDto {
  high: number;
  normal: number;
  low: number;
}

export interface BrainCaseDto {
  key: string;
  domain: string;
  model: string;
  tier: string;
  attempts: number;
  success_rate: number;
  last_at: number;
}

export interface BrainStatsDto {
  cases: number;
  attempts: number;
  success_count: number;
  success_rate: number;
  tiers: BrainTierStatsDto;
  capacity: number;
  enabled: boolean;
  recent: BrainCaseDto[];
}

export interface ReportEntryDto {
  name: string;
  path: string;
  size: number;
  mtime: number;
}

export interface ReportListDto {
  reports: ReportEntryDto[];
}

export interface ProvenanceListDto {
  rows: Record<string, unknown>[];
}

export interface TraceListDto {
  rows: Record<string, unknown>[];
}

export interface EventLogDto {
  rows: Record<string, unknown>[];
}

export interface SkillDetailDto {
  name: string;
  content: string;
  scripts: Record<string, unknown>;
  builtin: boolean;
  level: string;
  allowed_tools: string[];
  allowed_tools_missing: string[];
}

export interface SkillInstallDto {
  ok: boolean;
  name: string;
  path: string;
}

export interface SkillRemoveDto {
  ok: boolean;
  name: string;
}

export interface SkillDiscoverDto {
  ok: boolean;
  items: Record<string, unknown>[];
  error: string;
}

export interface McpReloadDto {
  ok: boolean;
  reloaded: number;
}

export interface SearchTaskDto {
  kind: string;
  ws_id: string;
  ws_name: string;
  run_id: string;
  text: string;
  status: string;
  ts: number;
}

export interface SearchSessionDto {
  kind: string;
  ws_id: string;
  ws_name: string;
  name: string;
  snippet: string;
  mtime: number;
}

export interface SearchResultDto {
  tasks: SearchTaskDto[];
  sessions: SearchSessionDto[];
}

export interface DialogPickDto {
  paths: string[];
}
