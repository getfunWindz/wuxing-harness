/** 任务服务：活动任务的事件投影 + 命令（提交/确认/取消/续跑）。 */
import type {
  AnyEvent, ConfirmDto, QuestionListDto, ResultDto, SnapshotDto, SubmitDto,
  WorktreeActionResultDto, WorktreeFileDto, WorktreeReviewDto,
} from "../../protocol/generated.ts";
import type { CommandBus } from "../commands.ts";
import type { RestClient } from "../connection/rest.ts";
import { createProjection, type Projection } from "../projection/store.ts";

export type UnitStatus = "running" | "ok" | "failed" | "confirm" | "answer";

/** 确认项：服务端 REST 契约的 [unit_id, approve] 对（manager.confirm 解包 pairs）。 */
export type ConfirmItem = readonly [string, boolean];

export interface TaskRow {
  readonly unitId: string;
  readonly domainId: string;
  readonly status: UnitStatus;
  readonly detail: string;
  /** 模型自报的预计时间（ProgressReport.eta；为空即未知） */
  readonly eta: string;
  /** S1-C：失败分类（""|"provider"|"budget"|"stalled"） */
  readonly failureClass: string;
  /** S1-C：自动恢复痕迹（"retry"|"fallback"|""） */
  readonly autoRetryKind: string;
  /** S1-C：retry=重试次数 / fallback=候选序号 */
  readonly autoRetryN: number;
}

/** 安全拦截（SafetyBlocked 事件归约——流内警示卡）。 */
export interface SafetyRow {
  readonly unitId: string;
  readonly domainId: string;
  readonly tool: string;
  readonly command: string;
  readonly reason: string;
  readonly seq: number;
}

/** FSC 观测行（FscAudit/FscSwitch 事件归约——流内提示行）。 */
export interface FscRow {
  readonly unitId: string;
  readonly domainId: string;
  readonly ratio: number;
  readonly kind: "audit" | "switch";
  readonly seq: number;
}

/** 思维链条目（P2-M6：`unit_reasoning` 流事件归约）。
 *
 * streaming（Task 3 回归修复）：delta 流进行中标记——整段 `unit_reasoning`
 * 只合并【本次】delta 流（同一 unit+round 的旧已完成行不得被覆盖）。
 */
export interface ThoughtRow {
  readonly unitId: string;
  readonly round: number;
  readonly text: string;
  readonly streaming?: boolean;
}

/** 单元产物条目（P2-M6：`artifact_written` 流事件归约——流内可下载）。 */
export interface UnitArtifactRow {
  readonly unitId: string;
  readonly path: string;
  readonly kind: string;
}

export type TaskStatus =
  | "idle" | "running" | "pending" | "done" | "partial"
  | "failed" | "cancelled" | "error" | "needs_design";

/** 重启后挂起确认（M7 #8 · A3）：快照 pending_resume 投影。 */
export interface PendingResume {
  readonly taskText: string;
  readonly units: readonly { readonly unitId: string; readonly domainId: string }[];
}

/** E3-1/R5（T5）：隔离运行 worktree（worktree_ready 事件 → Review 卡）。
 *
 * notice 为结构化提示（视图经 i18n 渲染——服务层不拼文案）：
 * applied（带文件数）/ review_failed / apply_failed / discard_failed。
 */
export interface WorktreeNotice {
  readonly kind: "applied" | "review_failed" | "apply_failed" | "discard_failed";
  readonly n?: number;
  readonly msg?: string;
}

export interface WorktreeState {
  readonly runId: string;
  readonly path: string;
  readonly files: readonly WorktreeFileDto[];
  readonly diff: string;
  /** 已取过 review 数据（防渲染循环重复取数） */
  readonly reviewed: boolean;
  readonly busy: boolean;
  readonly notice: WorktreeNotice | null;
}

export interface TaskState {
  readonly workspaceId: string;
  readonly runId: string;
  /** 串台修复（2026-09-25）：本任务的会话归属（空 = 未知/旧数据/CLI） */
  readonly session: string;
  readonly status: TaskStatus;
  readonly taskText: string;
  readonly rows: readonly TaskRow[];
  readonly thoughts: readonly ThoughtRow[];
  readonly unitArtifacts: readonly UnitArtifactRow[];
  readonly pendingConfirms: readonly (ConfirmDto & { readonly runId?: string })[];
  /** E2-5（A10）：待答问题组（unit_needs_answer 事件/快照——壳问题卡） */
  readonly pendingAnswers: readonly (QuestionListDto & { readonly runId?: string })[];
  readonly pendingResume: PendingResume | null;
  readonly safety: readonly SafetyRow[];
  readonly fsc: readonly FscRow[];
  readonly result: ResultDto | null;
  readonly error: string;
  /** E3-1/R5（T5）：隔离 worktree（终态 → Review/应用/丢弃） */
  readonly worktree: WorktreeState | null;
  readonly lastSeq: number;
}

export const INITIAL_TASK_STATE: TaskState = {
  workspaceId: "",
  runId: "",
  session: "",
  status: "idle",
  taskText: "",
  rows: [],
  thoughts: [],
  unitArtifacts: [],
  pendingConfirms: [],
  pendingAnswers: [],
  pendingResume: null,
  safety: [],
  fsc: [],
  result: null,
  error: "",
  worktree: null,
  lastSeq: 0,
};

export interface TaskService {
  readonly projection: Projection<TaskState>;
  state(): TaskState;
  subscribe(listener: (state: TaskState) => void): () => void;
  setWorkspace(workspaceId: string): Promise<void>;
  submit(text: string, references?: readonly string[], session?: string,
         unit?: string, override?: string,
         isolateRun?: boolean): Promise<SubmitDto>;
  /** E3-1/R5（T5）：隔离 worktree Review/Apply/Discard（Review 卡数据源） */
  reviewWorktree(runId: string): Promise<void>;
  applyWorktree(runId: string): Promise<void>;
  discardWorktree(runId: string): Promise<void>;
  confirm(items: readonly ConfirmItem[], reason?: string): Promise<void>;
  /** E2-5（A10）：答复提问（挂起单元续跑；先到为准——服务端校验） */
  answer(unitId: string, questionId: string, answer: string,
         source?: string): Promise<void>;
  rollback(runId: string, deleteArtifacts?: boolean): Promise<void>;
  cancel(): Promise<void>;
  resume(): Promise<void>;
  resumeWorkspace(): Promise<void>;
  abandonWorkspace(): Promise<void>;
  applyEvent(event: AnyEvent): void;
}

/** 快照 pending_resume → 前端投影（容忍缺字段)。 */
function readPendingResume(raw: Record<string, unknown> | null): PendingResume | null {
  if (!raw || typeof raw !== "object") return null;
  const taskText = typeof raw.task_text === "string" ? raw.task_text : "";
  const units = Array.isArray(raw.units)
    ? raw.units.map((u) => {
        const o = (u ?? {}) as Record<string, unknown>;
        return { unitId: String(o.unit_id ?? ""), domainId: String(o.domain_id ?? "") };
      })
    : [];
  return { taskText, units };
}

/** 会话隔离视图（2026-09-25 串台修复）：任务状态按会话过滤。
 *
 * 规则：
 *  - session=null（首页/未选会话）或状态无会话归属（旧数据）→ 原样返回（不回归）；
 *  - 归属其他会话 → 内容字段全清（历史/实时/结果/确认门不得跨会话显示）。
 * 保留 workspaceId/session/lastSeq；状态回落 idle（视图无活动任务）。
 */
export function taskViewForSession(state: TaskState, session: string | null): TaskState {
  if (session === null || state.session === "" || state.session === session) {
    return state;
  }
  return {
    ...INITIAL_TASK_STATE,
    workspaceId: state.workspaceId,
    session: state.session,
    lastSeq: state.lastSeq,
  };
}

function errText(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

function upsertRow(
  rows: readonly TaskRow[],
  unitId: string,
  patch: Partial<TaskRow>,
): TaskRow[] {
  const index = rows.findIndex((row) => row.unitId === unitId);
  if (index === -1) {
    return [...rows, {
      unitId,
      domainId: patch.domainId ?? "",
      status: patch.status ?? "running",
      detail: patch.detail ?? "",
      eta: patch.eta ?? "",
      failureClass: patch.failureClass ?? "",
      autoRetryKind: patch.autoRetryKind ?? "",
      autoRetryN: patch.autoRetryN ?? 0,
    }];
  }
  const existing = rows[index];
  if (!existing) return [...rows];
  const next = [...rows];
  next[index] = { ...existing, ...patch };
  return next;
}

/** 思维链条目定位（最后一个 streaming 中的同 (unitId, round)——整段合并靶点）。
 *
 * 不回看已完成的旧行：确认/续跑会重跑同一 (unit, round)——旧实现整段替换
 * 命中旧行导致文本回缩（真机采样实证）。旧行为（无 delta 流的整段）保持追加。
 */
function findStreamingThoughtIndex(
  thoughts: readonly ThoughtRow[],
  unitId: string,
  round: number,
): number {
  for (let i = thoughts.length - 1; i >= 0; i -= 1) {
    const t = thoughts[i];
    if (t !== undefined && t.unitId === unitId && t.round === round
        && t.streaming === true) return i;
  }
  return -1;
}

function reduce(state: TaskState, event: AnyEvent): TaskState {
  if (
    event.workspace_id !== "" &&
    state.workspaceId !== "" &&
    event.workspace_id !== state.workspaceId
  ) {
    return state;
  }
  if (event.seq <= state.lastSeq) return state;
  let adopted: TaskState = state;
  if (adopted.workspaceId === "" && event.workspace_id !== "") {
    adopted = { ...adopted, workspaceId: event.workspace_id };
  }
  if (adopted.runId === "" && event.run_id !== "") {
    adopted = { ...adopted, runId: event.run_id };
  }
  const base: TaskState = { ...adopted, lastSeq: event.seq };
  switch (event.type) {
    case "task_submitted": {
      const submittedSession =
        typeof event.data.session === "string" ? event.data.session : "";
      return {
        ...base,
        // 新任务接管新 run（否则第二个任务起 confirm/resume 会打到旧 run）
        runId: event.run_id !== "" ? event.run_id : base.runId,
        // 串台修复：提交即建立会话归属（事件先行/响应先行均收敛一致）
        session: submittedSession !== "" ? submittedSession : base.session,
        status: "running",
        taskText: event.data.task_text,
        rows: [],
        thoughts: [],
        unitArtifacts: [],
        // 2026-10-01 用户裁决：新任务不清除上一轮待确认——否则旧轮确认永久
        // 丢失（“新一轮开始就代表上一轮记录被清除”）。确认按 runId 回路由。
        safety: [],
        fsc: [],
        result: null,
        error: "",
      };
    }
    case "unit_started":
      return {
        ...base,
        rows: upsertRow(base.rows, event.data.unit_id, {
          domainId: event.data.domain_id,
          status: "running",
        }),
      };
    case "unit_done":
      return {
        ...base,
        rows: upsertRow(base.rows, event.data.unit_id, {
          // A10：挂起类终态不得显示成 "failed"（needs_answer → 待答复行态）
          status: event.data.status === "ok" ? "ok"
            : event.data.status === "needs_answer" ? "answer"
            : "failed",
          // S1-C：失败分类（成功终态清空——重试成功不残留）
          failureClass: event.data.status === "ok"
            ? ""
            : (event.data.failure_class ?? ""),
        }),
      };
    case "unit_auto_retry":
      return {
        ...base,
        rows: upsertRow(base.rows, event.data.unit_id, {
          autoRetryKind: event.data.kind ?? "",
          autoRetryN: event.data.kind === "fallback"
            ? (event.data.candidate ?? 0)
            : (event.data.attempt ?? 0),
        }),
      };
    case "unit_state_changed":
      return {
        ...base,
        rows: upsertRow(base.rows, event.data.unit_id, { detail: event.data.state }),
      };
    case "unit_reasoning": {
      // 思维链：追加上限 30 条（单条截断 4000 字符）——会话内保留
      // Task 3-1 + 回归修复：只合并【本次】delta 流（streaming 行）——
      // 无 delta 流的整段保持追加（不同调用/跨运行各自成行，不覆盖旧行）
      const full = event.data.text.slice(0, 4000);
      const idx = findStreamingThoughtIndex(
        base.thoughts, event.data.unit_id, event.data.round);
      if (idx >= 0) {
        return {
          ...base,
          thoughts: base.thoughts.map((t, i) =>
            i === idx ? { ...t, text: full, streaming: false } : t),
        };
      }
      const thought: ThoughtRow = {
        unitId: event.data.unit_id,
        round: event.data.round,
        text: full,
      };
      return { ...base, thoughts: [...base.thoughts, thought].slice(-30) };
    }
    case "unit_reasoning_delta": {
      // Task 3-1（思维链实时流式）：纯增量——追尾同 (unit,round) 的 streaming 行；
      // 无 streaming 行则新建（本次调用标识）；单条累计 4000 封顶；空 delta 不建行
      const delta = event.data.text;
      if (delta === "") return base;
      const idx = findStreamingThoughtIndex(
        base.thoughts, event.data.unit_id, event.data.round);
      if (idx >= 0) {
        return {
          ...base,
          thoughts: base.thoughts.map((t, i) =>
            i === idx ? { ...t, text: (t.text + delta).slice(0, 4000) } : t),
        };
      }
      const thought: ThoughtRow = {
        unitId: event.data.unit_id,
        round: event.data.round,
        text: delta.slice(0, 4000),
        streaming: true,
      };
      return { ...base, thoughts: [...base.thoughts, thought].slice(-30) };
    }
    case "artifact_written": {
      const entry: UnitArtifactRow = {
        unitId: event.data.unit_id,
        path: event.data.path,
        kind: event.data.kind,
      };
      const exists = base.unitArtifacts.some(
        (a) => a.unitId === entry.unitId && a.path === entry.path,
      );
      return exists ? base : { ...base, unitArtifacts: [...base.unitArtifacts, entry] };
    }
    case "progress":
      return {
        ...base,
        rows: upsertRow(base.rows, event.data.unit_id, {
          domainId: event.data.domain_id,
          detail: event.data.stage,
          eta: event.data.eta,
        }),
      };
    case "safety_blocked":
      return {
        ...base,
        safety: [...base.safety, {
          unitId: event.data.unit_id,
          domainId: event.data.domain_id,
          tool: event.data.tool,
          command: event.data.command,
          reason: event.data.reason,
          seq: event.seq,
        }],
      };
    case "fsc_audit":
    case "fsc_switch":
      return {
        ...base,
        fsc: [...base.fsc, {
          unitId: event.data.unit_id,
          domainId: event.data.domain_id,
          ratio: event.data.ratio,
          kind: event.type === "fsc_audit" ? "audit" : "switch",
          seq: event.seq,
        }],
      };
    case "unit_needs_confirm": {
      const already = base.pendingConfirms.some(
        (item) => item.unit_id === event.data.unit_id
          && (item.runId ?? event.run_id) === event.run_id,
      );
      const pendingConfirms = already
        ? base.pendingConfirms
        : [...base.pendingConfirms, {
            unit_id: event.data.unit_id,
            domain_id: event.data.domain_id,
            reason: event.data.reason,
            impact: (event.data.impact ?? {}) as Record<string, unknown>,
            view: (event.data.view ?? {}) as Record<string, unknown>,
            runId: event.run_id,
          }];
      return {
        ...base,
        status: "pending",
        pendingConfirms,
        rows: upsertRow(base.rows, event.data.unit_id, { status: "confirm" }),
      };
    }
    case "unit_needs_answer": {
      const already = base.pendingAnswers.some(
        (item) => item.question_id === event.data.question_id
          && (item.runId ?? event.run_id) === event.run_id,
      );
      const pendingAnswers = already
        ? base.pendingAnswers
        : [...base.pendingAnswers, {
            unit_id: event.data.unit_id,
            domain_id: event.data.domain_id,
            question_id: event.data.question_id,
            questions: (event.data.questions ?? []) as QuestionListDto["questions"],
            kind: event.data.kind ?? "",
            runId: event.run_id,
          }];
      return {
        ...base,
        status: "pending",
        pendingAnswers,
        rows: upsertRow(base.rows, event.data.unit_id, { status: "answer" }),
      };
    }
    case "question_answered":
      return {
        ...base,
        pendingAnswers: base.pendingAnswers.filter(
          (p) => !(p.unit_id === event.data.unit_id
                   && p.question_id === event.data.question_id)),
      };
    case "task_done": {
      const raw = event.data.status;
      if (raw === "pending") {
        return { ...base, status: "pending" };
      }
      const status: TaskStatus =
        raw === "done" || raw === "partial" || raw === "failed"
          || raw === "cancelled" || raw === "needs_design"
          ? raw
          : "done";
      // 2026-10-01：只清理本 run 的待确认（历史轮确认跨轮保留）——A10 待答同口径
      return { ...base, status,
               pendingConfirms: base.pendingConfirms.filter(
                 (p) => (p.runId ?? event.run_id) !== event.run_id),
               pendingAnswers: base.pendingAnswers.filter(
                 (p) => (p.runId ?? event.run_id) !== event.run_id) };
    }
    case "task_cancelled":
      return { ...base, status: "cancelled",
               pendingConfirms: base.pendingConfirms.filter(
                 (p) => (p.runId ?? event.run_id) !== event.run_id),
               pendingAnswers: base.pendingAnswers.filter(
                 (p) => (p.runId ?? event.run_id) !== event.run_id) };
    case "task_failed":
      return { ...base, status: "error", error: event.data.error };
    case "confirm_error":
      return { ...base, error: event.data.error };
    case "answer_error":
      return { ...base, error: event.data.error };
    case "resume_error":
      return { ...base, error: event.data.error };
    // E3-1/R5（T5）：worktree 生命周期（Ready → 卡片；Applied/Discarded 收束）
    case "worktree_ready": {
      const path = typeof event.data.path === "string" ? event.data.path : "";
      return {
        ...base,
        worktree: {
          runId: event.run_id !== "" ? event.run_id : base.runId,
          path, files: [], diff: "", reviewed: false,
          busy: false, notice: null,
        },
      };
    }
    case "worktree_applied": {
      if (base.worktree === null) return base;
      const n = typeof event.data.files === "number" ? event.data.files : 0;
      return {
        ...base,
        worktree: { ...base.worktree, busy: false,
                    notice: { kind: "applied", n } },
      };
    }
    case "worktree_apply_error": {
      if (base.worktree === null) return base;
      const msg = typeof event.data.error === "string" ? event.data.error : "";
      return {
        ...base,
        worktree: { ...base.worktree, busy: false,
                    notice: { kind: "apply_failed", msg } },
      };
    }
    case "worktree_discarded":
      return { ...base, worktree: null };
    default:
      return base; // 未知事件安全忽略（事件扩展缝）
  }
}

function isTerminal(event: AnyEvent): boolean {
  switch (event.type) {
    case "task_cancelled":
    case "task_failed":
      return true;
    case "task_done":
      return event.data.status !== "pending";
    default:
      return false;
  }
}

function normalizeStatus(raw: string): TaskStatus {
  switch (raw) {
    case "done":
    case "partial":
    case "failed":
    case "cancelled":
    case "pending":
    case "needs_design":
      return raw;
    default:
      return "done";
  }
}

function toUnitStatus(raw: string): UnitStatus {
  if (raw === "ok" || raw === "failed" || raw === "confirm") return raw;
  return "running";
}

export function createTaskService(deps: {
  rest: RestClient;
  commands: CommandBus;
  workspaceId: () => string | null;
}): TaskService {
  const projection = createProjection<TaskState>(INITIAL_TASK_STATE);
  let refreshing = false;

  const service: TaskService = {
    projection,
    state: () => projection.get(),
    subscribe(listener) {
      return projection.subscribe(listener);
    },
    async setWorkspace(workspaceId) {
      if (!workspaceId) {
        projection.seed(INITIAL_TASK_STATE);
        return;
      }
      const snapshot = await deps.commands.run("task.snapshot", () =>
        deps.rest.get<SnapshotDto>(`/api/v1/workspaces/${workspaceId}/snapshot`));
      const result = snapshot.result;
      const current = projection.get();
      const sameRun = current.workspaceId === workspaceId && current.runId === snapshot.run_id;
      // 合并：快照行覆盖同 id 状态；事件流多出的行保留（含详情）
      const snapshotRows: TaskRow[] = snapshot.units.map((unit) => {
        const existing = sameRun
          ? current.rows.find((row) => row.unitId === unit.unit_id)
          : undefined;
        return {
          unitId: unit.unit_id,
          domainId: unit.domain_id,
          status: toUnitStatus(unit.status),
          detail: existing?.detail ?? "",
          eta: existing?.eta ?? "",
          failureClass: existing?.failureClass ?? unit.failure_class ?? "",
          autoRetryKind: existing?.autoRetryKind ?? "",
          autoRetryN: existing?.autoRetryN ?? 0,
        };
      });
      const covered = new Set(snapshotRows.map((row) => row.unitId));
      const extraRows = sameRun
        ? current.rows.filter((row) => !covered.has(row.unitId))
        : [];
      projection.seed({
        ...INITIAL_TASK_STATE,
        workspaceId,
        runId: snapshot.run_id,
        session: snapshot.session ?? "",
        taskText: snapshot.task_text,
        status: snapshot.active_run
          ? "running"
          : result
            ? normalizeStatus(result.status)
            : sameRun && (current.status === "error" || current.status === "cancelled")
              ? current.status
              : "idle",
        rows: [...snapshotRows, ...extraRows],
        thoughts: sameRun ? current.thoughts : [],
        unitArtifacts: sameRun ? current.unitArtifacts : [],
        safety: sameRun ? current.safety : [],
        fsc: sameRun ? current.fsc : [],
        pendingConfirms: (snapshot.pending_confirms ?? []).map(
          (p) => ({ ...p, runId: snapshot.run_id })),
        pendingAnswers: (snapshot.pending_answers ?? []).map(
          (p) => ({ ...p, runId: snapshot.run_id })),
        pendingResume: readPendingResume(snapshot.pending_resume),
        result,
        // 失败原因保留：快照无结果时不得因 seed 而丢失（观测已报错未修复）
        error: result ? "" : (sameRun ? current.error : ""),
        // E3-1/R5（T5）：worktree 卡随快照保留（同 run）——终态快照刷新不得丢卡
        worktree: sameRun ? current.worktree : null,
        lastSeq: snapshot.last_seq,
      }, snapshot.last_seq);
    },
    async submit(text, references = [], session = "", unit = "", override = "",
                 isolateRun = false) {
      const workspaceId = deps.workspaceId();
      if (!workspaceId) throw new Error("未选择工作区");
      // 参考文件契约（T5.3）：非空才携带 references 键（空数组不输出——字节稳定）
      const body: Record<string, unknown> = references.length > 0
        ? { text, references: [...references] }
        : { text };
      // 修复①（2026-09-20）：会话名——空串由服务端自动新建（首句对话建立会话）
      if (session !== "") body.session = session;
      // 碎片会话后半程（2026-09-22）：碎片内提交携带绑定身份（空串不输出——字节稳定）
      if (unit !== "") body.unit = unit;
      // 二期批 1：显式闸覆盖（仅 "no_map"——无地图执行；空串不输出）
      if (override !== "") body.override = override;
      // E3-1/R5（T5）：显式隔离档（worktree）——默认关（不输出键，字节稳定）
      if (isolateRun) body.isolate_run = true;
      const out = await deps.commands.run("task.submit", () =>
        deps.rest.post<SubmitDto>(`/api/v1/workspaces/${workspaceId}/tasks`, body));
      // 串台修复：提交响应即建立会话归属（事件先到也不会丢失——同一值收敛）
      if ((out.session ?? "") !== "") {
        const current = projection.get();
        if (current.session !== out.session) {
          projection.seed({ ...current, session: out.session }, current.lastSeq);
        }
      }
      return out;
    },
    async rollback(runId, deleteArtifacts = false) {
      const workspaceId = deps.workspaceId();
      if (!workspaceId) throw new Error("未选择工作区");
      await deps.commands.run("task.rollback", () =>
        deps.rest.post(
          `/api/v1/workspaces/${workspaceId}/tasks/${runId}/rollback`,
          { delete_artifacts: deleteArtifacts },
        ));
    },
    async confirm(items, reason = "") {
      const state = projection.get();
      if (!state.workspaceId) throw new Error("无活动工作区");
      // 2026-10-01：确认项按所属 run 分组路由（跨轮保留的旧确认回打原 run）
      const groups = new Map<string, ConfirmItem[]>();
      for (const item of items) {
        const saved = state.pendingConfirms.find((p) => p.unit_id === item[0]);
        const rid = saved?.runId ?? state.runId;
        if (!rid) throw new Error("无活动任务");
        const bucket = groups.get(rid) ?? [];
        bucket.push(item);
        groups.set(rid, bucket);
      }
      for (const [rid, group] of groups) {
        // 服务端契约：items 为 [unit_id, approve] 对列表（manager.confirm 解包 pairs）
        await deps.commands.run("task.confirm", () =>
          deps.rest.post(
            `/api/v1/workspaces/${state.workspaceId}/tasks/${rid}/confirm`,
            { items: group.map(([unitId, approve]) => [unitId, approve]), reason },
          ));
      }
      // POST 200 = manager 已保证这些单元移出服务端待确认（同步校验 + finally 清除）——
      // 本地即时收敛（事件流此刻尚未到达）；失败在上一行抛出、投影不动
      const current = projection.get();
      const done = new Set(items.map(([unitId]) => unitId));
      projection.seed({
        ...current,
        pendingConfirms: current.pendingConfirms.filter((p) => !done.has(p.unit_id)),
      }, current.lastSeq);
    },
    async answer(unitId, questionId, answer, source = "text") {
      const state = projection.get();
      if (!state.workspaceId) throw new Error("无活动工作区");
      // 跨轮保留的待答问题按所属 run 回路由（同 confirm 口径）
      const saved = state.pendingAnswers.find(
        (p) => p.unit_id === unitId && p.question_id === questionId);
      const rid = saved?.runId ?? state.runId;
      if (!rid) throw new Error("无活动任务");
      await deps.commands.run("task.answer", () =>
        deps.rest.post(
          `/api/v1/workspaces/${state.workspaceId}/tasks/${rid}/answer`,
          { unit_id: unitId, question_id: questionId, answer, source },
        ));
      // POST 200 = manager 已同步校验并移出待答——本地即时收敛（事件流重到达无害）
      const current = projection.get();
      projection.seed({
        ...current,
        pendingAnswers: current.pendingAnswers.filter(
          (p) => !(p.unit_id === unitId && p.question_id === questionId)),
      }, current.lastSeq);
    },
    async cancel() {
      const state = projection.get();
      if (!state.workspaceId || !state.runId) throw new Error("无活动任务");
      await deps.commands.run("task.cancel", () =>
        deps.rest.post(
          `/api/v1/workspaces/${state.workspaceId}/tasks/${state.runId}/cancel`,
          {},
        ));
    },
    async resume() {
      const state = projection.get();
      if (!state.workspaceId || !state.runId) throw new Error("无活动任务");
      await deps.commands.run("task.resume", () =>
        deps.rest.post(
          `/api/v1/workspaces/${state.workspaceId}/tasks/${state.runId}/resume`,
          {},
        ));
    },
    async resumeWorkspace() {
      const workspaceId = deps.workspaceId();
      if (!workspaceId) throw new Error("未选择工作区");
      await deps.commands.run("task.resumeWorkspace", () =>
        deps.rest.post(`/api/v1/workspaces/${workspaceId}/resume`, {}));
    },
    async abandonWorkspace() {
      const workspaceId = deps.workspaceId();
      if (!workspaceId) throw new Error("未选择工作区");
      await deps.commands.run("task.abandonWorkspace", () =>
        deps.rest.post(`/api/v1/workspaces/${workspaceId}/abandon`, {}));
    },
    async reviewWorktree(runId) {
      const workspaceId = deps.workspaceId();
      if (!workspaceId) return;
      const current = projection.get();
      if (!current.worktree || current.worktree.runId !== runId
          || current.worktree.reviewed || current.worktree.busy) return;
      projection.seed({ ...current,
        worktree: { ...current.worktree, busy: true } }, current.lastSeq);
      try {
        const out = await deps.rest.get<WorktreeReviewDto>(
          `/api/v1/workspaces/${workspaceId}/tasks/${runId}/worktree`);
        const now = projection.get();
        if (!now.worktree || now.worktree.runId !== runId) return;
        projection.seed({ ...now, worktree: { ...now.worktree,
          files: out.files ?? [], diff: out.diff ?? "",
          reviewed: true, busy: false, notice: null } }, now.lastSeq);
      } catch (err) {
        const now = projection.get();
        if (!now.worktree || now.worktree.runId !== runId) return;
        projection.seed({ ...now, worktree: { ...now.worktree, reviewed: true,
          busy: false,
          notice: { kind: "review_failed", msg: errText(err) } } }, now.lastSeq);
      }
    },
    async applyWorktree(runId) {
      const workspaceId = deps.workspaceId();
      if (!workspaceId) return;
      const current = projection.get();
      if (current.worktree) {
        projection.seed({ ...current, worktree: { ...current.worktree,
          busy: true, notice: null } }, current.lastSeq);
      }
      try {
        const out = await deps.commands.run("task.worktree.apply", () =>
          deps.rest.post<WorktreeActionResultDto>(
            `/api/v1/workspaces/${workspaceId}/tasks/${runId}/worktree/apply`,
            {}));
        const now = projection.get();
        if (now.worktree) {
          projection.seed({ ...now, worktree: { ...now.worktree, busy: false,
            notice: { kind: "applied", n: out.files ?? 0 } } }, now.lastSeq);
        }
      } catch (err) {
        // 失败经命令总线广播；卡片提示同步（不重复抛出——防未处理拒绝）
        const now = projection.get();
        if (now.worktree) {
          projection.seed({ ...now, worktree: { ...now.worktree, busy: false,
            notice: { kind: "apply_failed", msg: errText(err) } } }, now.lastSeq);
        }
      }
    },
    async discardWorktree(runId) {
      const workspaceId = deps.workspaceId();
      if (!workspaceId) return;
      const current = projection.get();
      if (current.worktree) {
        projection.seed({ ...current, worktree: { ...current.worktree,
          busy: true, notice: null } }, current.lastSeq);
      }
      try {
        await deps.commands.run("task.worktree.discard", () =>
          deps.rest.post(
            `/api/v1/workspaces/${workspaceId}/tasks/${runId}/worktree/discard`,
            {}));
        const now = projection.get();
        projection.seed({ ...now, worktree: null }, now.lastSeq);
      } catch (err) {
        const now = projection.get();
        if (now.worktree) {
          projection.seed({ ...now, worktree: { ...now.worktree, busy: false,
            notice: { kind: "discard_failed", msg: errText(err) } } }, now.lastSeq);
        }
      }
    },
    applyEvent(event) {
      const applied = projection.apply(event.seq, (current) => reduce(current, event));
      if (!applied) return;
      if (isTerminal(event)) {
        const workspaceId = projection.get().workspaceId;
        if (!workspaceId || refreshing) return;
        refreshing = true;
        void service.setWorkspace(workspaceId)
          .catch(() => {
            // 失败已在命令总线广播（onFailure 全局面呈现）——此处仅防未处理拒绝
          })
          .finally(() => { refreshing = false; });
      }
    },
  };
  return service;
}
