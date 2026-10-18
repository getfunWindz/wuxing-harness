/** 视图模型（纯函数——可单测；DOM 细节由 E2E 覆盖）。 */
import type {
  BrainStatsDto,
  ContextPreviewDto,
  ContextPreviewListDto,
  ContextSegmentDto,
  McpStatusDto,
  SearchResultDto,
  NotificationDto,
  RecycleEntryDto,
  ReportEntryDto,
  ResultDto,
  SessionDto,
  SkillDto,
  TaskHistoryRowDto,
  WorkspaceDto,
} from "../protocol/generated.ts";
import { getLang, t } from "./i18n.ts";
import type {
  TaskState,
  TaskStatus,
  TaskRow,
  ThoughtRow,
  UnitArtifactRow,
} from "../runtime/services/tasks.ts";
import type { ConfirmItem } from "../runtime/services/tasks.ts";

export function shouldSubmit(input: {
  key: string;
  shiftKey: boolean;
  isComposing: boolean;
}): boolean {
  return input.key === "Enter" && !input.shiftKey && !input.isComposing;
}

/** 单元集合 → 确认项对（批量批准/驳回用；批准无需理由）。 */
export function buildConfirmItems(unitIds: readonly string[], approve: boolean): ConfirmItem[] {
  return unitIds.map((unitId) => [unitId, approve] as const);
}

/** 驳回理由必填（旧壳口径）——trim 后为空即缺失。 */
export function rejectReasonMissing(reason: string): boolean {
  return reason.trim() === "";
}

export interface WorkspaceChip {
  readonly id: string;
  readonly label: string;
  readonly active: boolean;
  readonly status: string;
}

export function deriveWorkspaceChips(
  list: readonly WorkspaceDto[],
  activeId: string | null,
): WorkspaceChip[] {
  return list.map((ws) => ({
    id: ws.id,
    label: ws.name,
    active: ws.id === activeId,
    status: ws.status,
  }));
}

export function statusLabel(status: TaskStatus): string {
  return t(`status.${status}`);
}

/** S1-C：失败分类 → i18n 键（未知/空回落空串）。 */
export function failureLabelKey(failureClass: string): string {
  if (failureClass === "provider" || failureClass === "budget"
      || failureClass === "stalled") {
    return `failure.${failureClass}`;
  }
  return "";
}

/** S1-C：自动恢复类型 → i18n 键（retry=同候选重试 / fallback=降级换候选）。 */
export function autoRetryKey(kind: string): string {
  if (kind === "retry") return "failure.autoRetry";
  if (kind === "fallback") return "failure.fallback";
  return "";
}

export function summarizeTask(state: TaskState): string {
  const parts: string[] = [statusLabel(state.status)];
  if (state.rows.length > 0) parts.push(`${state.rows.length} 单元`);
  if (state.pendingConfirms.length > 0) parts.push(`待确认 ${state.pendingConfirms.length}`);
  if (state.error !== "") parts.push(state.error);
  return parts.join(" · ");
}

export interface RailRow {
  readonly id: string;
  readonly label: string;
  readonly active: boolean;
  readonly statusLabel: string;
}

/** 左栏行派生（P2-S9 纯函数）：标签/激活/状态文案。 */
export function deriveRailRows(
  list: readonly WorkspaceDto[],
  activeId: string | null,
): RailRow[] {
  return list.map((ws) => ({
    id: ws.id,
    label: ws.name,
    active: ws.id === activeId,
    statusLabel: statusLabel(ws.status as TaskStatus),
  }));
}

/** dock·产物行（P2-S10 纯函数）：来自任务结果快照。
 *  A6（W1）：携带 mtime（历史载荷缺失 → 0，兼容旧快照）。 */
export interface ArtifactRow { readonly path: string; readonly kind: string; readonly mtime: number }

export function deriveArtifactRows(result: ResultDto | null): ArtifactRow[] {
  return (result?.artifacts ?? [])
    .filter((a) => !isInternalArtifact(a.path))
    .map((a) => ({
      path: a.path, kind: a.kind,
      mtime: typeof a.mtime === "number" && Number.isFinite(a.mtime) ? a.mtime : 0,
    }));
}

/** A6（W1-4）：预览大小上限——v1 = 512 KiB（字节口径）。 */
export const ARTIFACT_PREVIEW_BYTES = 512 * 1024;

export type ArtifactPreviewMode = "markdown" | "text" | "binary";

const ARTIFACT_MARKDOWN_EXT = new Set(["md", "markdown"]);
// HTML 等仅按纯文本渲染（不经任何 HTML 解析）——防注入是路由/渲染层职责
const ARTIFACT_TEXT_EXT = new Set([
  "txt", "log", "csv", "tsv", "json", "jsonc", "jsonl", "yaml", "yml",
  "toml", "ini", "cfg", "conf", "py", "ts", "tsx", "js", "mjs", "cjs",
  "css", "scss", "html", "htm", "xml", "svg", "sh", "bash", "ps1",
  "bat", "cmd", "c", "h", "cpp", "hpp", "rs", "go", "java", "kt",
  "rb", "php", "sql", "env", "diff", "patch",
]);

/** A6（W1-1）：预览类型分流——扩展名决定；未知/无扩展 = binary 兜底（仅元信息）。 */
export function artifactPreviewMode(path: string): ArtifactPreviewMode {
  const name = String(path || "").split(/[\\/]/).pop() ?? "";
  const match = /\.([A-Za-z0-9]+)$/.exec(name);
  const ext = match ? (match[1] ?? "").toLowerCase() : "";
  if (ARTIFACT_MARKDOWN_EXT.has(ext)) return "markdown";
  if (ARTIFACT_TEXT_EXT.has(ext)) return "text";
  return "binary";
}

/** A6（W1-4）：按 UTF-8 字节截断预览文本（不切碎代理对，不产生 U+FFFD）。 */
export function truncateArtifactText(
  text: string,
  byteLimit: number = ARTIFACT_PREVIEW_BYTES,
): { readonly text: string; readonly truncated: boolean } {
  const src = String(text ?? "");
  if (byteLimit <= 0) return { text: "", truncated: src.length > 0 };
  const enc = new TextEncoder();
  // UTF-8 字节数 ≥ UTF-16 码元数（每码元至少 1 字节）——码元未超限才需精确量字节
  if (src.length <= byteLimit && enc.encode(src).length <= byteLimit) {
    return { text: src, truncated: false };
  }
  let lo = 0;
  let hi = src.length;
  while (lo < hi) {
    const mid = Math.ceil((lo + hi) / 2);
    if (enc.encode(src.slice(0, mid)).length <= byteLimit) lo = mid;
    else hi = mid - 1;
  }
  const last = lo > 0 ? src.charCodeAt(lo - 1) : 0;
  if (last >= 0xd800 && last <= 0xdbff) lo -= 1; // 高半代理不得单独截出
  return { text: src.slice(0, lo), truncated: true };
}

/** A6（W1）：产物预览面板状态（dock 呈现；text 已按上限截断）。
 *  binary/失败时 text=""；error/notice 均为面板内可见文案（""=无）。 */
export interface ArtifactPreviewView {
  readonly path: string;
  readonly mode: ArtifactPreviewMode;
  readonly text: string;
  readonly truncated: boolean;
  readonly error: string;
  readonly notice: string;
}

/** A6（W1）：产物行/预览元信息（kind · 本地时间；空则省略对应段）。 */
export function artifactMeta(row: { readonly kind: string; readonly mtime: number }): string {
  const parts: string[] = [];
  if (row.kind.trim() !== "") parts.push(row.kind.trim());
  if (row.mtime > 0) parts.push(fmtStamp(row.mtime));
  return parts.join(" · ");
}

/** 2026-10-01 用户裁决：契约报告收纳于 .wuxing/ 内部——不进用户产物视图。 */
export function isInternalArtifact(path: string): boolean {
  return String(path || "").replace(/\\/g, "/").toLowerCase().startsWith(".wuxing/");
}

/** M7 B3（ST-13）：流卡片上限裁剪——保留最新 N 个键（旧壳 MAX_CARDS=400 口径）。 */
export function trimKeys(keys: readonly string[], max: number): string[] {
  if (max <= 0 || keys.length <= max) return [...keys];
  return keys.slice(keys.length - max);
}

/** M7 B4（#3）：参考文件是否在工作区外（大小写不敏感 + 分隔符归一；边界不误判）。 */
export function isOutsideWorkspace(refPath: string, wsPath: string): boolean {
  const norm = (p: string): string => p.replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
  const ref = norm(refPath);
  const ws = norm(wsPath);
  if (ref === "" || ws === "") return false;
  if (ref === ws) return false;
  return !ref.startsWith(`${ws}/`);
}

/** 会话聊天消息（修复②，2026-09-20）：session rows → 双侧对话消息。 */
export interface ChatMessage {
  readonly kind: "user" | "assistant";
  readonly text: string;
  readonly artifacts: readonly string[];
  readonly round: number;
  /** 轮次行时间戳（epoch 秒；role/content 旧行可能缺省）——气泡时间锚点 */
  readonly ts?: number;
}

/** 会话行 → 聊天消息（兼容三种形状：round 轮次 / role-content / messages[]；破损行跳过）。 */
export function deriveChatMessages(rows: readonly Record<string, unknown>[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const row of rows) {
    const round = typeof row.round === "number" ? row.round : 0;
    const ts = typeof row.ts === "number" && row.ts > 0 ? row.ts : undefined;
    if (typeof row.user_text === "string" && row.user_text !== "") {
      out.push({ kind: "user", text: row.user_text, artifacts: [], round,
                 ...(ts !== undefined ? { ts } : {}) });
      const arts = Array.isArray(row.artifacts) ? row.artifacts.map(String) : [];
      const summary = typeof row.summary === "string" ? row.summary : "";
      // Task 4-3（流式专项）：模型总体回复优先（reply）；无/空白则回退机械 summary
      const reply = typeof row.reply === "string" && row.reply.trim() !== ""
        ? row.reply
        : summary;
      if (reply !== "" || arts.length > 0) {
        out.push({ kind: "assistant", text: reply, artifacts: arts, round,
                   ...(ts !== undefined ? { ts } : {}) });
      }
      continue;
    }
    const role = typeof row.role === "string" ? row.role : "";
    const content = typeof row.content === "string" ? row.content : "";
    if ((role === "user" || role === "assistant") && content !== "") {
      out.push({ kind: role, text: content, artifacts: [], round });
      continue;
    }
    if (Array.isArray(row.messages)) {
      for (const raw of row.messages as readonly Record<string, unknown>[]) {
        const m = (raw ?? {}) as Record<string, unknown>;
        const r = typeof m.role === "string" ? m.role : "";
        const c = typeof m.content === "string" ? m.content : "";
        if ((r === "user" || r === "assistant") && c !== "") {
          out.push({ kind: r, text: c, artifacts: [], round });
        }
      }
    }
  }
  return out;
}

export interface SkillRow {
  readonly name: string;
  readonly description: string;
  readonly level: string;
  readonly enabled: boolean;
}

export function deriveSkillRows(list: readonly SkillDto[]): SkillRow[] {
  return list.map((s) => ({ name: s.name, description: s.description, level: s.level,
                            enabled: s.enabled !== false }));
}

export interface McpToolRow { readonly name: string; readonly permissions: string }

export interface McpRow {
  readonly name: string;
  readonly command: string;
  readonly tools: readonly McpToolRow[];
  readonly detail: string;
}

function permText(permissions: Record<string, unknown>): string {
  const on = Object.entries(permissions)
    .filter(([, value]) => value === true)
    .map(([key]) => key);
  return on.length === 0 ? "—" : on.join(" ");
}

/** dock·MCP 行（P2-M5 管理面）：命令 + 工具权限 + 调用统计。 */
export function deriveMcpRows(status: McpStatusDto | null): McpRow[] {
  return (status?.servers ?? []).map((s) => ({
    name: s.name,
    command: [s.command, ...(s.args ?? [])].filter((part) => part !== "").join(" "),
    tools: s.tools.map((tool) => ({
      name: tool.name,
      permissions: permText(tool.permissions ?? {}),
    })),
    detail: t("dock.mcp.detail", {
      tools: String(s.tools.length), calls: String(s.stats.calls),
    }),
  }));
}

/* ---------- 顶栏属性（旧壳 10 属性口径 + 可选展示） ---------- */

export const TOPBAR_ATTR_IDS = [
  "conc", "ws", "cache", "ctx", "pending",
  "reqHit", "tokensIn", "tokensOut", "calls", "fsc",
] as const;
export type TopbarAttrId = (typeof TOPBAR_ATTR_IDS)[number];
export const TOPBAR_DEFAULT_ATTRS: readonly TopbarAttrId[] = ["conc", "ws", "cache", "ctx"];

const TOPBAR_ATTR_LABEL_KEY: Record<TopbarAttrId, string> = {
  conc: "topbar.attr.conc", ws: "topbar.attr.ws", cache: "topbar.attr.cache",
  ctx: "topbar.attr.ctx", pending: "topbar.attr.pending", reqHit: "topbar.attr.reqHit",
  tokensIn: "topbar.attr.tokensIn", tokensOut: "topbar.attr.tokensOut",
  calls: "topbar.attr.calls", fsc: "topbar.attr.fsc",
};

export interface TopbarAttr {
  readonly key: TopbarAttrId;
  readonly label: string;
  readonly value: string;
  /** ctx 档位（双模式批 2；golden/normal/managed——仅展示用） */
  readonly band?: string;
}

/** 可见属性归一（存储值 → 声明顺序；非法/缺失回默认；窄屏仅前 2——旧壳口径）。 */
export function normalizeTopbarVisible(stored: unknown, narrow: boolean): TopbarAttrId[] {
  let ids: TopbarAttrId[] | null = null;
  if (Array.isArray(stored)) {
    const set = new Set(stored.filter((x): x is TopbarAttrId =>
      typeof x === "string" && (TOPBAR_ATTR_IDS as readonly string[]).includes(x)));
    ids = TOPBAR_ATTR_IDS.filter((id) => set.has(id));
  }
  if (ids === null) ids = [...TOPBAR_DEFAULT_ATTRS];
  return narrow ? ids.slice(0, 2) : ids;
}

/** 顶栏属性值（旧壳 attrValue 口径）：缺失留「—」不造假；ctx 引擎未暴露 → 恒「—」。 */
export function deriveTopbarAttrs(
  workspaces: readonly WorkspaceDto[],
  state: TaskState,
  metrics: Record<string, unknown> | null | undefined,
  contextPercent: number | null = null,
  contextBand: string | null = null,
): TopbarAttr[] {
  const m = asObj(metrics ?? {});
  const u = asObj(m.usage);
  const reply = asObj(asObj(m.cache).reply);
  const reqs = asZero(reply.hits) + asZero(reply.misses);
  const num = (v: unknown): string => (asNum(v) === null ? "—" : String(v));
  const pct = (v: number | null): string => (v === null ? "—" : `${(v * 100).toFixed(0)}%`);
  const runningWs = workspaces.filter((ws) => ws.status === "running").length;
  // CH 口径（用户裁决 2026-10-02）：缓存命中率 = 最近一次请求命中率（无数据不拿累计冒充）
  const latestUsage = asObj(m.usage_latest);
  const chRatio = asZero(latestUsage.input) > 0
    ? asZero(latestUsage.cache_read) / asZero(latestUsage.input) : null;
  const fsc = m.fsc === null || m.fsc === undefined ? null : asObj(m.fsc);
  const valueOf = (id: TopbarAttrId): string => {
    switch (id) {
      case "conc": return String(runningWs);
      case "ws": return String(workspaces.length);
      case "cache": return pct(chRatio);
      case "ctx": return formatContextPercent(contextPercent);
      case "pending": return state.pendingConfirms.length > 0 ? String(state.pendingConfirms.length) : "—";
      case "reqHit": return reqs > 0 ? pct(asZero(reply.hits) / reqs) : "—";
      case "tokensIn": return num(u.input);
      case "tokensOut": return num(u.output);
      case "calls": return num(m.llm_calls);
      case "fsc": return fsc === null ? "—" : num(fsc.reused);
    }
  };
  return TOPBAR_ATTR_IDS.map((id) => ({
    key: id, label: t(TOPBAR_ATTR_LABEL_KEY[id]), value: valueOf(id),
    ...(id === "ctx" && contextBand ? { band: contextBand } : {}),
  }));
}

/* ---------- 上下文投影（B 期 · 2026-09-22）：顶栏极简 `~NN%` + 拆段/轮次派生 ---------- */

/** 顶栏/面板百分比（诚实标记 `~`；无数据 → 「—」——不造假）。 */
export function formatContextPercent(percent: number | null): string {
  if (percent === null || !Number.isFinite(percent)) return "—";
  return `~${Math.round(percent * 100)}%`;
}

/** 档位视图（双模式批 2：黄金/正常/严管；未知/空 → null——不显示不造假）。 */
export interface ContextBandView {
  readonly label: string;
  readonly hint: string;
  readonly cls: string;
}

export function contextBandView(band: string): ContextBandView | null {
  if (band === "golden") {
    return { label: t("ctx.band.golden"), hint: t("ctx.hint.golden"),
             cls: "golden" };
  }
  if (band === "normal") {
    return { label: t("ctx.band.normal"), hint: "", cls: "normal" };
  }
  if (band === "managed") {
    return { label: t("ctx.band.managed"), hint: t("ctx.hint.managed"),
             cls: "managed" };
  }
  return null;
}

/** 路线进度（批 4）：`- [x]`/`- [ ]` 计数（无标记 → null——不造假）。 */
export function routeProgress(
  route: readonly string[],
): { done: number; total: number } | null {
  let done = 0;
  let total = 0;
  for (const line of route) {
    if (/^-\s*\[[xX ]\]/.test(line.trim())) {
      total += 1;
      if (/^-\s*\[[xX]\]/.test(line.trim())) done += 1;
    }
  }
  return total > 0 ? { done, total } : null;
}

export interface ContextBarSegment {
  readonly key: "fixed" | "history" | "digest" | "fsc";
  readonly est_tokens: number;
  readonly percent: number;
}

/** 分段桶（system/skills → fixed；fsc_prefix → fsc）——DSH 形态拆段条数据。 */
const CONTEXT_BUCKETS: Record<string, ContextBarSegment["key"]> = {
  system: "fixed", skills: "fixed", history: "history",
  digest: "digest", fsc_prefix: "fsc",
};

/** 拆段占比（相对投影总量）；全 0 → 空（不画空条）。 */
export function contextBarSegments(
  segments: readonly ContextSegmentDto[],
): ContextBarSegment[] {
  const totals = new Map<ContextBarSegment["key"], number>();
  for (const s of segments) {
    const key = CONTEXT_BUCKETS[s.key];
    if (key === undefined || s.est_tokens <= 0) continue;
    totals.set(key, (totals.get(key) ?? 0) + s.est_tokens);
  }
  const total = [...totals.values()].reduce((a, b) => a + b, 0);
  if (total <= 0) return [];
  const order: ContextBarSegment["key"][] = ["fixed", "history", "digest", "fsc"];
  return order
    .filter((k) => (totals.get(k) ?? 0) > 0)
    .map((k) => ({
      key: k,
      est_tokens: totals.get(k) ?? 0,
      percent: ((totals.get(k) ?? 0) / total) * 100,
    }));
}

export interface ContextRoundRow {
  readonly round: number;
  readonly summary: string;
  readonly chars: number;
  readonly est_tokens: number;
  readonly status: "context" | "omitted" | "replaced" | "isolated" | "compacted";
}

/** 轮次明细行（投影状态：在上下文/已省略/已替换/已隔离（碎片轮次）/已压缩）。 */
export function deriveContextRounds(preview: ContextPreviewDto | null): ContextRoundRow[] {
  if (preview === null) return [];
  return (preview.rounds ?? []).map((r) => ({
    round: r.round,
    summary: r.summary,
    chars: r.chars,
    est_tokens: r.est_tokens,
    status: r.unit_marked
      ? "isolated"
      : r.compacted
        ? "compacted"
        : r.omitted ? "omitted" : r.replaced ? "replaced" : "context",
  }));
}

export interface CtxEditActions {
  readonly omit: boolean;
  readonly replace: boolean;
  readonly restore: boolean;
}

/** G3/G7：投影编辑动作可见性（isolated/compacted 无动作；已编辑轮 → 显示恢复）。 */
export function ctxEditActions(status: string): CtxEditActions {
  if (status === "isolated" || status === "compacted") {
    return { omit: false, replace: false, restore: false };
  }
  return {
    omit: true,
    replace: true,
    restore: status === "omitted" || status === "replaced",
  };
}

export interface ContextRowView {
  readonly name: string;
  readonly percent: number | null;
  readonly available: boolean;
}

/** dock 会话行百分比（不可用 → null——「—」不造假）。 */
export function deriveContextRows(list: ContextPreviewListDto | null): ContextRowView[] {
  if (list === null) return [];
  return (list.items ?? []).map((i) => ({
    name: i.session,
    percent: i.available ? i.percent : null,
    available: i.available,
  }));
}

/** token 紧凑格式（k/M；非法值 → 「—」）。 */
export function formatTokenCount(n: number): string {
  if (!Number.isFinite(n) || n < 0) return "—";
  if (n < 1000) return String(Math.round(n));
  if (n < 1_000_000) {
    const v = n / 1000;
    return `${v >= 100 ? Math.round(v) : Math.round(v * 10) / 10}k`;
  }
  const v = n / 1_000_000;
  return `${Math.round(v * 10) / 10}M`;
}

/* ---------- 悬浮任务卡派生（B2）：域/碎片/FSC/ETA/并发 ---------- */

const DOMAIN_LABEL_KEYS: Record<string, string> = {
  plan: "domain.plan", execute: "domain.execute", verify: "domain.verify", user: "domain.user",
};

/** 域 id → 中文标签（未知域回 id 本身，不造假）。 */
export function domainLabel(domainId: string): string {
  if (domainId === "") return "—";
  const key = DOMAIN_LABEL_KEYS[domainId];
  if (key === undefined) return domainId;
  return t(key);
}

/** 碎片域分布（首见顺序）：如「执行 2 / 验证 1」；空 → 「—」。 */
export function deriveFragmentDomains(rows: readonly TaskRow[]): string {
  const counts = new Map<string, number>();
  for (const row of rows) {
    if (row.domainId === "") continue;
    counts.set(row.domainId, (counts.get(row.domainId) ?? 0) + 1);
  }
  if (counts.size === 0) return "—";
  return [...counts.entries()].map(([id, n]) => `${domainLabel(id)} ${n}`).join(" / ");
}

/** 预计执行时间（ProgressReport.eta）：取最后一条；无 → 空串（调用方显示「就绪」）。 */
export function deriveEta(state: TaskState): string {
  for (let i = state.rows.length - 1; i >= 0; i -= 1) {
    const eta = state.rows[i]?.eta ?? "";
    if (eta !== "") return eta;
  }
  return "";
}

/** 当前会话并发：运行单元数 / 上限（上限未知时只显示运行数）。 */
export function deriveConcurrency(state: TaskState, maxParallel: number | null): string {
  const running = state.rows.filter((row) => row.status === "running").length;
  return maxParallel === null ? String(running) : `${running} / ${maxParallel}`;
}

/** 悬浮任务卡可见性（U6）：无任务活动（空工作区/纯空闲）不显示——去视觉噪声。 */
export function deriveFloatCardVisible(enabled: boolean, state: TaskState): boolean {
  if (!enabled || state.workspaceId === "") return false;
  return state.taskText !== "" || state.runId !== "" || state.status !== "idle"
    || state.result !== null || state.rows.length > 0;
}

/** 右栏上下文目标（U11）：无活动会话时回退最近会话——调用方须显式标注来源。 */
export function deriveContextTarget(activeSession: string | null,
                                    sessionNames: readonly string[]):
                                    { target: string | null; fallback: boolean } {
  if (activeSession !== null) return { target: activeSession, fallback: false };
  const first = sessionNames[0] ?? null;
  return { target: first, fallback: first !== null };
}

/** FSC 情况：任务指标优先（复用/覆盖），运行中退回事件行计数；无 → 「—」。 */
export function deriveFscSummary(
  state: TaskState,
  metrics: Record<string, unknown> | null | undefined,
): string {
  const m = asObj(metrics ?? {});
  const fsc = m.fsc === null || m.fsc === undefined ? null : asObj(m.fsc);
  if (fsc !== null) {
    const parts: string[] = [];
    const reused = asNum(fsc.reused);
    const coverage = asNum(fsc.coverage);
    if (reused !== null) parts.push(`${t("usage.fscReused")} ${reused}`);
    if (coverage !== null) parts.push(`${t("usage.fscCoverage")} ${(coverage * 100).toFixed(0)}%`);
    if (parts.length > 0) return parts.join(" · ");
  }
  if (state.fsc.length > 0) {
    const audited = state.fsc.filter((row) => row.kind === "audit").length;
    const switched = state.fsc.filter((row) => row.kind === "switch").length;
    return `${t("usage.fscAudit")} ${audited} · ${t("usage.fscSwitch")} ${switched}`;
  }
  return "—";
}

export interface RecycleRow {
  readonly id: string;
  readonly name: string;
  readonly detail: string;
}

/** dock·回收站行（P2-M1 纯函数）：名称 + 类型/状态文案。 */
export function deriveRecycleRows(entries: readonly RecycleEntryDto[]): RecycleRow[] {
  return entries.map((e) => ({ id: e.id, name: e.name, detail: `${e.kind} · ${e.state}` }));
}

export interface SessionRow {
  /** 文件名（操作键：重命名/导出/归档） */
  readonly name: string;
  /** 展示名（LLM 标题；空 → 回退文件名） */
  readonly title: string;
  readonly detail: string;
  /** G1：分支血缘（非空 → 渲染「分支自 …」徽标） */
  readonly branchedFrom: { readonly source: string; readonly fromRound: number } | null;
}

/** dock/左栏·会话行（P2-M2 纯函数；标题空缺时回退文件名）。 */
export function deriveSessionRows(sessions: readonly SessionDto[]): SessionRow[] {
  return sessions.map((s) => {
    const rawTitle = (s.title ?? "").trim();
    const bf = s.branched_from;
    const source = typeof bf?.source === "string" ? bf.source : "";
    const fromRound = typeof bf?.from_round === "number" ? bf.from_round : 0;
    return {
      name: s.name,
      title: rawTitle === "" ? s.name.replace(/\.jsonl$/, "") : rawTitle,
      detail: `${Math.max(1, Math.round(s.size / 1024))} KB · ${new Date(s.mtime * 1000).toLocaleString()}`,
      branchedFrom: source !== "" && fromRound > 0
        ? { source: source.replace(/\.jsonl$/, ""), fromRound }
        : null,
    };
  });
}

/* ---------- P2-M4 观测视图派生（任务/使用/溯源/日志/通知/智脑/报告） ---------- */

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function asNum(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function asZero(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0;
}

function asObj(value: unknown): Record<string, unknown> {
  return typeof value === "object" && value !== null
    ? value as Record<string, unknown>
    : {};
}

function fmtClock(ts: number | null): string {
  if (ts === null) return "";
  return new Date(ts * 1000).toLocaleTimeString(
    getLang() === "zh" ? "zh-CN" : "en-US", { hour12: false });
}

function fmtStamp(ts: number | null): string {
  if (ts === null) return "";
  return new Date(ts * 1000).toLocaleString(
    getLang() === "zh" ? "zh-CN" : "en-US", { hour12: false });
}

function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/* ---- 任务 ---- */

export interface TaskViewRow {
  readonly runId: string;
  readonly text: string;
  readonly dot: string;
  readonly status: string;
  readonly meta: string;
  readonly error: string;
}

const TASK_STATUS_META: Record<string, { dot: string; key: string }> = {
  done: { dot: "ok", key: "status.done" },
  partial: { dot: "warn", key: "status.partial" },
  failed: { dot: "bad", key: "status.failed" },
  cancelled: { dot: "", key: "status.cancelled" },
  error: { dot: "bad", key: "status.error" },
  pending: { dot: "warn", key: "status.pending" },
  running: { dot: "run", key: "status.running" },
  rolled_back: { dot: "", key: "status.rolledBack" },
};

/** dock·任务行（P2-M4）：状态点/文案 + 时间 + 产物数。 */
export function deriveTaskRows(history: readonly TaskHistoryRowDto[]): TaskViewRow[] {
  return history.map((h) => {
    const meta = TASK_STATUS_META[h.status];
    const status = meta === undefined ? h.status : t(meta.key);
    const parts = [status];
    if (asNum(h.started_at) !== null) parts.push(fmtStamp(h.started_at));
    if (h.artifacts > 0) parts.push(t("dock.task.artifacts", { n: String(h.artifacts) }));
    return {
      runId: h.run_id,
      text: h.task_text,
      dot: meta === undefined ? "" : meta.dot,
      status,
      meta: parts.join(" · "),
      error: h.error,
    };
  });
}

/* ---- 使用信息 ---- */

export interface UsageRow {
  readonly key: string;
  readonly value: string;
}

export interface UsageSection {
  readonly title: string;
  readonly rows: readonly UsageRow[];
}

/** dock·使用信息（P2-M4）：token/缓存/成本/FSC 分组行；缺失留「—」不造假。 */
export function deriveUsageRows(
  metrics: Record<string, unknown> | null | undefined,
): UsageSection[] {
  const m = asObj(metrics ?? {});
  if (Object.keys(m).length === 0) return [];
  const val = (v: unknown): string => (asNum(v) === null ? "—" : String(v));
  const money = (v: unknown): string =>
    (asNum(v) === null ? "—" : t("usage.yuan", { v: String(v) }));
  const pct = (v: number | null): string =>
    (v === null ? "—" : `${(v * 100).toFixed(1)}%`);
  const u = asObj(m.usage);
  const cache = asObj(m.cache);
  const reply = asObj(cache.reply);
  const shape = asObj(cache.shape);
  const bd = asObj(m.breakdown);
  const cost = asObj(m.cost);
  const reqs = asZero(reply.hits) + asZero(reply.misses);
  const tokenHit = asNum(u.input) !== null && asZero(u.input) > 0
    ? asZero(u.cache_read) / asZero(u.input)
    : null;
  const latestUsage = asObj(m.usage_latest);
  const chRatio = asZero(latestUsage.input) > 0
    ? asZero(latestUsage.cache_read) / asZero(latestUsage.input)
    : null;
  // E0-6：CH 三分（首调用/延续/辅助）——缺失留『—』
  const chSplit = asObj(m.ch_split);
  const splitVal = (cat: unknown): string => {
    const c = asObj(cat);
    if (asNum(c.calls) === null) return "—";
    return `${pct(asNum(c.ratio))} · ${t("usage.nCalls", {
      n: String(asZero(c.calls)),
    })}`;
  };
  const sections: UsageSection[] = [
    {
      title: t("usage.overview"),
      rows: [
        { key: t("usage.calls"), value: val(m.llm_calls) },
        { key: t("usage.tokensIn"), value: val(u.input) },
        { key: t("usage.tokensOut"), value: val(u.output) },
        { key: t("usage.cacheRead"), value: val(u.cache_read) },
        { key: t("usage.cacheWrite"), value: val(u.cache_write) },
      ],
    },
    {
      title: t("usage.cacheTitle"),
      rows: [
        { key: t("usage.reqHit"), value: reqs > 0 ? pct(asZero(reply.hits) / reqs) : "—" },
        { key: t("usage.cacheHitLatest"), value: pct(chRatio) },
        { key: t("usage.tokenHit"), value: pct(tokenHit) },
        { key: t("usage.replyCache"), value: `${asZero(reply.hits)} / ${asZero(reply.misses)} / ${asZero(reply.similar_hits)}` },
        { key: t("usage.shapeCache"), value: `${asZero(shape.hits)} / ${asZero(shape.misses)}` },
        { key: t("usage.semantic"), value: `${asZero(bd.semantic_hits)} / ${asZero(bd.semantic_ok)}` },
        { key: t("usage.missStruct"), value: `${asZero(bd.first_round_misses)} / ${asZero(bd.later_round_misses)}` },
        { key: t("usage.chSplitFirst"), value: splitVal(chSplit.first) },
        { key: t("usage.chSplitCont"), value: splitVal(chSplit.continuation) },
        { key: t("usage.chSplitAux"), value: splitVal(chSplit.auxiliary) },
      ],
    },
    {
      title: t("usage.costTitle"),
      rows: [
        { key: t("usage.cost"), value: money(cost.estimate) },
        { key: t("usage.saveTokens"), value: val(cost.save_tokens) },
        { key: t("usage.saveCost"), value: money(cost.save_cost) },
        { key: t("usage.cacheReadRatio"), value: pct(asNum(cost.cache_read_ratio)) },
      ],
    },
  ];
  const fsc = m.fsc === null || m.fsc === undefined ? null : asObj(m.fsc);
  if (fsc === null) {
    sections.push({
      title: t("usage.fscTitle"),
      rows: [{ key: "", value: t("usage.fscOff") }],
    });
  } else {
    sections.push({
      title: t("usage.fscTitle"),
      rows: [
        { key: t("usage.fscReused"), value: val(fsc.reused) },
        { key: t("usage.fscSessions"), value: val(fsc.sessions) },
        { key: t("usage.fscCoverage"), value: pct(asNum(fsc.coverage)) },
        { key: t("usage.fscAudit"), value: val(fsc.audited) },
        { key: t("usage.fscSwitch"), value: val(fsc.switched) },
      ],
    });
  }
  return sections;
}

/* ---- 溯源 ---- */

export interface ProvenanceRow {
  readonly unitId: string;
  readonly domain: string;
  readonly dot: string;
  readonly detail: string;
  readonly depth: number;
}

/** dock·溯源树（P2-M4）：parent_id → 父子链缩进；防御缺字段/环。 */
export function deriveProvenanceRows(
  rows: readonly Record<string, unknown>[],
): ProvenanceRow[] {
  const children = new Map<string, Record<string, unknown>[]>();
  const roots: Record<string, unknown>[] = [];
  for (const row of rows) {
    const parent = asText(row.parent_id);
    if (parent === "") {
      roots.push(row);
      continue;
    }
    const list = children.get(parent) ?? [];
    list.push(row);
    children.set(parent, list);
  }
  const out: ProvenanceRow[] = [];
  const visited = new Set<string>();
  const visit = (row: Record<string, unknown>, depth: number): void => {
    const unitId = asText(row.unit_id);
    if (unitId === "" || visited.has(unitId) || depth > 12) return;
    visited.add(unitId);
    const artifacts = Array.isArray(row.artifacts) ? row.artifacts.length : 0;
    const status = asText(row.status);
    const detail = [
      asText(row.domain),
      artifacts > 0 ? t("dock.prov.artifacts", { n: String(artifacts) }) : "",
      fmtStamp(asNum(row.ts)),
    ].filter((part) => part !== "").join(" · ");
    out.push({
      unitId,
      domain: asText(row.domain),
      dot: status === "ok" ? "ok" : status === "failed" ? "bad" : "",
      detail,
      depth,
    });
    for (const child of children.get(unitId) ?? []) visit(child, depth + 1);
  };
  for (const root of [...roots, ...rows]) visit(root, 0);
  return out;
}

/* ---- 链路 / 事件日志 ---- */

export interface TraceViewRow {
  readonly time: string;
  readonly event: string;
  readonly unit: string;
  readonly detail: string;
}

export function deriveTraceRows(
  rows: readonly Record<string, unknown>[],
): TraceViewRow[] {
  const skip = new Set(["ts", "event", "unit_id", "domain"]);
  return rows.map((row) => ({
    time: fmtClock(asNum(row.ts)),
    event: asText(row.event),
    unit: asText(row.unit_id),
    detail: Object.entries(row)
      .filter(([key]) => !skip.has(key))
      .map(([key, value]) =>
        `${key}=${typeof value === "object" ? JSON.stringify(value) : String(value)}`)
      .join(" "),
  }));
}

export interface EventLogRow {
  readonly time: string;
  readonly type: string;
  readonly detail: string;
}

export function deriveEventLogRows(
  rows: readonly Record<string, unknown>[],
): EventLogRow[] {
  return rows.map((row) => ({
    time: fmtClock(asNum(row.ts)),
    type: asText(row.type),
    detail: [
      asText(row.workspace_id),
      row.data === undefined ? "" : JSON.stringify(row.data).slice(0, 90),
    ].filter((part) => part !== "").join(" · "),
  }));
}

/* ---- 通知 ---- */

export interface NoticeViewRow {
  readonly seq: number;
  readonly level: string;
  readonly title: string;
  readonly meta: string;
  readonly seal: string;   // 印章文字（相关文字——裁决 2026-09-18）
}

function noticeTitle(item: NotificationDto): string {
  if (item.type === "safety_blocked") {
    return t("notices.safety", { tool: item.tool || "—", reason: item.reason || "" });
  }
  if (item.type === "task_failed") return t("notices.failed");
  if (item.type === "task_cancelled") return t("notices.cancelled");
  const map: Record<string, string> = {
    partial: "notices.partial",
    failed: "notices.failed",
    cancelled: "notices.cancelled",
  };
  return t(map[item.status] ?? "notices.done");
}

function noticeSeal(item: NotificationDto): string {
  if (item.type === "safety_blocked") return t("notices.seal.safety");
  if (item.type === "task_failed" || item.status === "failed") return t("notices.seal.failed");
  if (item.type === "task_cancelled" || item.status === "cancelled") return t("notices.seal.cancelled");
  if (item.status === "partial") return t("notices.seal.partial");
  return t("notices.seal.done");
}

export function deriveNoticeRows(items: readonly NotificationDto[]): NoticeViewRow[] {
  return items.map((item) => ({
    seq: item.seq,
    level: item.level,
    title: noticeTitle(item),
    meta: [item.workspace_name || item.workspace_id, fmtStamp(asNum(item.ts))]
      .filter((part) => part !== "").join(" · "),
    seal: noticeSeal(item),
  }));
}

/* ---- 智脑 ---- */

export interface BrainView {
  readonly enabled: boolean;
  readonly summary: readonly UsageRow[];
  readonly recent: readonly NoticeViewRow[];
}

/** dock·智脑统计（P2-M4）：容量/尝试/成功率/分级 + 最近案例。 */
export function deriveBrainRows(brain: BrainStatsDto | null): BrainView {
  if (brain === null) return { enabled: false, summary: [], recent: [] };
  return {
    enabled: brain.enabled,
    summary: [
      { key: t("brain.capacity"), value: `${brain.cases} / ${brain.capacity}` },
      { key: t("brain.attempts"), value: String(brain.attempts) },
      {
        key: t("brain.successRate"),
        value: brain.attempts > 0 ? `${(brain.success_rate * 100).toFixed(1)}%` : "—",
      },
      {
        key: t("brain.tiers"),
        value: `${t("brain.tier.high")} ${brain.tiers.high} · ` +
          `${t("brain.tier.normal")} ${brain.tiers.normal} · ` +
          `${t("brain.tier.low")} ${brain.tiers.low}`,
      },
    ],
    recent: brain.recent.map((c) => ({
      seq: 0,
      level: c.tier === "high" ? "ok" : c.tier === "low" ? "bad" : "",
      title: c.key === "" ? "—" : c.key,
      meta: [c.domain, c.model, `${Math.round(c.success_rate * 100)}%`, String(c.attempts)]
        .filter((part) => part !== "").join(" · "),
      seal: "",   // 智脑行不用印章（保留圆点；印章仅通知——裁决 2026-09-18）
    })),
  };
}

/* ---- 报告 ---- */

export interface ReportViewRow {
  readonly name: string;
  readonly path: string;
  readonly detail: string;
}

export function deriveReportRows(reports: readonly ReportEntryDto[]): ReportViewRow[] {
  return reports.map((r) => ({
    name: r.name,
    path: r.path,
    detail: [fmtSize(r.size), fmtStamp(asNum(r.mtime))]
      .filter((part) => part !== "").join(" · "),
  }));
}

/* ---- 技能发现（P2-M5） ---- */

export interface DiscoverViewRow {
  readonly name: string;
  readonly detail: string;
}

/** dock·技能发现行：名称 + 描述/摘要（防御缺字段）。 */
export function deriveDiscoverRows(
  items: readonly Record<string, unknown>[],
): DiscoverViewRow[] {
  return items.map((item) => ({
    name: asText(item.name) === "" ? "—" : asText(item.name),
    detail: (asText(item.description) || asText(item.summary)).slice(0, 120),
  }));
}

/* ---- P2-M6 主视图派生（思维链/产物/恢复动作/搜索/面板过滤） ---- */

function statusText(raw: string): string {
  const meta = TASK_STATUS_META[raw];
  return meta === undefined ? raw : t(meta.key);
}

export interface ThoughtView {
  readonly unitId: string;
  readonly round: number;
  readonly text: string;
  readonly open: boolean;
}

/** 思维链块（P2-M6）：终态自动折叠（R4-3——保留可展开）。 */
export function deriveThoughtRows(
  thoughts: readonly ThoughtRow[],
  terminal: boolean,
): ThoughtView[] {
  return thoughts.map((thought) => ({
    unitId: thought.unitId,
    round: thought.round,
    text: thought.text,
    open: !terminal,
  }));
}

export interface ArtifactLink {
  readonly unitId: string;
  readonly path: string;
  readonly kind: string;
  readonly url: string;
}

/** 产物链接（P2-M6）：结果清单 + 流内单元产物去重合并；URL 走既有 artifacts 路由。 */
/** 结果卡产物链接（**本 run 作用域**）：快照 result 产物 ∪ 运行事件产物（去重）。
 *
 *  归属澄清（U8）：两类来源都是「本 run」——`tasks.ts` 在同一 run 内累计
 *  `unitArtifacts`，换 run 即清空；工作区**全部**产物见右栏「产物」面板
 *  （manifest 级，跨 run 聚合），两者口径不同，UI 已分别标注。
 */
export function deriveArtifactLinks(
  result: ResultDto | null,
  unitArtifacts: readonly UnitArtifactRow[],
  wsId: string,
): ArtifactLink[] {
  const seen = new Set<string>();
  const out: ArtifactLink[] = [];
  const base = wsId === "" ? "" : `/api/v1/workspaces/${wsId}/artifacts/`;
  const push = (unitId: string, path: string, kind: string): void => {
    if (path === "" || seen.has(path) || isInternalArtifact(path)) return;
    seen.add(path);
    out.push({ unitId, path, kind, url: `${base}${encodeURI(path)}` });
  };
  for (const artifact of result?.artifacts ?? []) {
    push("", artifact.path, artifact.kind);
  }
  for (const artifact of unitArtifacts) {
    push(artifact.unitId, artifact.path, artifact.kind);
  }
  return out;
}

export interface RecoveryAction {
  readonly id: "retry" | "resume" | "rollback" | "override";
  readonly key: string;
}

/** 结果恢复动作（P2-M6 旧壳口径）：重试=回填输入区；续跑=取消/错误可续；
 *  回滚=已产出运行；override=needs_design 跳过设计仍要执行（二期批 1）。 */
export function deriveRecoveryActions(status: TaskStatus): RecoveryAction[] {
  const actions: RecoveryAction[] = [];
  if (status === "needs_design") {
    actions.push({ id: "override", key: "stream.override" });
  }
  if (["done", "partial", "failed", "cancelled", "error"].includes(status)) {
    actions.push({ id: "retry", key: "stream.retry" });
  }
  if (status === "cancelled" || status === "error") {
    actions.push({ id: "resume", key: "stream.resume" });
  }
  if (status === "done" || status === "partial" || status === "failed") {
    actions.push({ id: "rollback", key: "stream.rollback" });
  }
  return actions;
}

export interface DesignTicketRow {
  readonly id: string;
  readonly statement: string;
  readonly recommend: string;
  readonly blockedBy: readonly string[];
  readonly frontier: boolean;
}

/** 实施票据状态 → i18n key（审查 F3）：done/failed/running 不得再显示「待发布」。 */
export function implTicketStatusKey(status: string): string {
  switch (status) {
    case "ready": return "design.ticketReady";
    case "running": return "design.ticketRunning";
    case "done": return "design.ticketDone";
    case "failed": return "design.ticketFailed";
    case "cancelled": return "design.ticketCancelled";
    default: return "design.ticketProposed";
  }
}

/** 设计票据行（批 2）：票据优先；无票据时回落旧 questions（兼容旧态——id 空）。 */
export function deriveDesignTicketRows(
  tickets: readonly { id: string; statement: string; recommend: string;
                      blocked_by?: readonly string[]; frontier?: boolean }[],
  questions: readonly { q: string; recommend: string }[],
): DesignTicketRow[] {
  if (tickets.length > 0) {
    return tickets.map((t) => ({
      id: t.id, statement: t.statement, recommend: t.recommend,
      blockedBy: t.blocked_by ?? [], frontier: t.frontier !== false,
    }));
  }
  return questions.map((q) => ({
    id: "", statement: q.q, recommend: q.recommend, blockedBy: [], frontier: true,
  }));
}

export interface SearchRow {
  readonly kind: "task" | "session";
  readonly wsId: string;
  readonly title: string;
  readonly meta: string;
}

/** 全库搜索行（P2-M6）：任务（工作区 · 状态）/ 会话（工作区 · 片段）。 */
export function deriveSearchRows(result: SearchResultDto | null): SearchRow[] {
  if (result === null) return [];
  const rows: SearchRow[] = [];
  for (const task of result.tasks) {
    rows.push({
      kind: "task",
      wsId: task.ws_id,
      title: task.text,
      meta: [task.ws_name, statusText(task.status)]
        .filter((part) => part !== "").join(" · "),
    });
  }
  for (const session of result.sessions) {
    rows.push({
      kind: "session",
      wsId: session.ws_id,
      title: session.name,
      meta: [session.ws_name, session.snippet]
        .filter((part) => part !== "").join(" · "),
    });
  }
  return rows;
}

export interface PaletteCommandLike {
  readonly title: string;
  readonly keywords?: string;
}

/** 命令面板过滤（P2-M6）：空查询全量；否则 title/keywords 包含匹配（大小写无关）。 */
export function filterPaletteCommands<T extends PaletteCommandLike>(
  commands: readonly T[],
  query: string,
): T[] {
  const q = query.trim().toLowerCase();
  if (q === "") return [...commands];
  return commands.filter((command) =>
    `${command.title} ${command.keywords ?? ""}`.toLowerCase().includes(q));
}

/* ---- 观测视图加载态机 ---- */

export type DockLoadStatus = "idle" | "loading" | "ready" | "error";

export interface DockLoadState {
  readonly status: DockLoadStatus;
  readonly error: string;
}

export const IDLE_DOCK_STATE: DockLoadState = { status: "idle", error: "" };

export function nextDockState(
  current: DockLoadState,
  event: "load" | "ready" | "fail" | "invalidate",
  error = "",
): DockLoadState {
  switch (event) {
    case "load":
      return current.status === "loading" ? current : { status: "loading", error: "" };
    case "ready":
      return { status: "ready", error: "" };
    case "fail":
      return { status: "error", error };
    case "invalidate":
      return current.status === "idle" ? current : IDLE_DOCK_STATE;
  }
}

/* ============ 轮次化（2026-09-21 工作区域批次）：过程折叠 / 并行 chips / 思考摘要 ============ */

const TERMINAL_STATUSES: readonly string[] = [
  "done", "partial", "failed", "cancelled", "error",
];

/** 终态判定（过程收起/思维链折叠共用口径）。 */
export function isTerminalStatus(status: string): boolean {
  return TERMINAL_STATUSES.includes(status);
}

export interface ChipView {
  readonly unitId: string;
  readonly domain: string;
  readonly label: string;
  readonly status: string;
}

const CHIP_LABEL_MAX = 12;

function clipText(text: string, max: number): string {
  const s = (text || "").trim();
  return s.length <= max ? s : `${s.slice(0, max)}…`;
}

/** 实时并行碎片 chips：仅 ≥2 个 running 时出现（线性任务主会话不出现碎片——用户运行思路）。 */
export function deriveLiveChips(rows: readonly TaskRow[]): ChipView[] {
  const running = rows.filter((row) => row.status === "running");
  if (running.length < 2) return [];
  return running.map((row) => ({
    unitId: row.unitId,
    domain: row.domainId,
    label: clipText(row.detail, CHIP_LABEL_MAX),
    status: row.status,
  }));
}

/** 思考单行摘要：运行中=最新一行；结束=首行（剥 `**`——DSH 口径）；空=null。 */
export function deriveThinkingSummary(
  thoughts: readonly ThoughtRow[],
  running: boolean,
): string | null {
  if (thoughts.length === 0) return null;
  const lines = (text: string): string[] =>
    text.replace(/\*\*/g, "").split("\n").map((l) => l.trim()).filter((l) => l !== "");
  const first = thoughts[0];
  const last = thoughts[thoughts.length - 1];
  if (!first || !last) return null;
  if (running) {
    const tail = lines(last.text);
    return tail.length > 0 ? (tail[tail.length - 1] ?? null) : null;
  }
  const head = lines(first.text);
  return head.length > 0 ? (head[0] ?? null) : null;
}

export interface SessionRoundLike {
  readonly round: number;
  readonly fragments: readonly { readonly duration_ms: number | null }[];
}

export interface RoundLiveInput {
  readonly taskText: string;
  readonly status: string;
  readonly rows: readonly TaskRow[];
  readonly thoughts: readonly ThoughtRow[];
}

export interface RoundView {
  readonly key: string;
  readonly userText: string;
  readonly live: boolean;
  readonly thinking: string | null;
  readonly chips: readonly ChipView[];
  readonly summary: string | null;
  readonly answer: string | null;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(1, Math.round(ms))}ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  return `${m}m${s % 60}s`;
}

function buildProcessSummary(steps: number, durationsMs: readonly number[]): string {
  const base = t("stream.processSummary", { steps: String(steps) });
  const total = durationsMs.reduce((sum, d) => sum + d, 0);
  if (total <= 0) return base;
  return base + t("stream.processDuration", { duration: formatDuration(total) });
}

/** 轮次视图：历史 transcript（+ rounds 富化，批 3 接入）+ 实时轮（过程组数据）。 */
export function deriveRoundViews(input: {
  transcript: readonly ChatMessage[];
  rounds?: readonly SessionRoundLike[];
  live: RoundLiveInput | null;
}): RoundView[] {
  const rounds = input.rounds ?? [];
  const views: RoundView[] = [];
  let userText: string | null = null;
  let answer: string | null = null;
  let roundNo = 0;
  const flush = (): void => {
    if (userText === null) return;
    const meta = rounds.find((r) => r.round === roundNo);
    const steps = meta ? meta.fragments.length : 0;
    const durations = meta
      ? meta.fragments
        .map((f) => (typeof f.duration_ms === "number" && f.duration_ms > 0 ? f.duration_ms : 0))
        .filter((d) => d > 0)
      : [];
    views.push({
      key: `round:${roundNo}:${views.length}`,
      userText, live: false, thinking: null, chips: [],
      summary: steps > 0 ? buildProcessSummary(steps, durations) : null,
      answer,
    });
    userText = null;
    answer = null;
  };
  for (const msg of input.transcript) {
    if (msg.kind === "user") {
      flush();
      userText = msg.text;
      roundNo = msg.round;
    } else if (userText !== null) {
      answer = answer === null ? msg.text : `${answer}\n${msg.text}`;
    }
  }
  const live = input.live;
  const liveActive = !!live && live.taskText !== "" && live.status !== "idle";
  const buildLive = (inputLive: RoundLiveInput, running: boolean): RoundView => ({
    key: "live",
    userText: inputLive.taskText,
    live: true,
    thinking: deriveThinkingSummary(inputLive.thoughts, running),
    chips: deriveLiveChips(inputLive.rows),
    summary: running ? null : buildProcessSummary(inputLive.rows.length, []),
    answer: null,
  });
  if (liveActive && userText !== null && userText === live!.taskText) {
    const recorded = answer !== null;   // 已完成并已入 transcript：不重复渲染
    userText = null;
    answer = null;
    if (!recorded) views.push(buildLive(live!, !isTerminalStatus(live!.status)));
  } else {
    flush();
    if (liveActive) views.push(buildLive(live!, !isTerminalStatus(live!.status)));
  }
  return views;
}

/* ============ 左栏会话树（2026-09-21 批 3）：仅非线性轮出碎片行 ============ */

export interface RailFragRow {
  readonly unitId: string;
  readonly domain: string;
  readonly goal: string;
  readonly status: string;
}

export interface RailRoundRow {
  readonly round: number;
  readonly label: string;
  readonly fragments: readonly RailFragRow[];
}

export interface RailRoundSource {
  readonly round: number;
  readonly user_text: string;
  readonly parallel: boolean;
  readonly fragments: readonly {
    readonly unit_id: string;
    readonly domain: string;
    readonly goal: string;
    readonly status: string;
    readonly parallel: boolean;
  }[];
}

/** 左栏树派生：仅并行碎片（parallel=true）出小字行；无碎片的轮不出现（用户运行思路）。 */
export function deriveRailRounds(rounds: readonly RailRoundSource[]): RailRoundRow[] {
  const out: RailRoundRow[] = [];
  for (const r of rounds) {
    const fragments = r.fragments
      .filter((f) => f.parallel)
      .map((f) => ({
        unitId: f.unit_id,
        domain: f.domain,
        goal: clipText(f.goal, 16),
        status: f.status,
      }));
    if (fragments.length === 0) continue;
    out.push({ round: r.round, label: clipText(r.user_text, 12), fragments });
  }
  return out;
}

/* ============ 碎片会话消息（批 3）：seed/增量 → 会话语汇 ============ */

export interface UnitSessionGroupLike {
  readonly state: string;
  readonly messages: readonly Record<string, unknown>[];
}

export interface FragmentItem {
  readonly kind: "system" | "user" | "assistant" | "tool" | "think" | "status";
  readonly text: string;
  /** 绑定轮次产物（可选——助手气泡上的 references chips） */
  readonly artifacts?: readonly string[];
}

/** 碎片会话会话流（2026-09-21）：seed→系统/用户；thinking→思维链（折叠）与工具行；done/failed→状态行。 */
export function deriveFragmentConversation(
  groups: readonly UnitSessionGroupLike[],
): FragmentItem[] {
  const out: FragmentItem[] = [];
  for (const g of groups) {
    if (g.state === "done" || g.state === "failed") {
      out.push({ kind: "status", text: g.state === "done" ? "done" : "failed" });
      continue;
    }
    let think: string[] = [];
    const flushThink = (): void => {
      if (think.length > 0) out.push({ kind: "think", text: think.join("\n\n") });
      think = [];
    };
    for (const m of g.messages) {
      const text = String(m.content ?? "");
      if (text === "") continue;
      const role = String(m.role ?? "");
      if (role === "system") {
        flushThink();
        out.push({ kind: "system", text });
      } else if (text.startsWith("[tool]")) {
        flushThink();
        out.push({ kind: "tool", text });
      } else if (g.state === "seed") {
        flushThink();
        out.push({ kind: "user", text });
      } else {
        think.push(text);
      }
    }
    flushThink();
  }
  return out;
}

/** 碎片会话映射：seed→用户任务；增量→LLM 输出（助手）与 `[tool]` 工具行；系统提示单独折叠。 */
export function deriveUnitSessionMessages(
  groups: readonly UnitSessionGroupLike[],
): FragmentItem[] {
  const out: FragmentItem[] = [];
  for (const g of groups) {
    for (const m of g.messages) {
      const text = String(m.content ?? "");
      if (text === "") continue;
      const role = String(m.role ?? "");
      if (role === "system") out.push({ kind: "system", text });
      else if (text.startsWith("[tool]")) out.push({ kind: "tool", text });
      else if (g.state === "seed") out.push({ kind: "user", text });
      else out.push({ kind: "assistant", text });
    }
  }
  return out;
}

/* ============ 碎片实时切片与绑定轮次（碎片会话后半程 2026-09-22） ============ */

export interface FragmentLiveInput {
  readonly unitId: string;
  /** 由碎片视图内提交的 run（null = 未绑定——按 unit 过滤实时数据） */
  readonly boundRunId: string | null;
  readonly runId: string;
  readonly status: string;
  readonly taskText: string;
  readonly rows: readonly TaskRow[];
  readonly thoughts: readonly ThoughtRow[];
  /** 已入绑定轮次的用户文本（防实时气泡与历史重复） */
  readonly boundUserTexts: readonly string[];
}

export interface FragmentLiveView {
  readonly running: boolean;
  readonly showUser: boolean;
  readonly userText: string;
  readonly chips: readonly ChipView[];
  readonly thoughts: readonly ThoughtView[];
  readonly rows: readonly TaskRow[];
  readonly steps: number;
}

/** 碎片实时切片：绑定 run 全量（该轮=碎片自己的任务）；否则按 unit 过滤（维度隔离）。 */
export function deriveFragmentLive(input: FragmentLiveInput): FragmentLiveView | null {
  if (input.status === "idle") return null;
  const bound = input.boundRunId !== null && input.boundRunId !== ""
    && input.runId !== "" && input.runId === input.boundRunId;
  const rows = bound
    ? [...input.rows]
    : input.rows.filter((r) => r.unitId === input.unitId);
  const thoughts = bound
    ? [...input.thoughts]
    : input.thoughts.filter((th) => th.unitId === input.unitId);
  if (!bound && rows.length === 0 && thoughts.length === 0) return null;
  const running = !isTerminalStatus(input.status);
  return {
    running,
    showUser: bound && input.taskText !== ""
      && !input.boundUserTexts.includes(input.taskText),
    userText: input.taskText,
    chips: deriveLiveChips(rows),
    thoughts: deriveThoughtRows(thoughts, !running),
    rows,
    steps: rows.length,
  };
}

export interface BoundRoundLike {
  readonly round: number;
  readonly user_text: string;
  readonly summary: string;
  readonly ts: number;
  readonly artifacts: readonly string[];
}

/** 绑定轮次 → 会话项（轮次升序；用户/助手成对；空摘要且无产物不生成助手项）。 */
export function deriveBoundRoundItems(
  rounds: readonly BoundRoundLike[],
): FragmentItem[] {
  const out: FragmentItem[] = [];
  for (const r of [...rounds].sort((a, b) => a.round - b.round)) {
    if (r.user_text === "") continue;
    out.push({ kind: "user", text: r.user_text, artifacts: [] });
    if (r.summary !== "" || r.artifacts.length > 0) {
      out.push({ kind: "assistant", text: r.summary, artifacts: [...r.artifacts] });
    }
  }
  return out;
}

/* ============ 轨迹视图（批 4）：按轮分组表格行 ============ */

export interface TrajectoryRow {
  readonly key: string;
  readonly round: number;
  readonly session: string;
  readonly unitId: string;
  readonly domain: string;
  readonly goal: string;
  readonly status: string;
  readonly duration: string;
  readonly toolCalls: number;
  readonly artifacts: number;
  readonly parallel: boolean;
}

export interface TrajectoryRoundSource {
  readonly session: string;
  readonly round: number;
  readonly fragments: readonly {
    readonly unit_id: string;
    readonly domain: string;
    readonly goal: string;
    readonly status: string;
    readonly duration_ms: number | null;
    readonly tool_calls: number;
    readonly artifacts: readonly string[];
    readonly parallel: boolean;
  }[];
}

/** 轨迹行派生（信息最全口径：线性+非线性碎片全量入表；耗时缺失显示「—」）。 */
export function deriveTrajectoryRows(
  rounds: readonly TrajectoryRoundSource[],
): TrajectoryRow[] {
  const out: TrajectoryRow[] = [];
  for (const r of rounds) {
    for (const f of r.fragments) {
      out.push({
        key: `${r.session}:${r.round}:${f.unit_id}`,
        round: r.round,
        session: r.session,
        unitId: f.unit_id,
        domain: f.domain,
        goal: f.goal,
        status: f.status,
        duration: typeof f.duration_ms === "number" ? formatDuration(f.duration_ms) : "—",
        toolCalls: f.tool_calls,
        artifacts: f.artifacts.length,
        parallel: f.parallel,
      });
    }
  }
  return out;
}

/* ============ 历史轮富化（2026-09-21）：主会话内的并行碎片呈现 ============ */

export interface RoundChipSource {
  readonly round: number;
  readonly fragments: readonly {
    readonly unit_id: string;
    readonly domain: string;
    readonly goal: string;
    readonly status: string;
    readonly parallel: boolean;
    readonly duration_ms: number | null;
  }[];
}

/** 历史轮富化：并行碎片 chips + 过程摘要（无并行碎片→null——线性轮主会话不出碎片）。 */
export function deriveRoundChips(
  rounds: readonly RoundChipSource[],
  roundNo: number,
): { summary: string; chips: ChipView[] } | null {
  const r = rounds.find((x) => x.round === roundNo);
  if (!r) return null;
  const parallel = r.fragments.filter((f) => f.parallel);
  if (parallel.length === 0) return null;
  const durations = r.fragments
    .map((f) => (typeof f.duration_ms === "number" && f.duration_ms > 0 ? f.duration_ms : 0))
    .filter((d) => d > 0);
  return {
    summary: buildProcessSummary(r.fragments.length, durations),
    chips: parallel.map((f) => ({
      unitId: f.unit_id, domain: f.domain, label: clipText(f.goal, 12), status: f.status,
    })),
  };
}

/* ============ T-4 确认区键盘导航（纯函数；DOM 绑定见 views/confirm-keys.ts） ============ */

/** 确认区键盘动作（Alt 组合键；选择/导航不含放行语义，approve/reject 复用既有按钮路径）。 */
export type ConfirmKeyAction =
  | "prev" | "next" | "toggle" | "toggleAll" | "approve" | "reject";

/** Alt 组合键 → 动作；修饰键多余（Ctrl/Meta/Shift）或 IME 组字/已消费则不匹配。 */
export function resolveConfirmKey(ev: {
  readonly code: string;
  readonly altKey: boolean;
  readonly ctrlKey: boolean;
  readonly metaKey: boolean;
  readonly shiftKey: boolean;
  readonly isComposing?: boolean;
  readonly defaultPrevented?: boolean;
}): ConfirmKeyAction | null {
  if (ev.defaultPrevented === true || ev.isComposing === true) return null;
  if (!ev.altKey || ev.ctrlKey || ev.metaKey || ev.shiftKey) return null;
  switch (ev.code) {
    case "ArrowUp": return "prev";
    case "ArrowDown": return "next";
    case "KeyX": return "toggle";
    case "KeyA": return "toggleAll";
    case "KeyY": return "approve";
    case "KeyN": return "reject";
    default: return null;
  }
}

/** 跳转目标索引：空列表 -1；当前不在列表（-1）时 next→0 / prev→末位；越界钳制（不循环）。 */
export function focusIndex(current: number, count: number, delta: -1 | 1): number {
  if (count <= 0) return -1;
  if (current < 0) return delta > 0 ? 0 : count - 1;
  const next = current + delta;
  if (next < 0 || next >= count) return current;
  return next;
}

/* ============ T-6 首用引导（纯函数；记账/渲染见 main.ts 与 hero.ts） ============ */

export interface OnboardInput {
  readonly heroVisible: boolean;
  readonly done: boolean;
}

/** 首用引导条显示条件：零态可见且未记账（提交/知道了 之后永久隐藏）。 */
export function shouldShowOnboard(input: OnboardInput): boolean {
  return input.heroVisible && !input.done;
}

/* ============ 设计卡「采用推荐」可加可退（纯函数；2026-10-16） ============ */

/** 推荐行构造：`<前缀><推荐>`（独立一行；前缀经 i18n 传入）。 */
export function recommendLine(prefix: string, recommend: string): string {
  return `${prefix}${recommend}`;
}

/** 输入框中是否已含该推荐行（逐行整行匹配，首尾空白容错）。 */
export function hasRecommendLine(text: string, line: string): boolean {
  const want = line.trim();
  return text.split("\n").some((l) => l.trim() === want);
}

/** 采用/取消采用：无 → 末尾追加一行；有 → 移除首个匹配行（其余文本不动）。
 *  追加前 trimEnd 防双空行；移除后 trimEnd 不留尾随空行。 */
export function toggleRecommendText(text: string, line: string): string {
  const want = line.trim();
  const lines = text.split("\n");
  const idx = lines.findIndex((l) => l.trim() === want);
  if (idx >= 0) {
    lines.splice(idx, 1);
    return lines.join("\n").replace(/\s+$/, "");
  }
  const base = text.replace(/\s+$/, "");
  return base === "" ? line : `${base}\n${line}`;
}

/* ============ 移动适配（O5 T4-A · 2026-10-17）：dock 窄屏默认收起 ============ */

/** 无持久值时：窄屏（≤768px）默认收起 dock 浮层（桌面保持展开）。 */
export function defaultDockCollapsed(persisted: string | null,
                                     narrow: boolean): boolean {
  if (persisted !== null) return persisted === "1";
  return narrow;
}
