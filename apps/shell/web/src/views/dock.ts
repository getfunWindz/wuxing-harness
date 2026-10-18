/** 右栏 dock（P2-S10 骨架 → P2-M4 观测视图补全）：12 视图（默认启用五视图，其余经设置自选）。
    —— 动画语言与左栏一致（内容淡出 150ms → 轨道滑动 → 图标滑入 150ms）。
    —— 数据视图三态：加载中 / 失败（可见 + 重试）/ 空态。 */
import { h, mount } from "../render/dom.ts";
import type { ComponentInstance } from "../render/component.ts";
import type { ContextPreviewDto, SkillDetailDto, SkillDiscoverDto } from "../protocol/generated.ts";
import { renderMarkdown } from "./markdown.ts";
import { skillToolsRows, validateSkillDraft } from "./skill-form.ts";
import { t } from "./i18n.ts";
import {
  IDLE_DOCK_STATE,
  artifactMeta,
  contextBandView,
  ctxEditActions,
  contextBarSegments,
  defaultDockCollapsed,
  deriveContextRounds,
  deriveDiscoverRows,
  formatContextPercent,
  formatTokenCount,
  type ArtifactRow,
  type ArtifactPreviewView,
  type BrainView,
  type ContextRowView,
  type DockLoadState,
  type EventLogRow,
  type McpRow,
  type NoticeViewRow,
  type ProvenanceRow,
  type RecycleRow,
  type ReportViewRow,
  type SessionRow,
  type SkillRow,
  type TaskViewRow,
  type TraceViewRow,
  type UsageSection,
} from "./view-model.ts";
import {
  ICON_ARTIFACT, ICON_BELL, ICON_BRAIN, ICON_CHEVRON, ICON_LOG, ICON_MCP,
  ICON_RECYCLE, ICON_REPORTS, ICON_SESSION, ICON_SKILL, ICON_TASK, ICON_USAGE,
} from "./icons.ts";
import { svgIcon } from "../render/dom.ts";

/** 收起态图标轨：视图 → 图标（旧壳 dock-views 图标口径）。 */
const VIEW_ICONS: Record<string, readonly string[]> = {
  artifacts: ICON_ARTIFACT,
  skills: ICON_SKILL,
  mcp: ICON_MCP,
  recycle: ICON_RECYCLE,
  sessions: ICON_SESSION,
  trajectory: ICON_LOG,
  tasks: ICON_TASK,
  usage: ICON_USAGE,
  provenance: ICON_LOG,
  log: ICON_LOG,
  notifications: ICON_BELL,
  brain: ICON_BRAIN,
  reports: ICON_REPORTS,
};

const DOCK_KEY = "wuxing.dock.v2";
const DOCK_VIEWS_KEY = "wuxing.dock.views.v1";

export type DockViewId =
  | "artifacts" | "skills" | "mcp" | "recycle" | "sessions"
  | "tasks" | "usage" | "provenance" | "log" | "notifications" | "brain" | "reports"
  | "trajectory";

export const DOCK_VIEW_IDS: readonly DockViewId[] = [
  "artifacts", "skills", "mcp", "recycle", "sessions",
  "tasks", "usage", "provenance", "log", "notifications", "brain", "reports",
  "trajectory",
];

/** 默认启用集（M1/M2 后的现状五视图；观测视图默认关——R2-2 口径延续）。 */
export const DEFAULT_DOCK_VIEWS: readonly DockViewId[] = [
  "artifacts", "skills", "mcp", "recycle", "sessions", "notifications",
];   /* 2026-09-19：通知默认入列（右栏可直接看通知；左栏不再驱动右栏临时加视图） */

export interface ContextUnitView {
  readonly unitId: string;
  readonly percent: number | null;
  readonly rounds: number;
}

export interface DockData {
  readonly artifacts: readonly ArtifactRow[];
  /** A6（W1）：产物预览面板状态（null = 未打开；内容已在取数层截断） */
  readonly artifactPreview: ArtifactPreviewView | null;
  readonly skills: readonly SkillRow[];
  readonly mcp: readonly McpRow[];
  readonly recycle: readonly RecycleRow[];
  readonly sessions: readonly SessionRow[];
  /** 上下文投影（B 期）：选中会话/碎片详情 + 列表行 % + 碎片会话 */
  readonly context: ContextPreviewDto | null;
  readonly contextRows: readonly ContextRowView[];
  readonly contextUnits: readonly ContextUnitView[];
  /** U11：无活动会话时回退最近会话——显式标注来源 */
  readonly contextFallback?: boolean;
  readonly tasks: readonly TaskViewRow[];
  readonly trajectory: readonly import("./view-model.ts").TrajectoryRow[];
  readonly usage: readonly UsageSection[];
  readonly provenance: readonly ProvenanceRow[];
  readonly trace: readonly TraceViewRow[];
  readonly traceUnit: string;
  readonly log: readonly EventLogRow[];
  readonly notices: readonly NoticeViewRow[];
  readonly brain: BrainView;
  readonly reports: readonly ReportViewRow[];
  readonly skillDetail: SkillDetailDto | null;
  readonly discover: SkillDiscoverDto | null;
  readonly skillNotice: string;
  readonly mcpNotice: string;
}

export interface DockProps {
  view: DockViewId;
  enabled: readonly DockViewId[];
  data: DockData;
  states: Readonly<Record<DockViewId, DockLoadState>>;
  skillPanel: "install" | "discover" | null;
  skillBusy: boolean;
  mcpBusy: boolean;
  onSelect(view: DockViewId): void;
  /** 轮次化（批 4）：轨迹行点击 → 打开碎片会话（可选——向后兼容） */
  onOpenFragment?(unitId: string): void;
  onRestore(id: string): void;
  onPurge(id: string): void;
  onRenameSession(name: string): void;
  onExportSession(name: string): void;
  /** 上下文（B 期）：选会话 / 省略 / 替换 / 选碎片 / 来源开关（A 期） */
  onContextSelect?(name: string): void;
  onContextOmit?(name: string, round: number): void;
  onContextReplace?(name: string, round: number): void;
  /** G3：恢复（回到原文） */
  onContextRestore?(name: string, round: number): void;
  /** 批 4：一键「新会话承接」（严管档——生成承接简报并预填新会话） */
  onContextHandoff?(name: string): void;
  onContextUnit?(unitId: string): void;
  onContextSources?(
    target: { session?: string; unit?: string },
    values: Record<string, boolean | number>,
  ): void;
  /** A2：碎片消息编辑（omit/replace——三键随行携带） */
  onContextUnitEdit?(
    unit: string,
    edit: { index: number; fp_in: string; fp_out: string;
            op: "omit" | "replace" | "restore"; text?: string },
  ): void;
  /** A3：上下文预算设置（0=关闭） */
  onContextBudget?(target: { session?: string; unit?: string }, current: number): void;
  onFocusUnit(unitId: string): void;
  onOpenReport(path: string): void;
  /** A6（W1）：产物预览／动作（可选项——旧调用方向后兼容） */
  onPreviewArtifact?(path: string): void;
  onCloseArtifactPreview?(): void;
  onCopyArtifactPath?(path: string): void;
  onOpenArtifactLocal?(path: string): void;
  onLogExport(): void;
  onRetry(view: DockViewId): void;
  onSkillPanel(panel: "install" | "discover" | null): void;
  onSkillOpen(name: string): void;
  onSkillInstall(name: string, description: string, content: string): void;
  onSkillRemove(name: string): void;
  onSkillToggle(name: string, enabled: boolean): void;
  onSkillDiscover(goal: string): void;
  onMcpReload(): void;
}

const VIEW_KEYS: Record<DockViewId, string> = {
  artifacts: "dock.artifacts",
  skills: "dock.skills",
  mcp: "dock.mcp",
  recycle: "dock.recycle",
  sessions: "dock.sessions",
  trajectory: "dock.trajectory",
  tasks: "dock.tasks",
  usage: "dock.usage",
  provenance: "dock.provenance",
  log: "dock.log",
  notifications: "dock.notifications",
  brain: "dock.brain",
  reports: "dock.reports",
};

function isDockViewId(value: unknown): value is DockViewId {
  return typeof value === "string" && (DOCK_VIEW_IDS as readonly string[]).includes(value);
}

export function loadDockViews(): DockViewId[] {
  try {
    const raw = localStorage.getItem(DOCK_VIEWS_KEY);
    if (raw !== null) {
      const parsed: unknown = JSON.parse(raw);
      if (Array.isArray(parsed)) {
        const views = parsed.filter(isDockViewId);
        if (views.length > 0) return views;
      }
    }
  } catch (err) {
    void err; // 偏好不可用 → 默认集
  }
  return [...DEFAULT_DOCK_VIEWS];
}

export function saveDockViews(views: readonly DockViewId[]): void {
  try {
    localStorage.setItem(DOCK_VIEWS_KEY, JSON.stringify(views));
  } catch (err) {
    void err; // 持久化失败不阻断交互
  }
}

const viewsListeners = new Set<(views: readonly DockViewId[]) => void>();

export function onDockViewsChange(
  listener: (views: readonly DockViewId[]) => void,
): () => void {
  viewsListeners.add(listener);
  return () => { viewsListeners.delete(listener); };
}

/** 设置面入口：保存并通知（订阅者即时重渲染）。 */
export function setDockViews(views: readonly DockViewId[]): void {
  saveDockViews(views);
  for (const listener of [...viewsListeners]) listener(views);
}

function loadCollapsed(): boolean {
  try {
    return defaultDockCollapsed(
      localStorage.getItem(DOCK_KEY),
      window.matchMedia("(max-width: 768px)").matches);
  } catch (err) {
    void err; // 偏好不可用 → 默认展开
    return false;
  }
}

function saveCollapsed(value: boolean): void {
  try {
    localStorage.setItem(DOCK_KEY, value ? "1" : "0");
  } catch (err) {
    void err; // 持久化失败不阻断交互
  }
}

export function createDock(host: HTMLElement, initial: DockProps): ComponentInstance<DockProps> {
  let props = initial;
  let collapsed = loadCollapsed();
  let animating = false;
  // 动效常量（与 theme/ink.css 令牌同值——CSS 为动画时长单源，改令牌须同步）
  const MOTION_CONTENT_MS = 150;    // --motion-content
  const MOTION_STRUCTURAL_MS = 160; // --motion-structural
  const DOCK_IN_CLEANUP_MS = MOTION_CONTENT_MS + 120 + 50;  // 工具入场序列（延迟 ≤120 + 时长 150 + 余量）
  const DOCK_WIDE_CLEANUP_MS = MOTION_STRUCTURAL_MS + 80;   // 轨道展开动画清理余量
  let purgeConfirm: string | null = null;
  let skillInstallConfirm = false;
  let skillRemoveConfirm = false;
  let skillFormError = "";
  let skillFormWarn = "";
  let skillDraft = { name: "", desc: "", content: "" };
  let discoverGoal = "";
  let lastSkillPanel: "install" | "discover" | null = null;

  const root = h("aside", { class: "dock" });
  host.appendChild(root);

  function emptyState(kind: DockViewId): HTMLElement {
    return h("div", { class: "dock-empty", text: t(`dock.empty.${kind}`) });
  }

  function kvRow(key: string, value: string): HTMLElement {
    return h("div", { class: "dock-kv" },
      h("span", { class: "k", text: key }),
      h("span", { class: "v", text: value }));
  }

  function sectionNode(section: UsageSection): HTMLElement {
    return h("div", { class: "dock-sec" },
      h("div", { class: "dock-sec-head", text: section.title }),
      ...section.rows.map((row) => kvRow(row.key, row.value)));
  }

  /** 数据视图三态：加载中 / 失败可见+重试 / build（自处理空态）。 */
  function withState(view: DockViewId, build: () => HTMLElement[]): HTMLElement[] {
    const state = props.states[view] ?? IDLE_DOCK_STATE;
    if (state.status === "loading") {
      return [h("div", {
        class: "dock-empty",
        dataset: { st: `dock-state:${view}` },
        text: t("dock.loading"),
      })];
    }
    if (state.status === "error") {
      return [h("div", { class: "dock-error", dataset: { st: `dock-error:${view}` } },
        h("div", { text: t("dock.loadFailed") }),
        h("div", { class: "dock-error-msg", text: state.error }),
        h("button", {
          class: "st-btn ghost",
          attrs: { type: "button", "data-st": `dock-retry:${view}` },
          text: t("dock.retry"),
          onClick: () => { props.onRetry(view); },
        }))];
    }
    return build();
  }

  /** 上下文投影主面板（B 期 · DSH 形态）：环 + 拆段条 + 图例 + 实测锚点 + 轮次/碎片。 */
  function contextPanel(): HTMLElement[] {
    const data = props.data.context;
    if (data === null) {
      return [h("div", { class: "dock-empty", dataset: { st: "ctx-panel" },
        text: t("ctx.pickSession") })];
    }
    if (!data.available) {
      return [h("div", { class: "dock-empty", dataset: { st: "ctx-panel" },
        text: t("ctx.noData") })];
    }
    const pct = Math.min(100, Math.round(data.percent * 100));
    const head = h("div", { class: "ctx-head" },
      h("div", { class: "ctx-ring", dataset: { st: "ctx-ring" },
        attrs: { style: `--ctx-p:${pct}` } },
        h("div", { class: "ctx-ring-mid" },
          h("span", { class: "ctx-percent", dataset: { st: "ctx-percent" },
            text: `~${pct}%` }))),
      h("div", { class: "ctx-head-info" },
        h("div", { class: "ctx-title", dataset: { st: "ctx-title" },
          text: data.unit_id !== "" ? data.unit_id : data.session }),
        h("div", { class: "ctx-figures", text: t("ctx.figures", {
          used: formatTokenCount(data.est_tokens),
          window: formatTokenCount(data.window),
        }) })));
    const introEl = h("div", { class: "ctx-intro", dataset: { st: "ctx-intro" },
      text: t("ctx.intro") });
    const bar = contextBarSegments(data.segments);
    const barEl = h("div", { class: "ctx-bar", dataset: { st: "ctx-bar" } },
      ...bar.map((b) => h("div", {
        class: `ctx-bar-seg ${b.key}`,
        dataset: { st: `ctx-seg:${b.key}` },
        attrs: { style: `width:${b.percent}%`,
                 title: `${t(`ctx.seg.${b.key}`)} · ~${formatTokenCount(b.est_tokens)}` },
      })));
    const legend = h("div", { class: "ctx-legend" },
      ...bar.map((b) => h("div", { class: "ctx-legend-row" },
        h("span", { class: `ctx-swatch ${b.key}` }),
        h("span", { class: "ctx-legend-label", text: t(`ctx.seg.${b.key}`) }),
        h("span", { class: "ctx-legend-val", text: `~${formatTokenCount(b.est_tokens)}` }))));
    const nodes: HTMLElement[] = [];
    if (props.data.contextFallback === true) {
      nodes.push(h("div", {
        class: "ctx-intro", dataset: { st: "ctx-fallback" },
        text: t("ctx.fallback", { session: data.session }),
      }));
    }
    nodes.push(head);
    const bandView = contextBandView(data.band);
    if (bandView) {
      nodes.push(h("div", {
        class: `ctx-band-row ${bandView.cls}`,
        dataset: { st: "ctx-band-row" },
      },
        h("span", { class: "ctx-band-label", dataset: { st: "ctx-band" },
                    text: bandView.label }),
        bandView.hint !== ""
          ? h("span", { class: "ctx-band-hint",
                       dataset: { st: "ctx-band-hint" },
                       text: bandView.hint })
          : null,
        bandView.cls === "managed" && data.unit_id === "" && data.session !== ""
          && props.onContextHandoff
          ? h("button", {
              class: "st-btn ghost ctx-handoff",
              attrs: { type: "button", "data-st": "ctx-handoff-new" },
              text: t("ctx.handoff.new"),
              onClick: () => { props.onContextHandoff?.(data.session); },
            })
          : null));
    }
    nodes.push(introEl, barEl, legend);
    if (data.anchor_tokens !== null) {
      nodes.push(h("div", { class: "ctx-anchor", dataset: { st: "ctx-anchor" },
        text: t("ctx.anchor", { tokens: formatTokenCount(data.anchor_tokens),
                                 unit: data.anchor_unit }) }));
    }
    if (data.unknown.length > 0) {
      nodes.push(h("div", { class: "ctx-unknown", dataset: { st: "ctx-unknown" },
        text: t("ctx.unknown", {
          items: data.unknown.map((u) => u.label).join("、") }) }));
    }
    // 精化（2026-09-23）：最基础说明（用户复核：是什么/有什么用/推荐查看）
    nodes.push(h("details", { class: "ctx-help", dataset: { st: "ctx-help" } },
      h("summary", { text: t("ctx.help.summary") }),
      h("ul", { class: "ctx-help-list" },
        h("li", { text: t("ctx.help.what") }),
        h("li", { text: t("ctx.help.use") }),
        h("li", { text: t("ctx.help.when") }))));
    // A 期（2026-09-22）：携带来源开关（会话级持久——改一次生效到再改）
    const srcKeys: ("history" | "digest" | "skills" | "prefix")[] =
      data.unit_id !== ""
        ? ["prefix", "history", "digest", "skills"]
        : ["history", "digest", "skills"];
    nodes.push(h("div", { class: "ctx-sources", dataset: { st: "ctx-sources" } },
      h("div", { class: "ctx-sources-head", text: t("ctx.src.title") }),
      ...srcKeys.map((key) => {
        const on = Boolean(data.sources?.[key]);
        return h("button", {
          class: `ctx-src${on ? " on" : ""}`,
          dataset: { st: `ctx-src:${key}` },
          attrs: { type: "button", title: t(`ctx.src.${key}`),
                   "aria-pressed": on ? "true" : "false" },
          text: t(`ctx.src.${key}`),
          onClick: () => {
            const target = data.unit_id !== ""
              ? { unit: data.unit_id }
              : { session: data.session };
            props.onContextSources?.(target, { [key]: !on });
          },
        });
      })));
    nodes.push(h("div", { class: "ctx-hint", text: t("ctx.cacheHint") }));
    const out: HTMLElement[] = [h("section", { class: "ctx-panel",
      dataset: { st: "ctx-panel" } }, ...nodes)];
    // 轮次明细（碎片投影只读——B 期裁剪仅主会话）
    const rounds = deriveContextRounds(data);
    if (rounds.length > 0) {
      out.push(h("div", { class: "ctx-rounds", dataset: { st: "ctx-rounds" } },
        ...rounds.map((r) => {
          const acts = ctxEditActions(r.status);
          return h("div", {
            class: `ctx-round ${r.status}`,
            dataset: { st: `ctx-round:${r.round}` },
          },
            h("span", { class: "ctx-round-no",
              text: t("ctx.round", { n: String(r.round) }) }),
            h("span", { class: "ctx-round-sum", text: r.summary }),
            h("span", { class: "ctx-round-meta",
              text: `${r.chars} · ~${formatTokenCount(r.est_tokens)}` }),
            h("span", { class: "ctx-round-status",
              text: t(`ctx.status.${r.status}`) }),
            data.unit_id === "" && (acts.omit || acts.restore)
              ? h("span", { class: "ctx-round-acts" },
                  acts.omit
                    ? h("button", {
                        class: "st-btn ghost",
                        attrs: { type: "button",
                                 "data-st": `ctx-omit:${r.round}` },
                        text: t("ctx.omit"),
                        onClick: () => {
                          props.onContextOmit?.(data.session, r.round);
                        },
                      })
                    : null,
                  acts.omit
                    ? h("button", {
                        class: "st-btn ghost",
                        attrs: { type: "button",
                                 "data-st": `ctx-replace:${r.round}` },
                        text: t("ctx.replace"),
                        onClick: () => {
                          props.onContextReplace?.(data.session, r.round);
                        },
                      })
                    : null,
                  acts.restore
                    ? h("button", {
                        class: "st-btn ghost",
                        attrs: { type: "button",
                                 "data-st": `ctx-restore:${r.round}` },
                        text: t("ctx.restore"),
                        onClick: () => {
                          props.onContextRestore?.(data.session, r.round);
                        },
                      })
                    : null)
              : null);
        })));
    }
    // 碎片会话区（B 期只读——% 为各自投影）
    if (props.data.contextUnits.length > 0) {
      out.push(h("div", { class: "ctx-units" },
        h("div", { class: "ctx-units-head", text: t("ctx.units") }),
        ...props.data.contextUnits.map((u) => h("div", {
          class: "ctx-unit",
          dataset: { st: `ctx-unit:${u.unitId}` },
          attrs: { role: "button", tabindex: "0" },
          onClick: () => { props.onContextUnit?.(u.unitId); },
        },
          h("span", { class: "ctx-unit-id", text: u.unitId }),
          h("span", { class: "ctx-unit-meta", text: String(u.rounds) }),
          h("span", { class: "ctx-unit-pct",
            text: formatContextPercent(u.percent) })))));
    }
    // A3：预算行（0=关闭；设置入口；超限裁剪提示）
    const srcTarget = data.unit_id !== ""
      ? { unit: data.unit_id }
      : { session: data.session };
    const budget = data.budget_tokens ?? 0;
    const trimNote = (data.trimmed ?? []).length > 0
      ? t("ctx.budget.trimmed", {
          items: (data.trimmed ?? []).map((x) => `${x.key} ${x.chars}`).join(" · "),
        })
      : "";
    out.push(h("div", { class: "ctx-budget", dataset: { st: "ctx-budget" } },
      h("span", { class: "ctx-budget-label", text: t("ctx.budget.label") }),
      h("span", {
        class: "ctx-budget-value", dataset: { st: "ctx-budget-value" },
        text: budget > 0
          ? `~${formatTokenCount(budget)}`
            + (data.budget_auto ? t("ctx.budget.autoSuffix") : "")
          : t("ctx.budget.off"),
      }),
      h("button", {
        class: "st-btn ghost",
        attrs: { type: "button", "data-st": "ctx-budget-set" },
        text: t("ctx.budget.set"),
        onClick: () => { props.onContextBudget?.(srcTarget, budget); },
      }),
      trimNote === "" ? null
        : h("span", { class: "ctx-budget-trimmed",
                      dataset: { st: "ctx-budget-trimmed" }, text: trimNote })));
    // A2：碎片消息明细（三键可操作）
    if (data.messages.length > 0) {
      out.push(h("div", { class: "ctx-msgs", dataset: { st: "ctx-msgs" } },
        h("div", { class: "ctx-msgs-head", text: t("ctx.msg.title") }),
        ...data.messages.map((m) => h("div", {
          class: `ctx-msg${m.omitted ? " omitted" : ""}`
            + `${m.replaced ? " replaced" : ""}`,
          dataset: { st: `ctx-msg:${m.index}` },
        },
          h("span", { class: "ctx-msg-idx", text: String(m.index) }),
          h("span", { class: "ctx-msg-role", text: m.role }),
          h("span", { class: "ctx-msg-text", text: m.text.slice(0, 48),
                      attrs: { title: m.text } }),
          m.omitted
            ? h("span", { class: "ctx-msg-status", text: t("ctx.msg.omitted") })
            : m.replaced
              ? h("span", { class: "ctx-msg-status", text: t("ctx.msg.replaced") })
              : null,
          h("span", { class: "ctx-msg-acts" },
            h("button", {
              class: "st-btn ghost",
              attrs: { type: "button", "data-st": `ctx-msg-omit:${m.index}` },
              text: t("ctx.omit"),
              onClick: () => {
                props.onContextUnitEdit?.(data.unit_id,
                  { index: m.index, fp_in: m.fp_in, fp_out: m.fp_out, op: "omit" });
              },
            }),
            h("button", {
              class: "st-btn ghost",
              attrs: { type: "button", "data-st": `ctx-msg-replace:${m.index}` },
              text: t("ctx.replace"),
              onClick: () => {
                props.onContextUnitEdit?.(data.unit_id,
                  { index: m.index, fp_in: m.fp_in, fp_out: m.fp_out,
                    op: "replace", text: m.text });
              },
            }),
            m.omitted || m.replaced
              ? h("button", {
                  class: "st-btn ghost",
                  attrs: { type: "button",
                           "data-st": `ctx-msg-restore:${m.index}` },
                  text: t("ctx.msg.restore"),
                  onClick: () => {
                    props.onContextUnitEdit?.(data.unit_id,
                      { index: m.index, fp_in: m.fp_in, fp_out: m.fp_out,
                        op: "restore" });
                  },
                })
              : null)))));
    }
    return out;
  }

  function taskRowNode(row: TaskViewRow): HTMLElement {
    return h("div", { class: "dock-item" },
      h("div", { class: "dock-item-line" },
        h("span", { class: `dock-dot ${row.dot}` }),
        h("span", { class: "dock-item-main", text: row.text || "—" })),
      h("div", { class: "dock-item-meta", text: row.meta }),
      ...(row.error === "" ? [] : [h("div", { class: "dock-item-meta bad", text: row.error })]));
  }

  function noticeRowNode(row: NoticeViewRow): HTMLElement {
    const dot = row.level === "warn" ? "warn" : row.level === "ok" ? "ok" : "";
    const marker = row.seal === ""
      ? h("span", { class: `dock-dot ${dot}` })
      : h("span", { class: "seal-stamp", attrs: { "aria-hidden": "true" }, text: row.seal });
    return h("div", { class: "dock-item" },
      h("div", { class: "dock-item-line" },
        marker,
        h("span", { class: "dock-item-main", text: row.title })),
      ...(row.meta === "" ? [] : [h("div", { class: "dock-item-meta", text: row.meta })]));
  }

  function traceRowNode(row: TraceViewRow): HTMLElement {
    return h("div", { class: "dock-trace-row" },
      h("span", { text: row.time }),
      h("span", { class: "ev", text: row.event }),
      h("span", { text: row.unit }),
      ...(row.detail === "" ? [] : [h("span", { text: row.detail })]));
  }

  /** 技能安装面板（两步确认；输入值存于组件态——重渲染不丢失；错误行内可见）。 */
  function skillInstallPanel(): HTMLElement {
    const nameInput = h("input", {
      class: "st-input",
      attrs: { "data-st": "sk-name", id: "sk-name", name: "skill-name", placeholder: t("dock.skills.name"), spellcheck: "false", value: skillDraft.name },
      oninput: (ev: Event) => { skillDraft.name = (ev.target as HTMLInputElement).value; },
    });
    const descInput = h("input", {
      class: "st-input",
      attrs: { "data-st": "sk-desc", id: "sk-desc", name: "skill-desc", placeholder: t("dock.skills.desc"), spellcheck: "false", value: skillDraft.desc },
      oninput: (ev: Event) => { skillDraft.desc = (ev.target as HTMLInputElement).value; },
    });
    const contentArea = h("textarea", {
      class: "st-input",
      attrs: { "data-st": "sk-content", id: "sk-content", name: "skill-content", placeholder: t("dock.skills.contentHint"), spellcheck: "false" },
      text: skillDraft.content,
      oninput: (ev: Event) => { skillDraft.content = (ev.target as HTMLTextAreaElement).value; },
    });
    const actions = skillInstallConfirm
      ? [
        h("button", {
          class: "st-btn", attrs: { type: "button", "data-st": "sk-save-ok" },
          text: t("dock.skills.confirmInstall"),
          onClick: () => {
            skillInstallConfirm = false;
            props.onSkillInstall(skillDraft.name.trim(), skillDraft.desc.trim(), skillDraft.content);
          },
        }),
        h("button", {
          class: "st-btn ghost", attrs: { type: "button", "data-st": "sk-save-cancel" },
          text: t("dock.skills.cancel"),
          onClick: () => { skillInstallConfirm = false; paint(); },
        }),
      ]
      : [h("button", {
        class: "st-btn", attrs: { type: "button", "data-st": "sk-save" },
        text: t("dock.skills.save"),
        onClick: () => {
          // A9（v43-⑦）：提交前与 install_skill 同规预校验（errors 拦截；warnings 提示不拦截）
          const check = validateSkillDraft(skillDraft.name.trim(), skillDraft.content);
          if (check.errors.length > 0) {
            skillFormError = check.errors.join("；");
            skillFormWarn = "";
            paint();
            return;
          }
          skillFormError = "";
          skillFormWarn = check.warnings.join("；");
          skillInstallConfirm = true;
          paint();
        },
      })];
    return h("div", { class: "dock-sec" },
      h("div", { class: "dock-sec-head", text: t("dock.skills.install") }),
      nameInput, descInput, contentArea,
      ...(skillFormError === ""
        ? []
        : [h("div", { class: "dock-error-msg", attrs: { "data-st": "sk-error" }, text: skillFormError })]),
      ...(skillFormWarn === ""
        ? []
        : [h("div", { class: "dock-item-meta", attrs: { "data-st": "sk-warn" }, text: skillFormWarn })]),
      h("div", { class: "dock-row-actions" }, ...actions));
  }

  /** 技能发现面板（只读结果；busy 期间按钮禁用）。 */
  function skillDiscoverPanel(): HTMLElement {
    const goalInput = h("input", {
      class: "st-input",
      attrs: { "data-st": "sk-goal", id: "sk-goal", name: "skill-goal", placeholder: t("dock.skills.discoverGoal"), spellcheck: "false", value: discoverGoal },
      oninput: (ev: Event) => { discoverGoal = (ev.target as HTMLInputElement).value; },
    });
    const run = h("button", {
      class: "st-btn",
      attrs: {
        type: "button", "data-st": "sk-discover-run",
        ...(props.skillBusy ? { disabled: "disabled" } : {}),
      },
      text: t(props.skillBusy ? "dock.skills.discovering" : "dock.skills.discoverRun"),
      onClick: () => {
        const goal = discoverGoal.trim();
        if (goal === "") {
          skillFormError = t("dock.skills.needGoal");
          paint();
          return;
        }
        skillFormError = "";
        props.onSkillDiscover(goal);
      },
    });
    const out: HTMLElement[] = [
      h("div", { class: "dock-sec-head", text: t("dock.skills.discover") }),
      h("div", { class: "dock-row-actions" }, goalInput, run),
    ];
    if (skillFormError !== "") {
      out.push(h("div", { class: "dock-error-msg", attrs: { "data-st": "sk-error" }, text: skillFormError }));
    }
    const result = props.data.discover;
    if (result !== null) {
      if (!result.ok) {
        out.push(h("div", { class: "dock-error-msg", text: t("dock.skills.discoverFailed", { msg: result.error }) }));
      } else if (result.items.length === 0) {
        out.push(h("div", { class: "dock-empty", text: t("dock.skills.discoverEmpty") }));
      } else {
        out.push(...deriveDiscoverRows(result.items).map((row) =>
          h("div", { class: "dock-item", attrs: { "data-st": `sk-found:${row.name}` } },
            h("div", { class: "dock-item-main", text: row.name }),
            ...(row.detail === "" ? [] : [h("div", { class: "dock-item-meta", text: row.detail })]))));
      }
    }
    return h("div", { class: "dock-sec" }, ...out);
  }

  /** 技能详情（正文 + 内置只读 / 两步确认卸载）。 */
  function skillDetailNode(detail: SkillDetailDto): HTMLElement {
    const tools = skillToolsRows(detail);
    const out: HTMLElement[] = [
      h("div", { class: "dock-sec-head" },
        h("span", { text: detail.name }),
        ...(detail.builtin
          ? [h("span", { class: "dock-badge", text: t("dock.skills.builtin") })]
          : [])),
      ...(tools.tools !== ""
        ? [h("div", { class: "dock-item-meta",
                     attrs: { "data-st": "sk-tools" },
                     text: t("dock.skills.tools") + "：" + tools.tools })]
        : []),
      ...(tools.missing !== ""
        ? [h("div", { class: "dock-item-meta bad",
                     attrs: { "data-st": "sk-tools-warn" },
                     text: t("dock.skills.toolsMissing", { tools: tools.missing }) })]
        : []),
      h("pre", { class: "dock-pre", attrs: { "data-st": "sk-content-view" }, text: detail.content }),
    ];
    if (!detail.builtin) {
      out.push(h("div", { class: "dock-row-actions" },
        skillRemoveConfirm
          ? h("button", {
            class: "st-btn danger", attrs: { type: "button", "data-st": "sk-remove-ok" },
            text: t("dock.skills.removeOk"),
            onClick: () => { skillRemoveConfirm = false; props.onSkillRemove(detail.name); },
          })
          : h("button", {
            class: "st-btn ghost", attrs: { type: "button", "data-st": "sk-remove" },
            text: t("dock.skills.remove"),
            onClick: () => { skillRemoveConfirm = true; paint(); },
          })));
    }
    return h("div", { class: "dock-sec", attrs: { "data-st": "sk-detail" } }, ...out);
  }

  /** A6（W1-1/W1-4）：产物预览面板——标题/元信息/内容区 + 复制/本地打开动作。 */
  function artifactPreviewPanel(pv: ArtifactPreviewView): HTMLElement {
    const row = props.data.artifacts.find((a) => a.path === pv.path);
    const content: HTMLElement[] = [];
    if (pv.error !== "") {
      content.push(h("div", { class: "dock-item-meta bad",
        attrs: { "data-st": "art-error" }, text: pv.error }));
    } else if (pv.mode === "binary") {
      content.push(h("div", { class: "dock-item-meta",
        attrs: { "data-st": "art-binary" }, text: t("dock.art.binary") }));
    } else if (pv.mode === "markdown") {
      const md = h("div", { class: "art-preview-md", attrs: { "data-st": "art-content" } });
      md.appendChild(renderMarkdown(pv.text));
      content.push(md);
    } else {
      content.push(h("pre", { class: "art-preview-text",
        attrs: { "data-st": "art-content" }, text: pv.text }));
    }
    if (pv.truncated) {
      content.push(h("div", { class: "dock-item-meta",
        attrs: { "data-st": "art-truncated" }, text: t("dock.art.truncated") }));
    }
    if (pv.notice !== "") {
      content.push(h("div", { class: "dock-notice",
        attrs: { "data-st": "art-notice" }, text: pv.notice }));
    }
    return h("div", { class: "dock-sec", attrs: { "data-st": "artifact-preview" } },
      h("div", { class: "dock-item-line" },
        h("span", { class: "dock-item-main", text: pv.path }),
        h("button", {
          class: "st-mini",
          attrs: { type: "button", "data-st": "art-close" },
          text: t("dock.art.close"),
          onClick: () => { props.onCloseArtifactPreview?.(); },
        })),
      h("div", { class: "dock-item-meta",
        text: artifactMeta({ kind: row?.kind ?? "", mtime: row?.mtime ?? 0 }) }),
      h("div", { class: "dock-item-actions" },
        h("button", {
          class: "st-btn ghost",
          attrs: { type: "button", "data-st": "art-copy" },
          text: t("dock.art.copy"),
          onClick: () => { props.onCopyArtifactPath?.(pv.path); },
        }),
        h("button", {
          class: "st-btn ghost",
          attrs: { type: "button", "data-st": "art-open" },
          text: t("dock.art.open"),
          onClick: () => { props.onOpenArtifactLocal?.(pv.path); },
        })),
      ...content);
  }

  function body(): HTMLElement[] {
    if (props.view === "artifacts") {
      return withState("artifacts", () => {
        const out: HTMLElement[] = [];
        if (props.data.artifactPreview !== null) {
          out.push(artifactPreviewPanel(props.data.artifactPreview));
        }
        if (props.data.artifacts.length === 0) {
          out.push(emptyState("artifacts"));
        } else {
          out.push(...props.data.artifacts.map((a) =>
            h("button", {
              class: "dock-item dock-report",
              attrs: { type: "button", "data-st": `art-row:${a.path}` },
              onClick: () => { props.onPreviewArtifact?.(a.path); },
            },
              h("div", { class: "dock-item-main", text: a.path }),
              h("div", { class: "dock-item-meta", text: artifactMeta(a) }))));
        }
        return out;
      });
    }
    if (props.view === "skills") {
      return withState("skills", () => {
        const out: HTMLElement[] = [];
        out.push(h("div", { class: "dock-tools" },
          h("button", {
            class: "st-btn ghost", attrs: { type: "button", "data-st": "sk-install" },
            text: t("dock.skills.install"),
            onClick: () => { props.onSkillPanel(props.skillPanel === "install" ? null : "install"); },
          }),
          h("button", {
            class: "st-btn ghost", attrs: { type: "button", "data-st": "sk-discover" },
            text: t("dock.skills.discover"),
            onClick: () => { props.onSkillPanel(props.skillPanel === "discover" ? null : "discover"); },
          })));
        if (props.data.skillNotice !== "") {
          out.push(h("div", { class: "dock-notice", attrs: { "data-st": "sk-notice" }, text: props.data.skillNotice }));
        }
        if (props.skillPanel === "install") out.push(skillInstallPanel());
        else if (props.skillPanel === "discover") out.push(skillDiscoverPanel());
        if (props.data.skills.length === 0) {
          out.push(emptyState("skills"));
        } else {
          out.push(...props.data.skills.map((s) =>
            h("div", {
              class: s.enabled ? "dock-item dock-clickable" : "dock-item dock-clickable off",
              dataset: { st: `skill:${s.name}` },
              onClick: () => { skillRemoveConfirm = false; props.onSkillOpen(s.name); },
            },
              h("div", { class: "dock-item-main", text: s.name }),
              h("div", { class: "dock-item-meta", text: `${s.level} · ${s.description}` }),
              h("button", {
                class: "st-mini",
                attrs: { type: "button", "data-st": `skill-toggle:${s.name}` },
                text: s.enabled ? t("dock.skills.disable") : t("dock.skills.enable"),
                onClick: (ev: Event) => {
                  ev.stopPropagation();
                  props.onSkillToggle(s.name, !s.enabled);
                },
              }))));
        }
        const detail = props.data.skillDetail;
        out.push(detail === null
          ? h("div", { class: "dock-empty", text: t("dock.skills.pickHint") })
          : skillDetailNode(detail));
        return out;
      });
    }
    if (props.view === "sessions") {
      return withState("sessions", () => [
        ...contextPanel(),
        ...(props.data.sessions.length === 0
          ? [emptyState("sessions")]
          : props.data.sessions.map((s) => {
            const row = props.data.contextRows.find((c) => c.name === s.name);
            return h("div", {
              class: "dock-item ctx-session-row",
              dataset: { st: `ctx-session:${s.name}` },
              onClick: () => { props.onContextSelect?.(s.name); },
            },
              h("div", { class: "dock-item-main", attrs: { title: s.name } },
                h("span", { class: "ctx-row-name", text: s.title }),
                h("span", {
                  class: "ctx-row-pct",
                  dataset: { st: `ctx-row:${s.name}` },
                  text: formatContextPercent(row?.percent ?? null),
                })),
              h("div", { class: "dock-item-meta", text: s.detail }),
              h("div", { class: "dock-item-actions" },
                h("button", {
                  class: "st-btn ghost",
                  attrs: { type: "button", "data-st": `sess-rename:${s.name}` },
                  text: t("dock.renameSession"),
                  onClick: (ev: Event) => {
                    ev.stopPropagation();
                    props.onRenameSession(s.name);
                  },
                }),
                h("button", {
                  class: "st-btn ghost",
                  attrs: { type: "button", "data-st": `sess-export:${s.name}` },
                  text: t("dock.exportSession"),
                  onClick: (ev: Event) => {
                    ev.stopPropagation();
                    props.onExportSession(s.name);
                  },
                })));
          })),
      ]);
    }
    if (props.view === "recycle") {
      return withState("recycle", () =>
        props.data.recycle.length === 0
          ? [emptyState("recycle")]
          : props.data.recycle.map((e) =>
            h("div", { class: "dock-item" },
              h("div", { class: "dock-item-main", text: e.name }),
              h("div", { class: "dock-item-meta", text: e.detail }),
              h("div", { class: "dock-item-actions" },
                h("button", {
                  class: "st-btn", attrs: { type: "button", "data-st": `rc-restore:${e.id}` },
                  text: t("dock.restore"),
                  onClick: () => { props.onRestore(e.id); },
                }),
                purgeConfirm === e.id
                  ? h("button", {
                    class: "st-btn danger", attrs: { type: "button", "data-st": `rc-purge-ok:${e.id}` },
                    text: t("dock.purgeConfirm"),
                    onClick: () => { purgeConfirm = null; props.onPurge(e.id); paint(); },
                  })
                  : h("button", {
                    class: "st-btn ghost", attrs: { type: "button", "data-st": `rc-purge:${e.id}` },
                    text: t("dock.purge"),
                    onClick: () => { purgeConfirm = e.id; paint(); },
                  })))));
    }
    if (props.view === "tasks") {
      return withState("tasks", () =>
        props.data.tasks.length === 0
          ? [emptyState("tasks")]
          : props.data.tasks.map(taskRowNode));
    }
    if (props.view === "trajectory") {
      return withState("trajectory", () =>
        props.data.trajectory.length === 0
          ? [h("div", { class: "dock-empty" })]
          : props.data.trajectory.map((row) => h("button", {
              class: "dock-item traj-row",
              attrs: { type: "button", "data-st": `traj:${row.unitId}`, title: row.goal },
              onClick: () => { props.onOpenFragment?.(row.unitId); },
            },
              h("span", { class: "traj-round", text: t("stream.round", { n: String(row.round) }) }),
              h("span", { class: "dom-tag", text: row.domain }),
              h("span", { class: "traj-goal", text: row.goal }),
              row.parallel
                ? h("span", { class: "traj-badge", text: t("trajectory.parallel") })
                : null,
              h("span", {
                class: "traj-meta",
                text: `${row.status} · ${row.duration} · ×${row.toolCalls} · ${row.artifacts}`,
              }))));
    }
    if (props.view === "usage") {
      return withState("usage", () =>
        props.data.usage.length === 0
          ? [emptyState("usage")]
          : props.data.usage.map(sectionNode));
    }
    if (props.view === "provenance") {
      return withState("provenance", () => {
        if (props.data.provenance.length === 0) return [emptyState("provenance")];
        const out: HTMLElement[] = props.data.provenance.map((row) =>
          h("div", {
            class: "dock-unit-row",
            dataset: { st: `prov-unit:${row.unitId}` },
            style: { paddingLeft: `${8 + row.depth * 16}px` },
            onClick: () => { props.onFocusUnit(row.unitId); },
          },
            h("span", { class: `dock-dot ${row.dot}` }),
            h("span", { class: "dock-unit", text: row.unitId }),
            h("span", { class: "dock-item-meta", text: row.detail })));
        if (props.data.traceUnit !== "") {
          out.push(h("div", { class: "dock-trace", dataset: { st: "prov-trace" } },
            h("div", { class: "dock-trace-head", text: `${t("pv.trace.title")} · ${props.data.traceUnit}` }),
            ...(props.data.trace.length === 0
              ? [h("div", { class: "dock-empty", text: t("dock.empty.trace") })]
              : props.data.trace.map(traceRowNode))));
        }
        return out;
      });
    }
    if (props.view === "log") {
      return withState("log", () => [
        h("div", { class: "dock-tools" },
          h("button", {
            class: "st-btn ghost", attrs: { type: "button", "data-st": "log-export" },
            text: t("dock.log.export"),
            onClick: () => { props.onLogExport(); },
          })),
        ...(props.data.log.length === 0
          ? [emptyState("log")]
          : props.data.log.map((row) =>
            h("div", { class: "dock-log-row" },
              h("span", { class: "t", text: row.time }),
              h("span", { class: "ev", text: row.type }),
              h("span", { class: "d", text: row.detail })))),
      ]);
    }
    if (props.view === "notifications") {
      return withState("notifications", () =>
        props.data.notices.length === 0
          ? [emptyState("notifications")]
          : props.data.notices.map(noticeRowNode));
    }
    if (props.view === "brain") {
      return withState("brain", () => {
        const view = props.data.brain;
        if (view.summary.length === 0 && view.recent.length === 0) return [emptyState("brain")];
        return [
          h("div", { class: "dock-sec" },
            h("div", { class: "dock-sec-head", text: view.enabled ? t("brain.enabled") : t("brain.disabled") }),
            ...view.summary.map((row) => kvRow(row.key, row.value))),
          h("div", { class: "dock-sec" },
            h("div", { class: "dock-sec-head", text: t("brain.recent") }),
            ...(view.recent.length === 0
              ? [h("div", { class: "dock-empty", text: t("brain.empty") })]
              : view.recent.map(noticeRowNode))),
        ];
      });
    }
    if (props.view === "mcp") {
      return withState("mcp", () => {
        const out: HTMLElement[] = [];
        out.push(h("div", { class: "dock-tools" },
          h("button", {
            class: "st-btn ghost",
            attrs: {
              type: "button", "data-st": "mcp-reload",
              ...(props.mcpBusy ? { disabled: "disabled" } : {}),
            },
            text: t(props.mcpBusy ? "dock.mcp.reloading" : "dock.mcp.reload"),
            onClick: () => { props.onMcpReload(); },
          })));
        if (props.data.mcpNotice !== "") {
          out.push(h("div", { class: "dock-notice", attrs: { "data-st": "mcp-notice" }, text: props.data.mcpNotice }));
        }
        if (props.data.mcp.length === 0) {
          out.push(emptyState("mcp"));
        } else {
          out.push(...props.data.mcp.map((s) =>
            h("div", { class: "dock-item" },
              h("div", { class: "dock-item-main", text: s.name }),
              h("div", { class: "dock-item-meta", text: s.command }),
              ...(s.tools.length === 0
                ? [h("div", { class: "dock-item-meta", text: t("dock.mcp.noTools") })]
                : [h("div", { class: "dock-chips" }, ...s.tools.map((tool) =>
                  h("span", { class: "dock-chip", attrs: { title: tool.permissions }, text: tool.name })))]),
              h("div", { class: "dock-item-meta", text: s.detail }))));
        }
        return out;
      });
    }
    return withState("reports", () =>
      props.data.reports.length === 0
        ? [emptyState("reports")]
        : props.data.reports.map((r) =>
          h("button", {
            class: "dock-item dock-report",
            attrs: { type: "button", "data-st": `report:${r.path}` },
            onClick: () => { props.onOpenReport(r.path); },
          },
            h("div", { class: "dock-item-main", text: r.name }),
            h("div", { class: "dock-item-meta", text: r.detail }))));
  }

  function inner(): HTMLElement[] {
    const enabled = props.enabled.filter((id) => isDockViewId(id));
    if (collapsed) {
      return [
        h("div", { class: "dock-rail" },
          h("button", {
            class: "dock-tool",
            attrs: { type: "button", "data-st": "dock-expand", title: t("dock.expand") },
            onClick: () => { toggle(); },
          }, h("span", { class: "rot180" }, svgIcon(ICON_CHEVRON))),
          ...enabled.map((id) =>
            h("button", {
              class: props.view === id ? "dock-tool on" : "dock-tool",
              attrs: { type: "button", "data-st": `dock-tool:${id}`, title: t(VIEW_KEYS[id]) },
              onClick: () => {
                if (collapsed) {
                  toggle();
                }
                props.onSelect(id);
              },
            }, svgIcon(VIEW_ICONS[id] ?? ICON_TASK)))),
      ];
    }
    return [
      h("div", { class: "dock-head" },
        h("div", { class: "dock-title", text: t("dock.title") }),
        h("button", {
          class: "dock-toggle",
          attrs: { type: "button", "data-st": "dock-collapse", title: t("dock.collapse"), "aria-label": t("dock.collapse") },
          onClick: () => { toggle(); },
        }, svgIcon(ICON_CHEVRON))),
      h("div", { class: "dock-tabs" }, ...enabled.map((id) =>
        h("button", {
          class: props.view === id ? "dock-tab on" : "dock-tab",
          attrs: { type: "button", "data-st": `dock-tab:${id}` },
          text: t(VIEW_KEYS[id]),
          onClick: () => { props.onSelect(id); },
        }))),
      h("div", { class: "dock-body" }, ...body()),
    ];
  }

  function paint(): void {
    mount(root, ...inner());
  }

  /** 收起/展开（与左栏同款时序）。 */
  function toggle(): void {
    if (animating) return;
    animating = true;
    if (!collapsed) {
      root.classList.add("dock-fading");
      setTimeout(() => {
        collapsed = true;
        saveCollapsed(true);
        root.classList.remove("dock-fading");
        root.classList.add("collapsed");
        paint();
        root.classList.add("dock-in");
        animating = false;
        setTimeout(() => { root.classList.remove("dock-in"); }, DOCK_IN_CLEANUP_MS);
      }, MOTION_CONTENT_MS);
      return;
    }
    collapsed = false;
    saveCollapsed(false);
    root.classList.remove("collapsed");
    paint();
    root.classList.add("dock-wide-in");
    animating = false;
    setTimeout(() => { root.classList.remove("dock-wide-in"); }, DOCK_WIDE_CLEANUP_MS);
  }

  root.classList.toggle("collapsed", collapsed);
  paint();

  return {
    update(next: DockProps): void {
      props = next;
      if (next.skillPanel !== lastSkillPanel) {
        if (next.skillPanel === null) {
          skillDraft = { name: "", desc: "", content: "" };
          skillInstallConfirm = false;
          skillFormError = "";
          skillFormWarn = "";
          discoverGoal = "";
        }
        lastSkillPanel = next.skillPanel;
      }
      paint();
    },
    dispose(): void {
      root.remove();
    },
  };
}
