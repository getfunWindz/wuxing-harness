/** dock 控制器（P8 拆分 · F-3 前端）：12 视图状态 + 取数/写操作——自 main.ts 逐字节提取（行为等价）。
 *
 * 依赖注入（main 持有）：runtime / render / host / showError / refreshRailSessions /
 * refreshDockContext / 通知水位回写 / 技能缓存失效回写。
 * 边界：上下文投影状态（dockContext*）与通知/技能链（railNotices/skillList）仍由 main 持有。
 */
import { openPrompt } from "../views/prompt.ts";
import { openReportModal } from "../views/report.ts";
import { t } from "../views/i18n.ts";
import { loadDockViews, onDockViewsChange, type DockViewId } from "../views/dock.ts";
import { readDesktopBridge } from "../platform/capabilities.ts";
import {
  ARTIFACT_PREVIEW_BYTES,
  artifactPreviewMode,
  truncateArtifactText,
  type ArtifactPreviewView,
} from "../views/view-model.ts";
import {
  IDLE_DOCK_STATE, nextDockState,
  deriveBrainRows, deriveEventLogRows, deriveMcpRows, deriveNoticeRows,
  deriveProvenanceRows, deriveRecycleRows, deriveReportRows, deriveSessionRows,
  deriveSkillRows, deriveTaskRows, deriveTraceRows, deriveTrajectoryRows,
  type BrainView, type DockLoadState, type EventLogRow, type McpRow,
  type NoticeViewRow, type ProvenanceRow, type RecycleRow, type ReportViewRow,
  type SessionRow, type SkillRow, type TaskViewRow, type TraceViewRow,
} from "../views/view-model.ts";
import type { SkillDetailDto, SkillDiscoverDto } from "../protocol/generated.ts";
import type { Runtime } from "./boot.ts";

export interface DockCtlDeps {
  readonly runtime: Runtime;
  readonly host: HTMLElement;
  readonly render: () => void;
  readonly showError: (message: string) => void;
  readonly refreshRailSessions: () => Promise<void>;
  readonly refreshDockContext: () => Promise<void>;
  readonly onNotificationsRead: (lastSeq: number) => void;
  readonly onSkillToggled: (name: string, enabled: boolean) => void;
}

export function createDockCtl(deps: DockCtlDeps) {
  const { runtime, host, render, showError, refreshRailSessions,
          refreshDockContext, onNotificationsRead, onSkillToggled } = deps;

let dockView: DockViewId = "artifacts";
let dockViewsEnabled: readonly DockViewId[] = loadDockViews();
let dockSkills: SkillRow[] = [];
let dockMcp: McpRow[] = [];
let dockRecycle: RecycleRow[] = [];
let dockSessions: SessionRow[] = [];

let dockTasks: TaskViewRow[] = [];
let dockTrajectory: import("../views/view-model.ts").TrajectoryRow[] = [];
let dockProvenance: ProvenanceRow[] = [];
let dockTrace: TraceViewRow[] = [];
let dockTraceUnit = "";
let dockLog: EventLogRow[] = [];
let dockNotices: NoticeViewRow[] = [];
let dockBrain: BrainView = deriveBrainRows(null);
let dockReports: ReportViewRow[] = [];
let dockSkillDetail: SkillDetailDto | null = null;
let dockDiscover: SkillDiscoverDto | null = null;
let dockSkillNotice = "";
let dockMcpNotice = "";
let dockSkillPanel: "install" | "discover" | null = null;
let dockSkillBusy = false;
let dockMcpBusy = false;
/** A6（W1）：产物预览面板状态 + 取数代际（快速连点/关闭后丢弃过期结果） */
let dockArtifactPreview: ArtifactPreviewView | null = null;
let artifactPreviewSeq = 0;
const dockLoad: Record<DockViewId, DockLoadState> = {
  artifacts: IDLE_DOCK_STATE, skills: IDLE_DOCK_STATE, mcp: IDLE_DOCK_STATE,
  recycle: IDLE_DOCK_STATE, sessions: IDLE_DOCK_STATE,
  tasks: IDLE_DOCK_STATE, usage: IDLE_DOCK_STATE, provenance: IDLE_DOCK_STATE,
  log: IDLE_DOCK_STATE, notifications: IDLE_DOCK_STATE, brain: IDLE_DOCK_STATE,
  reports: IDLE_DOCK_STATE, trajectory: IDLE_DOCK_STATE,
};

const markDockState = (
  view: DockViewId,
  event: "load" | "ready" | "fail" | "invalidate",
  error = "",
): void => {
  dockLoad[view] = nextDockState(dockLoad[view], event, error);
};

/** 观测视图数据失效（工作区切换/新任务）——下次进入重新取数。 */
const invalidateObserved = (): void => {
  dockTasks = [];
  dockProvenance = [];
  dockTrace = [];
  dockTraceUnit = "";
  dockLog = [];
  dockNotices = [];
  dockBrain = deriveBrainRows(null);
  dockReports = [];
  dockArtifactPreview = null;   // A6：产物预览随观测面失效（防跨工作区串台）
  artifactPreviewSeq += 1;
  for (const view of ["tasks", "provenance", "log", "notifications", "brain", "reports"] as const) {
    markDockState(view, "invalidate");
  }
};

const refreshSessions = async (): Promise<void> => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) {
    dockSessions = [];
    return;
  }
  const payload = await runtime.sessions.list(wsId);
  dockSessions = deriveSessionRows(payload.sessions);
};

const renameSession = (name: string): void => {
  openPrompt(host, {
    title: t("dock.renameSession"),
    value: name.replace(/\.jsonl$/, ""),   // 展示名（无后缀）——用户随意改名
    onOk: async (value) => {
      const wsId = runtime.workspaces.activeId();
      if (wsId === null) throw new Error("无活动工作区");
      await runtime.sessions.rename(wsId, name, value);
      await refreshSessions();
      await refreshRailSessions();
      render();
    },
  });
};

const exportSession = (name: string): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  window.open(runtime.sessions.exportUrl(wsId, name), "_blank");
};

const refreshRecycle = async (): Promise<void> => {
  const payload = await runtime.recycle.list();
  dockRecycle = deriveRecycleRows(payload.entries);
};

const restoreRecycle = (id: string): void => {
  void (async () => {
    try {
      await runtime.recycle.restore(id);
      await runtime.workspaces.refresh();
      // 2026-10-01 壳端复验：会话恢复 → 左栏/会话视图即时可见（否则需手工刷新）
      await refreshRailSessions();
      await refreshSessions();
      await refreshRecycle();
    } catch (err) {
      showError(`恢复失败：${err instanceof Error ? err.message : String(err)}`);
    }
    render();
  })();
};

const purgeRecycle = (id: string): void => {
  void (async () => {
    try {
      await runtime.recycle.purge(id);
      await refreshRecycle();
    } catch (err) {
      showError(`彻底删除失败：${err instanceof Error ? err.message : String(err)}`);
    }
    render();
  })();
};

/** 观测视图取数（三态：loading → ready/error；失败不静默——dock 内可重试）。 */
const loadDockView = async (view: DockViewId): Promise<void> => {
  const wsId = runtime.workspaces.activeId();
  const needsWorkspace: readonly DockViewId[] = ["tasks", "provenance", "brain", "reports", "sessions"];
  if (wsId === null && needsWorkspace.includes(view)) {
    markDockState(view, "ready");
    render();
    return;
  }
  markDockState(view, "load");
  render();
  try {
    if (view === "skills") {
      dockSkills = deriveSkillRows((await runtime.observe.skills()).skills);
    } else if (view === "mcp") {
      dockMcp = deriveMcpRows(await runtime.observe.mcpStatus());
    } else if (view === "recycle") {
      await refreshRecycle();
    } else if (view === "sessions") {
      await refreshSessions();
      await refreshDockContext();   // B 期：上下文投影（列表 + 选中详情）
    } else if (view === "tasks") {
      dockTasks = deriveTaskRows((await runtime.observe.taskHistory(wsId ?? "")).history);
    } else if (view === "trajectory") {
      dockTrajectory = deriveTrajectoryRows(
        (await runtime.observe.trajectory(wsId ?? "")).rounds);
    } else if (view === "provenance") {
      dockProvenance = deriveProvenanceRows((await runtime.observe.provenance(wsId ?? "")).rows);
    } else if (view === "log") {
      dockLog = deriveEventLogRows((await runtime.observe.eventLog()).rows);
    } else if (view === "notifications") {
      const payload = await runtime.observe.notifications();
      dockNotices = deriveNoticeRows(payload.items);
      onNotificationsRead(payload.last_seq); // 打开即标读（本地水位·main 回写）
    } else if (view === "brain") {
      dockBrain = deriveBrainRows(await runtime.observe.brain(wsId ?? ""));
    } else if (view === "reports") {
      dockReports = deriveReportRows((await runtime.observe.reports(wsId ?? "")).reports);
    }
    // artifacts/usage：本地派生，无需取数
    markDockState(view, "ready");
  } catch (err) {
    markDockState(view, "fail", err instanceof Error ? err.message : String(err));
  }
  render();
};

const focusUnit = (unitId: string): void => {
  void (async () => {
    if (dockTraceUnit === unitId) {
      dockTraceUnit = "";
      dockTrace = [];
      render();
      return;
    }
    const wsId = runtime.workspaces.activeId();
    if (wsId === null) return;
    dockTraceUnit = unitId;
    dockTrace = [];
    render();
    try {
      dockTrace = deriveTraceRows((await runtime.observe.trace(wsId, unitId)).rows);
    } catch (err) {
      dockTraceUnit = "";
      showError(`链路加载失败：${err instanceof Error ? err.message : String(err)}`);
    }
    render();
  })();
};

const openReport = (path: string): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  const url = `/api/v1/workspaces/${wsId}/artifacts/${encodeURI(path)}`;
  void (async () => {
    try {
      const res = await fetch(url);
      if (!res.ok) throw new Error(String(res.status));
      const text = await res.text();
      const title = path.split(/[\\/]/).pop() ?? path;
      openReportModal(host, title, text, url);
    } catch (err) {
      showError(`报告打开失败：${err instanceof Error ? err.message : String(err)}`);
    }
  })();
};

// ---- A6（W1）：产物预览与动作（结果区升级）----

const artifactUrl = (wsId: string, path: string): string =>
  `/api/v1/workspaces/${wsId}/artifacts/` +
  path.split(/[\\/]/).map(encodeURIComponent).join("/");

const writeClipboard = (text: string): Promise<void> => {
  try {
    return navigator.clipboard.writeText(text);
  } catch (error) {
    return Promise.reject(error);   // 非安全上下文等：clipboard 不可用 → 由调用方显性反馈
  }
};

const setArtifactNotice = (path: string, text: string): void => {
  if (dockArtifactPreview !== null && dockArtifactPreview.path === path) {
    dockArtifactPreview = { ...dockArtifactPreview, notice: text };
    render();
  }
};

const openArtifactPreview = (path: string): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  const mode = artifactPreviewMode(path);
  const seq = ++artifactPreviewSeq;
  void (async () => {
    try {
      const res = await fetch(artifactUrl(wsId, path));
      if (!res.ok) throw new Error(String(res.status));
      let text = "";
      let truncated = false;
      if (mode !== "binary") {
        const clamped = truncateArtifactText(await res.text(), ARTIFACT_PREVIEW_BYTES);
        text = clamped.text;
        truncated = clamped.truncated;
      }
      if (seq !== artifactPreviewSeq) return;   // 已关闭/已切换 → 丢弃过期结果
      dockArtifactPreview = { path, mode, text, truncated, error: "", notice: "" };
    } catch (err) {
      if (seq !== artifactPreviewSeq) return;
      dockArtifactPreview = {
        path, mode, text: "", truncated: false,
        error: `${t("dock.art.loadFail")}${err instanceof Error ? err.message : String(err)}`,
        notice: "",
      };
    }
    render();
  })();
};

const closeArtifactPreview = (): void => {
  artifactPreviewSeq += 1;
  if (dockArtifactPreview !== null) {
    dockArtifactPreview = null;
    render();
  }
};

const copyArtifactPath = (path: string): void => {
  void writeClipboard(path).then(
    () => { setArtifactNotice(path, t("dock.art.copied")); },
    (err: unknown) => { showError(`${t("dock.art.copyFail")}${String(err)}`); },
  );
};

const openArtifactLocal = (path: string): void => {
  const rel = path.replace(/\\/g, "/");
  // 白名单边界（W1-6）：仅工作区内相对路径——绝对路径（/、盘符）/.. 越界一律拒绝
  if (rel.trim() === "" || rel.startsWith("/") || /^[A-Za-z]:/.test(rel)
      || rel.split("/").includes("..")) {
    showError(t("dock.art.openReject"));
    return;
  }
  const bridge = readDesktopBridge(globalThis);
  if (bridge?.openPath === undefined) {
    // 浏览器承载：诚实降级 → 复制路径 + 提示（W1-6）
    void writeClipboard(path).then(
      () => { setArtifactNotice(path, t("dock.art.webFallback")); },
      () => { showError(t("dock.art.webFallback")); },
    );
    return;
  }
  const wsPath = runtime.workspaces.list().find(
    (w) => w.id === runtime.workspaces.activeId())?.path ?? "";
  if (wsPath === "") return;
  const target = `${wsPath.replace(/[\\/]+$/, "")}/${rel}`;
  void bridge.openPath(target).then(
    (err) => {
      if (err !== "") showError(`${t("dock.art.openFail")}${err}`);
    },
    (error: unknown) => { showError(`${t("dock.art.openFail")}${String(error)}`); },
  );
};

// ---- 技能 / MCP 管理（P2-M5）：写操作经服务层，结果行内可见 ----

const openSkill = (name: string): void => {
  void (async () => {
    try {
      dockSkillDetail = await runtime.observe.skillDetail(name);
      dockSkillPanel = null;
    } catch (err) {
      dockSkillNotice = err instanceof Error ? err.message : String(err);
    }
    render();
  })();
};

const installSkill = (name: string, description: string, content: string): void => {
  void (async () => {
    dockSkillBusy = true;
    render();
    try {
      await runtime.observe.skillInstall(name, description, content);
      dockSkillNotice = t("dock.skills.installed", { name });
      dockSkillPanel = null;
      await loadDockView("skills");
    } catch (err) {
      dockSkillNotice = err instanceof Error ? err.message : String(err);
    } finally {
      dockSkillBusy = false;
    }
    render();
  })();
};

const removeSkill = (name: string): void => {
  void (async () => {
    dockSkillBusy = true;
    render();
    try {
      await runtime.observe.skillRemove(name);
      dockSkillNotice = t("dock.skills.removed", { name });
      dockSkillDetail = null;
      await loadDockView("skills");
    } catch (err) {
      dockSkillNotice = err instanceof Error ? err.message : String(err);
    } finally {
      dockSkillBusy = false;
    }
    render();
  })();
};

/** 技能启停（M7 #5）：停用后选择器不再列出（缓存失效），load_skill 侧拒绝。 */
const toggleSkillEnabled = (name: string, enabled: boolean): void => {
  void (async () => {
    dockSkillBusy = true;
    render();
    try {
      await runtime.observe.skillSetEnabled(name, enabled);
      dockSkillNotice = t(enabled ? "dock.skills.enabled" : "dock.skills.disabled",
                          { name });
      onSkillToggled(name, enabled); // 选择器缓存失效（停用不列/启用重现）
      await loadDockView("skills");
    } catch (err) {
      dockSkillNotice = err instanceof Error ? err.message : String(err);
    } finally {
      dockSkillBusy = false;
    }
    render();
  })();
};

const discoverSkills = (goal: string): void => {
  void (async () => {
    dockSkillBusy = true;
    render();
    try {
      dockDiscover = await runtime.observe.skillDiscover(goal);
    } catch (err) {
      dockDiscover = {
        ok: false, items: [],
        error: err instanceof Error ? err.message : String(err),
      };
    } finally {
      dockSkillBusy = false;
    }
    render();
  })();
};

const reloadMcp = (): void => {
  void (async () => {
    dockMcpBusy = true;
    render();
    try {
      const out = await runtime.observe.mcpReload();
      dockMcpNotice = t("dock.mcp.reloaded", { n: String(out.reloaded) });
      await loadDockView("mcp");
    } catch (err) {
      dockMcpNotice = err instanceof Error ? err.message : String(err);
    } finally {
      dockMcpBusy = false;
    }
    render();
  })();
};

const selectDock = async (id: DockViewId): Promise<void> => {
  dockView = id;
  render();
  if (id === "artifacts" || id === "usage") return; // 本地派生视图（无取数）
  await loadDockView(id);
};

/** 外部入口打开视图（Q4 裁决：禁用视图临时开启并跳转）。 */
const openDockView = (id: DockViewId): void => {
  if (!dockViewsEnabled.includes(id)) {
    dockViewsEnabled = [...dockViewsEnabled, id];
  }
  void selectDock(id);
};



  onDockViewsChange((views: readonly DockViewId[]) => {
    dockViewsEnabled = views;
    if (!views.includes(dockView)) {
      dockView = views[0] ?? "artifacts";
      void loadDockView(dockView);
    }
    render();
  });

  const snapshot = () => ({
    view: dockView, enabled: dockViewsEnabled,
    skills: dockSkills, mcp: dockMcp, recycle: dockRecycle, sessions: dockSessions,
    tasks: dockTasks, trajectory: dockTrajectory, provenance: dockProvenance,
    trace: dockTrace, traceUnit: dockTraceUnit, log: dockLog, notices: dockNotices,
    brain: dockBrain, reports: dockReports,
    artifactPreview: dockArtifactPreview,
    skillDetail: dockSkillDetail, discover: dockDiscover,
    skillNotice: dockSkillNotice, mcpNotice: dockMcpNotice,
    states: dockLoad, skillPanel: dockSkillPanel,
    skillBusy: dockSkillBusy, mcpBusy: dockMcpBusy,
  });
  const currentView = (): DockViewId => dockView;
  const setSkillPanel = (panel: "install" | "discover" | null): void => {
    dockSkillPanel = panel;
  };
  const setSkillNotice = (text: string): void => { dockSkillNotice = text; };

  return {
    snapshot, currentView, setSkillPanel, setSkillNotice,
    loadDockView, refreshSessions, refreshRecycle, renameSession, exportSession,
    restoreRecycle, purgeRecycle, focusUnit, openReport, openSkill, installSkill,
    removeSkill, toggleSkillEnabled, discoverSkills, reloadMcp, selectDock,
    openDockView, invalidateObserved,
    openArtifactPreview, closeArtifactPreview, copyArtifactPath, openArtifactLocal,
  };
}
