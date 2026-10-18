/** 切片页入口：装配运行时 + 视图（settle 后揭示）。 */
import { createRuntime } from "./boot.ts";
import { createDockCtl } from "./dock-ctl.ts";
import { createComposer } from "../components/composer.ts";
import { createDesignCard } from "../components/design-card.ts";
import { createModeBar } from "../components/mode-bar.ts";
import { h } from "../render/dom.ts";
import { createScheduler } from "../render/scheduler.ts";
import { INITIAL_TASK_STATE, taskViewForSession } from "../runtime/services/tasks.ts";
import type { ConfirmItem } from "../runtime/services/tasks.ts";
import { joinModeId, splitModeId } from "../runtime/services/modes.ts";
import { createHero } from "../views/hero.ts";
import { createFloatCard } from "../components/float-card.ts";
import { skillContentBlock, userSelectableSkills } from "../components/skill-picker.ts";
import type { SkillEntry } from "../components/skill-picker.ts";
import { openHelp } from "../views/help.ts";
import { openReportModal } from "../views/report.ts";
import { createRail } from "../views/rail.ts";
import { loadSessionChat } from "../views/session-load.ts";
import { createSingleFlight } from "../views/single-flight.ts";
import { openPrompt } from "../views/prompt.ts";
import { openBranchDialog } from "../views/branch.ts";
import { openMapView } from "../views/map.ts";
import { openCommandArgs } from "../views/command-args.ts";
import { openCommandResult } from "../views/command-result.ts";
import { createTopbar } from "../views/topbar.ts";
import { createSettingsView } from "../views/settings/view.ts";
import { createStream } from "../views/stream.ts";
import { createFragment } from "../views/fragment.ts";
import { deriveChatMessages, deriveArtifactRows, deriveBrainRows, deriveContextRows, deriveContextTarget, deriveDesignTicketRows, deriveNoticeRows, deriveTopbarAttrs, deriveUsageRows, normalizeTopbarVisible, recommendLine, shouldShowOnboard, toggleRecommendText, type NoticeViewRow, type SessionRow, type TopbarAttrId } from "../views/view-model.ts";
import { createDock, type ContextUnitView } from "../views/dock.ts";
import { loadSessionRail } from "../views/session-rail.ts";
import { openSearch, type SearchHandlers } from "../views/search.ts";
import { initPalette, isPaletteOpen, openPalette, type PaletteCommand } from "../views/palette.ts";
import { initConfirmKeys } from "../views/confirm-keys.ts";
import { createConfirmNotify } from "../views/confirm-notify.ts";
import { deriveZeroState } from "../views/zero-state.ts";
import type { SearchRow } from "../views/view-model.ts";
import type { AssemblyPresetListDto, ContextPreviewDto, DesignStateDto, ExtCommandDto, ExtCommandListDto, SessionModeDto } from "../protocol/generated.ts";
import { onLangChange, t } from "../views/i18n.ts";

const hostEl = document.getElementById("app");
if (!hostEl) {
  throw new Error("缺少 #app 容器");
}
const host: HTMLElement = hostEl;

const bootLine = h("div", { class: "app-boot", text: "正在启动…" });
const errorBox = h("div", { class: "app-error", attrs: { hidden: "hidden" } });
const noticeBox = h("div", { class: "app-notice", attrs: { hidden: "hidden" } });
/** 错误气泡（2026-09-19 用户反馈：瞬时悬浮，自动消失——不再常驻顶栏）。 */
const toastBox = h("div", { class: "app-toast bad", attrs: { hidden: "hidden", "data-st": "toast" } });
const topbarHost = h("div", {});
const heroHost = h("div", { class: "app-hero-slot" });
const streamHost = h("div", { class: "app-stream-slot" });
const composerHost = h("div", { class: "app-composer-slot" });
const modeBarHost = h("div", { class: "app-mode-bar-slot" });
const designCardHost = h("div", { class: "app-design-card-slot" });
const fragmentHost = h("div", { class: "app-fragment-slot" });
const railHost = h("div", {});
const dockHost = h("div", {});
const settingsHost = h("div", {});
const floatRoot = h("div", { attrs: { id: "float-root" } });
// 外观复现 A2：旧壳骨架（顶条全宽 44px + 三栏任务台 + 列独立滚动）
const shell = h("div", { class: "app-shell" },
  h("div", { class: "app-topbar" }, topbarHost),
  h("div", { class: "app-body" },
    h("div", { class: "app-rail-slot" }, railHost),
    h("div", { class: "app-center" }, heroHost, streamHost, modeBarHost, designCardHost, composerHost, fragmentHost),
    h("div", { class: "app-dock-slot" }, dockHost)));
host.append(bootLine, errorBox, noticeBox, toastBox, shell, floatRoot, settingsHost);

const scheduler = createScheduler();

let toastTimer: ReturnType<typeof setTimeout> | null = null;

/** 通用气泡：悬浮 + 自动消失（默认 5.5s）——错误 bad 样式（旧 showError 通用化）。 */
function showToast(message: string, bad = false): void {
  toastBox.textContent = message;
  toastBox.className = bad ? "app-toast bad" : "app-toast";
  toastBox.removeAttribute("hidden");
  if (toastTimer !== null) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    toastBox.setAttribute("hidden", "hidden");
  }, 5500);
}

/** 错误提示：悬浮气泡 + 自动消失（默认 5.5s）；启动失败仍用常驻 errorBox。 */
function showError(message: string): void {
  showToast(message, true);
}

let topbar: ReturnType<typeof createTopbar> | null = null;
/** 上下文投影百分比（B 期）：null = 无数据（顶栏「—」不造假） */
let contextPercent: number | null = null;
/** 上下文档位（批 2）：golden/normal/managed；null = 无数据（不显示徽标） */
let contextBand: string | null = null;
// A3 E2E 暴露（2026-09-20）：boot 期 render/onStatus 可能早于 start 完成——
// 服务未注册时不得触碰（启动门闩；初始 props 仍为静态安全值）。
let appStarted = false;
// 停机门闩（2026-09-20）：beforeunload → stop() 注销服务后，残留调度回调不得再触碰服务。
let appStopping = false;

/* ---------- T-6：首用引导记账（客户端一次；浏览器/Electron 各自记——登记） ---------- */
const ONBOARD_KEY = "wuxing.onboard.v1";
function onboardIsDone(): boolean {
  try { return localStorage.getItem(ONBOARD_KEY) === "1"; } catch (err) { void err; return true; }
}
let onboardDone = onboardIsDone();
function markOnboardDone(): void {
  onboardDone = true;
  try { localStorage.setItem(ONBOARD_KEY, "1"); } catch (err) { void err; }
}

/* ---------- #2 Phase 1.5：交互偏好（呈现级，两级存档） ---------- */
let interactionPrefs: Record<string, unknown> = {};
let interactionPrefsWs: string | null = null;

async function loadInteractionPrefs(wsId: string | null): Promise<void> {
  try {
    const dto = await runtime.observe.interaction(wsId ?? undefined);
    interactionPrefs = { ...(dto.effective ?? {}) };
    confirmNotify.sync();
  } catch (_err) {
    void _err;   // 呈现级偏好取数失败：保留默认呈现（命令总线已呈现错误；不阻塞）
  }
  render();
}

function onPrefsChange(patch: Record<string, unknown>): void {
  const prev = interactionPrefs;
  interactionPrefs = { ...interactionPrefs, ...patch };
  confirmNotify.sync();
  render();                                   // 立即反馈
  void runtime.observe.interactionSave({ scope: "user", values: patch }).then(
    (dto) => { interactionPrefs = { ...(dto.effective ?? {}) }; confirmNotify.sync(); render(); },
    () => { interactionPrefs = prev; confirmNotify.sync(); render(); },   // 失败回退（错误经总线可见）
  );
}

/* ---------- T-2：确认门挂起通知（系统通知；隐藏态触发） ---------- */
const confirmNotify = createConfirmNotify({
  cards: () => {
    if (!appStarted || appStopping) return [];
    return runtime.tasks.state().pendingConfirms.map((item) => {
      const title = typeof item.view["title"] === "string" ? item.view["title"] : "";
      return { id: item.unit_id, label: (title || item.reason || "").trim() };
    });
  },
  enabled: () => interactionPrefs["confirm_notify"] === true,
});

function topbarProps() {
  const state = runtime.tasks.state();
  return {
    attrs: deriveTopbarAttrs(runtime.workspaces.list(), state,
                             state.result?.metrics, contextPercent,
                             contextBand),
    visible: normalizeTopbarVisible(topbarVisible, window.innerWidth <= 768),
    onToggleAttr: (id: TopbarAttrId) => {
      const set = new Set(topbarVisible);
      if (set.has(id)) set.delete(id); else set.add(id);
      topbarVisible = normalizeTopbarVisible([...set], false);
      saveTopbarVisible();
      render();
    },
    onOpenHelp: () => { openHelp(host); },
  };
}

// ---- 顶栏属性显隐偏好（旧壳同键 wuxing.topbar.v1；窄屏仅前 2） ----
const TOPBAR_KEY = "wuxing.topbar.v1";
let topbarVisible: TopbarAttrId[] = (() => {
  let stored: unknown = null;
  try { stored = JSON.parse(localStorage.getItem(TOPBAR_KEY) || "null"); } catch (err) { void err; stored = null; }
  return normalizeTopbarVisible(stored, window.innerWidth <= 768);
})();

function saveTopbarVisible(): void {
  try { localStorage.setItem(TOPBAR_KEY, JSON.stringify(topbarVisible)); } catch (err) { void err; }
}

const runtime = createRuntime({
  baseUrl: window.location.origin,
  onStatus: (status) => {
    void status; // 连接指示不再展示（旧壳无）：仅触发属性重取/重绘
    scheduler.schedule(() => {
      if (topbar !== null && appStarted && !appStopping) topbar.update(topbarProps());
    });
  },
  onCommandFailure: (event) => {
    scheduler.schedule(() => {
      showError(`${event.name} 失败：${event.error ?? "未知错误"}`);
    });
  },
});

// ---- 界面主题（引擎配置 ui_theme，双写；2026-09-19 用户裁决） ----
function applyUiTheme(value: unknown): void {
  document.documentElement.dataset.theme = value === "plain" ? "plain" : "ink";
}

// ---- 悬浮任务卡显示偏好（设置中心可重开；关闭后全局隐藏） ----
const FLOATCARD_KEY = "wuxing.floatcard.v1";
let floatCardEnabled = (() => {
  try { return localStorage.getItem(FLOATCARD_KEY) !== "0"; } catch (err) { void err; return true; }
})();
const setFloatCardEnabled = (value: boolean): void => {
  floatCardEnabled = value;
  try { localStorage.setItem(FLOATCARD_KEY, value ? "1" : "0"); } catch (err) { void err; }
  render();
};

const settingsView = createSettingsView(settingsHost, {
  settings: runtime.settings,
  maintenance: runtime.observe,
  about: runtime.observe,
  workspaces: {
    list: () => runtime.workspaces.list(),
    setAutoConfirm: (id: string, autoConfirm: boolean) =>
      runtime.workspaces.setAutoConfirm(id, autoConfirm),
  },
  activeWorkspaceId: () => runtime.workspaces.activeId(),
  assembly: {
    target: () => modeTargetSession(),
    presets: () => {
      const wsId = runtime.workspaces.activeId();
      return wsId === null ? Promise.resolve({ presets: [] })
                           : runtime.presets.list(wsId);
    },
    session: () => {
      const wsId = runtime.workspaces.activeId();
      return wsId === null ? Promise.resolve({ session: "", name: "" })
                           : runtime.presets.session(wsId, modeTargetSession());
    },
    setSession: (name: string) => {
      const wsId = runtime.workspaces.activeId();
      if (wsId === null) return Promise.reject(new Error("无活动工作区"));
      return runtime.presets.setSession(wsId, modeTargetSession(), name);
    },
  },
  floatCardEnabled: () => floatCardEnabled,
  onFloatCardChange: setFloatCardEnabled,
  onUiThemeChange: (theme: string) => { applyUiTheme(theme); },
});

// ---- 顶栏（P2-S11）：状态 + 属性卡 + ＋菜单 ----
const createWorkspace = async (path: string): Promise<void> => {
  const id = await runtime.workspaces.create(path);
  await runtime.tasks.setWorkspace(id);
  render();
};

/** 新建工作区（2026-09-19 用户裁决）：先弹系统资源管理器选文件夹（复用对话框桥）；
    取消/选择失败 → 回退手输对话框（预填上次选择）；**选定后建区失败不再回退弹窗**（2026-09-21 修复）；
    **防重入（2026-09-30 黄金测试修复）**：选择进行中忽略再次点击——
    旧实现在用户连击时会开两个系统对话框（第一个常被窗口挡住 → 再点；
    取消多余对话框时又触发回退弹窗 =「选择无效」体感）。 */
let lastWsDir = "";
const runWorkspaceDirPick = createSingleFlight(async (): Promise<void> => {
  let path = "";
  try {
    const out = await runtime.dialog.pickDirectory();
    path = out.paths[0] ?? "";
  } catch (err) {
    showError(`选择文件夹失败：${err instanceof Error ? err.message : String(err)}`);
  }
  if (path === "") {
    rail.openCreateDialog(lastWsDir);   // 取消/选择失败 → 手输回退（预填）
    return;
  }
  lastWsDir = path;
  try {
    await createWorkspace(path);
  } catch (err) {
    showError(`新建工作区失败：${err instanceof Error ? err.message : String(err)}`);
  }
});
const chooseWorkspaceDir = (): void => {
  void runWorkspaceDirPick();   // 进行中再次调用被忽略（防双击=防多对话框）
};
// 初始 props 不得触碰服务（start 前服务未注册）——render() 在 start 后填充真实数据
topbar = createTopbar(topbarHost, {
  attrs: deriveTopbarAttrs([], INITIAL_TASK_STATE, null),
  visible: topbarVisible,
  onToggleAttr: () => { /* start 前无交互 */ },
  onOpenHelp: () => { /* start 前无交互 */ },
});
let noticeTimer: ReturnType<typeof setTimeout> | null = null;
function notice(text: string): void {
  noticeBox.textContent = text;
  noticeBox.removeAttribute("hidden");
  if (noticeTimer !== null) clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => { noticeBox.setAttribute("hidden", "hidden"); }, 2600);
}

// ---- 通知徽标 / 参考文件（P2-M6） ----
const NOTICE_SEQ_KEY = "wuxing.notices.seq.v1";
const TERMINAL_STATUSES: readonly string[] = [
  "done", "partial", "failed", "cancelled", "error", "needs_design",
];
let noticeWatermark = 0;
try {
  noticeWatermark = Number(localStorage.getItem(NOTICE_SEQ_KEY) ?? "0") || 0;
} catch (err) {
  void err; // 偏好不可用 → 从 0 起
}
let noticeUnread = 0;
let taskRefs: string[] = [];
let taskSkills: string[] = [];
let skillList: SkillEntry[] = [];

/** 技能列表懒加载（首次打开选择器时取——失败静默为空列表）。 */
const openSkills = (): void => {
  if (skillList.length > 0) return;
  void runtime.observe.skills().then((payload) => {
    // E2-1（B5）：停用 + 仅模型技能不进选择器（管理面不受影响）
    skillList = userSelectableSkills(payload.skills)
      .map((s) => ({ name: s.name, description: s.description,
                     model_invocable: s.model_invocable }));
    render();
  }, () => { render(); });
};

const toggleSkill = (name: string): void => {
  taskSkills = taskSkills.includes(name)
    ? taskSkills.filter((x) => x !== name)
    : [...taskSkills, name];
  render();
};

async function work(fn: () => Promise<void>): Promise<void> {
  try {
    await fn();
  } catch (err) {
    showError(err instanceof Error ? err.message : String(err));
  }
  render();
}

async function copyWorkspacePath(id: string): Promise<void> {
  const ws = runtime.workspaces.list().find((w) => w.id === id);
  try {
    await navigator.clipboard.writeText(ws?.path ?? "");
    notice(t("rail.copied"));
  } catch (err) {
    showError(`复制路径失败：${err instanceof Error ? err.message : String(err)}`);
  }
}

const railCallbacks = {
  onSelect: (id: string) => { void selectWorkspace(id); },
  onArchive: (id: string) => { void work(() => runtime.workspaces.archive(id)); },
  onClose: (id: string) => { void work(() => runtime.workspaces.close(id)); },
  onCopyPath: (id: string) => { void copyWorkspacePath(id); },
  onMoveToFolder: (id: string, folder: string) => {
    void work(() => runtime.workspaces.moveToFolder(id, folder));
  },
  onToggleFolder: (id: string, collapsed: boolean) => {
    void work(() => runtime.workspaces.setFolderCollapsed(id, collapsed));
  },
  onNewFolder: () => {
    openPrompt(host, {
      title: t("rail.prompt.newFolder"),
      onOk: (value) => runtime.workspaces.createFolder(value),
    });
  },
  onRenameFolder: (id: string) => {
    const folder = runtime.workspaces.folders().find((f) => f.id === id);
    openPrompt(host, {
      title: t("rail.prompt.renameFolder"),
      value: folder?.name ?? "",
      onOk: (value) => runtime.workspaces.renameFolder(id, value),
    });
  },
  onDeleteFolder: (id: string) => { void work(() => runtime.workspaces.deleteFolder(id)); },
  onNewSession: () => {
    newSession = true;
    activeSession = null;
    contextPercent = null;
    contextBand = null;
    pendingSessionName = null;
    pendingModePicked = false;
    sessionMode = null;
    void refreshDockContext();
    refreshSessionMeta();
    render();
  },
  onOpenFragment: (unitId: string) => { void openFragment(unitId); },
  onPickWorkspaceDir: () => { chooseWorkspaceDir(); },
  onSelectSession: (name: string) => { openSession(name); },
  onArchiveSession: (name: string) => { void archiveSession(name); },
  onDeleteSession: (name: string) => { void deleteSession(name); },
  onRenameSession: (name: string) => { renameSession(name); },
  onExportSession: (name: string) => { exportSession(name); },
  onRecycleOpen: () => {
    // 弹出菜单每次打开重取条目（与右栏视图同源）
    void refreshRecycle().then(() => { render(); }, () => { render(); });
  },
  onNoticesOpen: () => {
    void refreshRailNotices().then(() => { render(); }, () => { render(); });
  },
  onOpenAllNotices: () => { openDockView("notifications"); },
  onRestoreRecycle: (id: string) => { restoreRecycle(id); },
  onPurgeRecycle: (id: string) => { purgeRecycle(id); },
};

// ---- 会话列表（B1：左栏「会话」区；新建会话 = 回到零态起新会话） ----
let newSession = false;
// E3-1/R5（T5）：隔离运行开关（提交时随任务带 isolate_run；默认关）
let isolateRun = false;
let railSessions: SessionRow[] = [];
let activeSession: string | null = null;
/** Wave-2 T3：最近一次会话选择时刻——防陈旧列表快照反清选择。 */
let activeSessionSince = 0;
// 双模式批 1：会话模式（会话级固定——空白可切；变更只影响新会话）
let sessionMode: SessionModeDto | null = null;
/** 循迹设计态（批 3）：null = 非循迹/无态（卡片隐藏） */
let designState: DesignStateDto | null = null;
/** 实施票据（批 4）：工作区级执行清单（卡片展示；失败保留旧数据） */
let implTickets: readonly { id: string; title: string; status: string;
                             claimed_by: string; stale: boolean }[] = [];
/** 新会话模式写入的预生成会话名（仅用户实际点选模式后才随提交使用）。 */
let pendingSessionName: string | null = null;
let pendingModePicked = false;
/** 轮次化（批 3）：当前会话轮→碎片树数据（左栏展示；聚合失败置空） */
let sessionRoundsData: import("../protocol/generated.ts").SessionRoundsDto | null = null;
/** 批 3：碎片会话钻取态（null=不在碎片视图） */
let activeFragment: string | null = null;
let fragmentData: import("../protocol/generated.ts").UnitSessionDto | null = null;
/** 碎片会话后半程（2026-09-22）：碎片视图内提交的 run（实时切片全量口径） */
let activeFragmentRun: string | null = null;
let railNotices: NoticeViewRow[] = [];

async function refreshRailNotices(): Promise<void> {
  try {
    const payload = await runtime.observe.notifications(0, 50);
    railNotices = deriveNoticeRows(payload.items);
  } catch (err) {
    void err; // 通知列表失败不阻断（保留旧数据）
  }
}

async function refreshRailSessions(): Promise<void> {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) { railSessions = []; return; }
  try {
    // 2026-09-27 审查修复：列表立即上屏；LLM 标题后台补齐（不阻塞切换体验）。
    // 旧实现串行等标题才更新——真实服务下切工作区后列表滞后数秒（用户可见）。
    await loadSessionRail({
      list: async () => (await runtime.sessions.list(wsId)).sessions,
      title: async (name) =>
        (await runtime.sessions.title(wsId, name)).title ?? "",
      apply: (rows, startedAt) => {
        railSessions = rows;
        const absent = activeSession !== null
          && !rows.some((row) => row.name === activeSession);
        // Wave-2 T3：列表发起早于选择 → 陈旧快照不得反清选择；装载在途同样不清
        const listPredatesSelection = startedAt < activeSessionSince;
        if (absent && !listPredatesSelection && sessionLoadState !== "loading") {
          activeSession = null;   // 仅"新列表+非在途"才允许清（删除/归档走显式路径）
        }
        render(); // 列表先上屏（不等标题）
      },
      onTitle: (name, title) => {
        railSessions = railSessions.map((row) =>
          row.name === name ? { ...row, title } : row);
        render();
      },
      isStale: () => runtime.workspaces.activeId() !== wsId,
    });
  } catch (err) {
    void err; // 会话列表失败不阻断（保留旧数据）
  }
}

/** 修复②（2026-09-20）：当前会话聊天记录（session rows；随会话切换/终态刷新）。 */
let sessionRows: readonly Record<string, unknown>[] = [];

/** Wave-2 T2：会话装载状态（idle/loading/ready——切换骨架与空会话提示）。 */
let sessionLoadState: "idle" | "loading" | "ready" = "idle";

/** 碎片会话钻取（批 3）：碎片 = 独立会话——中栏正常会话区展示（返回保留主视图状态）。
 *  后半程（2026-09-22）：重新钻取潜清活动绑定 run（实时切片回到按 unit 过滤）。 */
const openFragment = async (unitId: string): Promise<void> => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null || unitId === "") return;
  activeFragment = unitId;
  activeFragmentRun = null;
  fragmentData = null;
  render(); // 先进入视图（数据到达前显示空态）
  await refreshFragmentData();
  refreshContextPercent(); // 碎片视图口径（顶栏跟随 unit）
};
/** 重取碎片会话数据（绑定轮次随终态/新任务刷新；不改变钻取态）。 */
const refreshFragmentData = async (): Promise<void> => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null || activeFragment === null) return;
  try {
    fragmentData = await runtime.sessions.unitSession(wsId, activeFragment);
  } catch (err) {
    void err; // 读取失败保留旧数据（不阻塞视图）
  }
  render();
};
function closeFragment(): void {
  activeFragment = null;
  activeFragmentRun = null;
  fragmentData = null;
  refreshContextPercent();
  render();
}

/** 顶栏 % 刷新（B 期）：跟随当前视图对应会话（碎片视图 → unit；否则 → 活动会话）。
 *  失败/无数据 → null（「—」不造假）。 */
function refreshContextPercent(): void {
  if (!appStarted || appStopping) return;
  const wsId = runtime.workspaces.activeId();
  const target = activeFragment !== null
    ? { unit: activeFragment }
    : activeSession !== null ? { session: activeSession } : null;
  if (wsId === null || target === null) {
    contextPercent = null;
    contextBand = null;
    render();
    return;
  }
  void runtime.context.preview(wsId, target).then(
    (d) => {
      contextPercent = d.available ? d.percent : null;
      contextBand = d.available ? (d.band || null) : null;
      render();
    },
    () => {
      contextPercent = null;   // 读取失败不保留陈旧值（不造假）
      contextBand = null;
      render();
    },
  );
}

/** 当前模式目标会话名（新会话惰性生成；仅模式 GET/PUT 使用——提交未选模式时不带）。 */
function modeTargetSession(): string {
  if (activeSession !== null) return activeSession;
  pendingSessionName ??= `conversation-${Date.now()}.jsonl`;
  return pendingSessionName;
}

/** 会话模式刷新（失败 → null——界面回退默认展示，不造假）。 */
function refreshSessionMode(): void {
  if (!appStarted || appStopping) return;
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) { sessionMode = null; render(); return; }
  void runtime.modes.get(wsId, modeTargetSession()).then(
    (d) => { sessionMode = d; render(); },
    () => { sessionMode = null; render(); },
  );
}

/** 点选模式（服务端机制守卫：非空白 422；壳侧非空白点选先行提示）。 */
const pickMode = (id: string): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  const session = modeTargetSession();
  void runtime.modes.set(wsId, session, splitModeId(id)).then(
    (d) => {
      sessionMode = d;
      if (activeSession === null) pendingModePicked = true;
      render();
    },
    () => { /* 失败已由命令总线全局呈现 */ },
  );
};

/** 循迹设计态刷新（失败 → null——卡片隐藏，不造假）。 */
function refreshDesignState(): void {
  if (!appStarted || appStopping) return;
  const wsId = runtime.workspaces.activeId();
  if (wsId === null || activeSession === null) {
    designState = null;
    render();
    return;
  }
  void runtime.design.get(wsId, activeSession).then(
    (d) => { designState = d.available ? d : null; render(); },
    () => { designState = null; render(); },
  );
}

/** 会话元数据刷新（模式 + 设计态——同触发点：会话/工作区/终态切换）。 */
function refreshSessionMeta(): void {
  refreshSessionMode();
  refreshDesignState();
  refreshImplTickets();
}

/** 实施票据刷新（批 4）：工作区级；失败保留旧数据（不造假）。 */
function refreshImplTickets(): void {
  if (!appStarted || appStopping) return;
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) {
    implTickets = [];
    render();
    return;
  }
  void runtime.design.tickets(wsId).then(
    (d) => {
      implTickets = d.tickets.map((t) => ({ id: t.id, title: t.title,
                                            status: t.status,
                                            claimed_by: typeof t.claimed_by === "string"
                                              ? t.claimed_by : "",
                                            stale: t.stale === true }));
      render();
    },
    () => { /* 读取失败保留旧数据（不阻塞视图） */ },
  );
}

/** 发布票据（批 4）：用户 quiz 动作——失败已由命令总线全局呈现。 */
const publishImplTickets = (): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  void runtime.design.publishTickets(wsId).then(
    (d) => {
      implTickets = d.tickets.map((t) => ({ id: t.id, title: t.title,
                                            status: t.status,
                                            claimed_by: typeof t.claimed_by === "string"
                                              ? t.claimed_by : "",
                                            stale: t.stale === true }));
      render();
    },
    () => { /* 失败已由命令总线全局呈现 */ },
  );
};

/** 「交给执行」：设计态 phase=ready（服务端仅接受该值）+ 就地刷新。 */
const designHandoff = (): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null || activeSession === null) return;
  void runtime.design.handoff(wsId, activeSession).then(
    (d) => { designState = d.available ? d : null; render(); },
    () => { /* 失败已由命令总线全局呈现 */ },
  );
};

/** 复制地图摘要（失败可见——与复制消息同口径）。 */
const copyMapSummary = (text: string): void => {
  void navigator.clipboard.writeText(text).then(
    () => { notice(t("map.copied")); },
    (err: unknown) => {
      showError(`复制失败：${err instanceof Error ? err.message : String(err)}`);
    },
  );
};

/** 地图只读视图（「查看地图」）。 */
const designViewMap = (): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  void runtime.design.map(wsId).then(
    (d) => {
      openMapView(host, d, runtime.design.mapFileUrl(wsId),
                  { onCopy: copyMapSummary });
    },
    (err: unknown) => {
      showError(`地图读取失败：${err instanceof Error ? err.message : String(err)}`);
    },
  );
};

/** 一键「新会话承接」（批 4）：取承接简报 → 零态新会话 + hero 输入区预填（不自动提交）。 */
const contextHandoff = (name: string): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null || name === "") return;
  void runtime.context.handoffBrief(wsId, name).then(
    (d) => {
      if (!d.available || d.brief === "") {
        showError("承接简报不可用（会话记录缺失）");
        return;
      }
      newSession = true;
      activeSession = null;
      contextPercent = null;
      contextBand = null;
      pendingSessionName = null;
      pendingModePicked = false;
      sessionMode = null;
      designState = null;
      void refreshDockContext();
      refreshSessionMeta();
      render();
      hero.setText(d.brief);
    },
    (err: unknown) => {
      showError(`承接简报读取失败：${err instanceof Error ? err.message : String(err)}`);
    },
  );
};

/** 当前会话轮次中的碎片（unit_id 去重 + 轮数）——dock 碎片会话区数据源。 */
function collectContextUnits(): { unitId: string; rounds: number }[] {
  const map = new Map<string, number>();
  for (const r of sessionRoundsData?.rounds ?? []) {
    for (const f of r.fragments ?? []) {
      if (f.unit_id !== "") map.set(f.unit_id, (map.get(f.unit_id) ?? 0) + 1);
    }
  }
  return [...map].map(([unitId, rounds]) => ({ unitId, rounds }));
}

/** dock 会话视图上下文数据（B 期）：列表行 % + 选中会话详情 + 碎片会话 %。 */
const refreshDockContext = async (): Promise<void> => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) {
    dockContext = null;
    dockContextRows = [];
    dockContextUnits = [];
    dockContextFallback = false;
    return;
  }
  try {
    dockContextRows = deriveContextRows(await runtime.context.previews(wsId));
  } catch (err) {
    void err; // 列表失败保留旧数据（失败已命令总线可见）
  }
  const { target, fallback } = deriveContextTarget(
    activeSession, railSessions.map((row) => row.name));
  dockContextFallback = fallback;
  if (target === null) {
    dockContext = null;
    dockContextUnits = [];
    render();
    return;
  }
  try {
    dockContext = await runtime.context.preview(wsId, { session: target });
  } catch (err) {
    void err;
    dockContext = null;
  }
  const units = target === activeSession ? collectContextUnits() : [];
  dockContextUnits = await Promise.all(units.slice(0, 6).map(async (u) => {
    try {
      const d = await runtime.context.preview(wsId, { unit: u.unitId });
      return { unitId: u.unitId, percent: d.available ? d.percent : null,
               rounds: u.rounds };
    } catch (err) {
      void err;
      return { unitId: u.unitId, percent: null, rounds: u.rounds };
    }
  }));
  render();
};

/** 投影层编辑（B 期）：omit/replace——成功后就地刷新（失败已命令总线全局呈现）。 */
const contextEdit = (name: string, round: number,
                     op: "omit" | "replace" | "restore",
                     content = ""): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null || name === "") return;
  const input = op === "replace" ? { round, op, content } : { round, op };
  void runtime.context.edit(wsId, name, input).then(
    (d) => {
      dockContext = d.preview;
      refreshContextPercent();
      void refreshDockContext();
      render();
    },
    () => { /* 失败已经命令总线全局呈现 */ },
  );
};

/** A1：来源开关写入（会话级持久）——成功后就地刷新（失败已命令总线呈现）。 */
const contextSetSources = (
  target: { session?: string; unit?: string },
  values: Record<string, boolean | number>,
): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  void runtime.context.setSources(wsId, target, values).then(
    (d) => {
      dockContext = d.preview;
      refreshContextPercent();
      void refreshDockContext();
      render();
    },
    () => { /* 失败已经命令总线全局呈现 */ },
  );
};

/** A2：碎片消息三键编辑（omit 直接写；replace 先弹输入）。 */
const contextUnitEdit = (
  unit: string,
  edit: { index: number; fp_in: string; fp_out: string;
          op: "omit" | "replace"; text?: string },
): void => {
  const apply = (content: string): void => {
    const wsId = runtime.workspaces.activeId();
    if (wsId === null || unit === "") return;
    void runtime.context.editUnit(wsId, unit, {
      index: edit.index, fp_in: edit.fp_in, fp_out: edit.fp_out,
      op: edit.op, content,
    }).then(
      (d) => {
        dockContext = d.preview;
        render();
      },
      () => { /* 失败已经命令总线全局呈现 */ },
    );
  };
  if (edit.op === "replace") {
    openPrompt(host, {
      title: t("ctx.replace"),
      value: edit.text ?? "",
      onOk: (value) => { apply(value); },
    });
    return;
  }
  apply("");
};

const refreshSessionMessages = async (): Promise<void> => {
  // 2026-09-30 修复：装载带会话身份校验（await 期间切换会话 → 陈旧响应丢弃）；
  // 旧实现在这里无条件回填且 rounds 用写入时刻的 activeSession → 切换竞态丢画面。
  await loadSessionChat({
    current: () => ({ wsId: runtime.workspaces.activeId(), name: activeSession }),
    fetchMessages: (wsId, name) => runtime.sessions.messages(wsId, name),
    fetchRounds: (wsId, name) => runtime.sessions.rounds(wsId, name),
    // Wave-2 T2：先清后填（切换即清旧会话内容，装载态驱动骨架）
    onStart: () => {
      sessionLoadState = "loading";
      sessionRows = [];
      sessionRoundsData = null;
      render();
    },
    onApply: (rows, rounds) => {
      sessionLoadState = "ready";
      sessionRows = rows;
      sessionRoundsData = rounds;
      render();
    },
    onClear: () => {
      sessionLoadState = "idle";
      sessionRows = [];
      sessionRoundsData = null;
      render();
    },
  });
};

/** override（二期批 1）：needs_design 结果卡「仍要执行」→ 原任务重提交 + no_map
 *  （显式放行无地图执行；报告注记由引擎侧写上）。 */
const overrideGate = (): void => {
  const text = runtime.tasks.state().taskText;
  if (text === "") return;
  newSession = false;
  submitTaskText(text, taskRefs, "", "no_map");
};

/** 修复②：复制用户消息（失败可见）。 */
const copyMessage = (text: string): void => {
  void navigator.clipboard.writeText(text).then(
    () => { notice(t("chat.copied")); },
    (err: unknown) => {
      showError(`复制失败：${err instanceof Error ? err.message : String(err)}`);
    },
  );
};

/** 修复②：编辑用户消息——回填输入区（修改后作为新消息发送）。 */
const editMessage = (text: string): void => {
  composer.setText(text);
  notice(t("chat.editLoaded"));   // U13：回填提示——「编辑=作为新消息发送」语义显式化
};

/** G1：从既有轮分支（弹层 → 派生新会话 → 切换 + redo 回填）。 */
const branchFromMessage = (round: number, _text: string): void => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null || activeSession === null) return;
  const source = activeSession;
  openBranchDialog(document.body, {
    round,
    onConfirm: async (req) => {
      const res = await runtime.sessions.branch(wsId, source, req);
      await refreshRailSessions();
      activeSession = res.session;
      activeSessionSince = Date.now();   // Wave-2 T3
      activeFragment = null;
      fragmentData = null;
      activeFragmentRun = null;
      pendingSessionName = null;
      pendingModePicked = false;
      refreshContextPercent();
      refreshSessionMeta();
      void refreshDockContext();
      openDockView("sessions");
      await refreshSessionMessages();
      if (req.mode === "redo" && (res.redo_text ?? "") !== "") {
        composer.setText(res.redo_text ?? "");
        hero.setText(res.redo_text ?? "");
      }
      render();
    },
  });
};

const archiveSession = async (name: string): Promise<void> => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  try {
    await runtime.sessions.archive(wsId, name);
    await refreshRailSessions();
    await refreshSessions();
    if (activeSession === name) { activeSession = null; sessionRows = []; }
  } catch (err) {
    showError(`归档会话失败：${err instanceof Error ? err.message : String(err)}`);
  }
  render();
};

/** M7 C3（DK-11）：删除会话 → 回收站（可恢复；不同于卸载/物理删除）。 */
const deleteSession = async (name: string): Promise<void> => {
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) return;
  try {
    await runtime.sessions.delete(wsId, name);
    await refreshRailSessions();
    await refreshSessions();
    if (activeSession === name) { activeSession = null; sessionRows = []; }
    notice(t("rail.session.deleted"));
  } catch (err) {
    showError(`删除会话失败：${err instanceof Error ? err.message : String(err)}`);
  }
  render();
};

/** M7 C4（DK-12）：事件日志导出 JSON（对齐旧壳 exportEvents）。 */
const exportEvents = (): void => {
  void (async () => {
    try {
      const payload = await runtime.observe.eventLog(2000);
      const blob = new Blob([JSON.stringify(payload.rows, null, 2)],
                            { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      const stamp = new Date().toISOString().slice(0, 10).replace(/-/g, "");
      a.href = url;
      a.download = `events-${stamp}.json`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      showError(`导出事件失败：${err instanceof Error ? err.message : String(err)}`);
    }
  })();
};

const rail = createRail(railHost, {
  ...railCallbacks,
  workspaces: [], folders: [], activeId: null,
  sessions: [], activeSession: null, recycle: [], notices: [],
  noticeUnread: 0,
  onSearch: () => { /* start 前无交互 */ },
  onNotices: () => { /* start 前无交互 */ },
  onOpenSettings: () => { /* start 前无交互 */ },
  onRecycle: () => { /* start 前无交互 */ },
  onCreateWorkspace: async () => { /* start 前无交互 */ },
});

// ---- dock（P2-M4）：12 视图（默认五视图 + 观测自选）+ 三态加载 ----
const dockCtl = createDockCtl({
  runtime, host, render: () => render(), showError,
  refreshRailSessions, refreshDockContext,
  onNotificationsRead: (lastSeq) => {
    noticeWatermark = lastSeq; // 打开即标读（本地水位）
    noticeUnread = 0;
    try {
      localStorage.setItem(NOTICE_SEQ_KEY, String(lastSeq));
    } catch (err) {
      void err; // 持久化失败不阻断
    }
  },
  onSkillToggled: (name, enabled) => {
    skillList = []; // 选择器缓存失效（停用不列/启用重现）
    if (!enabled) taskSkills = taskSkills.filter((x) => x !== name);
  },
});
const { loadDockView, refreshSessions, refreshRecycle, renameSession, exportSession,
        restoreRecycle, purgeRecycle, focusUnit, openReport, openSkill,
        installSkill, removeSkill, toggleSkillEnabled, discoverSkills, reloadMcp,
        selectDock, openDockView, invalidateObserved,
        openArtifactPreview, closeArtifactPreview, copyArtifactPath,
        openArtifactLocal } = dockCtl;

/** 上下文投影（B 期）：选中会话详情 / 列表行 % / 碎片会话 %（main 持有——不随 dock 控制器迁出） */
let dockContext: ContextPreviewDto | null = null;
let dockContextRows: import("../views/view-model.ts").ContextRowView[] = [];
let dockContextUnits: ContextUnitView[] = [];
let dockContextFallback = false;

/** 通知徽标刷新（终态事件后 / 启动时）——代际守卫：标读后到达的旧请求结果丢弃。 */
const refreshNotices = async (): Promise<void> => {
  const since = noticeWatermark;
  try {
    const payload = await runtime.observe.notifications(since);
    if (noticeWatermark !== since) return; // 水位已变（已标读）——丢弃过期结果
    noticeUnread = payload.unread;
    render();
  } catch (err) {
    void err; // 徽标属辅助信息；失败已在命令总线广播
  }
};

/** 打开会话（单一入口）：左栏点击 / 搜索结果共用。
 *  2026-09-27 审查：搜索结果点击旧实现只切工作区+开右栏，**不打开目标会话**
 *  （点了没反应/留在欢迎页）——统一走上此入口。 */
const openSession = (name: string): void => {
  if (name === "") return;
  activeSession = name;
  activeSessionSince = Date.now();   // Wave-2 T3：选择时刻（反清判据）
  newSession = false;          // Wave-2 T1：选择即清除新建意图（Bug#1 双保险；真相由纯函数兜底）
  // 2026-09-21：碎片会话视图下点左栏主会话可正常跳回（原仅工作区返回按钮）
  activeFragment = null;
  fragmentData = null;
  activeFragmentRun = null;
  refreshContextPercent();
  pendingSessionName = null;
  pendingModePicked = false;
  refreshSessionMeta();
  void refreshDockContext();
  openDockView("sessions");
  void refreshSessionMessages(); // 修复②：载入该会话聊天记录
  render();
};

/** 搜索结果点击：切工作区（需时）+ 打开对应视图（旧壳口径）。 */
const pickSearchRow = (row: SearchRow): void => {
  void (async () => {
    if (row.wsId !== "" && runtime.workspaces.activeId() !== row.wsId) {
      await selectWorkspace(row.wsId);
    }
    if (row.kind === "session" && row.title !== "") {
      openSession(row.title); // 搜索到会话 → 直接打开（会话名即 row.title）
    } else {
      openDockView(row.kind === "task" ? "tasks" : "sessions");
    }
  })();
};

const searchHandlers: SearchHandlers = {
  onQuery: (query) => runtime.observe.search(query),
  onPick: pickSearchRow,
};

/** 参考文件（P2-M6）：系统对话框桥 → chips；提交携带 refs。 */
const pickRefs = (): void => {
  void (async () => {
    try {
      const out = await runtime.dialog.pickFiles();
      for (const path of out.paths) {
        if (!taskRefs.includes(path)) taskRefs = [...taskRefs, path];
      }
    } catch (err) {
      showError(`参考文件选择失败：${err instanceof Error ? err.message : String(err)}`);
    }
    render();
  })();
};

const removeRef = (path: string): void => {
  taskRefs = taskRefs.filter((item) => item !== path);
  render();
};

/** 提交通用路径（composer / hero / 碎片视图共用）：技能前缀注入 + 成功后清参考/技能 chips + 观测失效重取。
    unit（碎片会话后半程 2026-09-22）：非空 = 碎片视图内提交（绑定轮次 + 上下文隔离）。 */
const submitTaskText = (text: string, refs: readonly string[], unit = "",
                        override = ""): void => {
  // 修复①（2026-09-20）：会话绑定——新建/无会话时交服务端自动新建
  // 双模式批 1：新会话且已点选模式 → 用预生成会话名（sidecar 已先行写入）；
  // 未点选模式保持空串 → 服务端自动新建（旧行为不变）
  const sessionArg = newSession || activeSession === null
    ? (pendingModePicked && pendingSessionName !== null ? pendingSessionName : "")
    : activeSession;
  newSession = false; // 提交即离开「新建会话」零态
  const baseBody = taskSkills.length > 0
    ? `${t("composer.skillPrefix", { names: taskSkills.join("、") })}\n${text}`
    : text;
  const send = (extra: string): void => {
    markOnboardDone();   // T-6：首次提交任务即完成引导
    const body = extra === "" ? baseBody : `${baseBody}\n\n${extra}`;
    void runtime.tasks.submit(body, refs, sessionArg, unit, override,
                              isolateRun).then((out) => {
      if ((out.session ?? "") !== "") {
        activeSession = out.session;
        activeSessionSince = Date.now();   // Wave-2 T3：提交建会话即选择
      }
      // 碎片内提交：该 run 归属当前碎片视图（实时切片全量）
      if (unit !== "") activeFragmentRun = out.run_id;
      if (refs === taskRefs) taskRefs = []; // 提交成功 → 清空参考 chips
      taskSkills = [];
      pendingSessionName = null;
      pendingModePicked = false;
      refreshSessionMeta(); // 会话名已定 → 模式同步（editable 随轮次落地更新）
      invalidateObserved(); // 新任务 → 观测数据失效重取
      void refreshRailSessions().then(() => { render(); }); // 会话列表即时刷新
      void refreshSessionMessages(); // 修复②：聊天记录（当前轮次由实时气泡承载）
      const dv = dockCtl.currentView();
      if (dv !== "artifacts" && dv !== "usage") {
        void loadDockView(dv);
      }
      render();
    }, () => {
      // 失败已在命令总线广播（onCommandFailure 呈现）——此处仅防未处理拒绝
    });
  };
  // E2-1（J5）：仅用户技能（model_invocable=false）模型不可 load_skill
  // → 由壳取详情、去 frontmatter、随任务文本注入；拉取失败不阻塞提交。
  const userOnly = taskSkills.filter((n) =>
    skillList.find((s) => s.name === n)?.model_invocable === false);
  if (userOnly.length > 0) {
    void Promise.all(userOnly.map((n) => runtime.observe.skillDetail(n))).then(
      (details) => {
        const blocks = details
          .map((d, i) => {
            const name = userOnly[i];
            return d && d.content && name
              ? skillContentBlock(name, d.content) : "";
          })
          .filter((x) => x !== "");
        send(blocks.join("\n\n"));
      },
      () => { send(""); },
    );
  } else {
    send("");
  }
};

/** 碎片视图输入区提交（全量对齐：与主输入区同组件同约束）。 */
const submitFragmentText = (text: string, refs: readonly string[]): void => {
  const unit = activeFragment;
  if (unit === null) return;
  submitTaskText(text, refs, unit);
};

const cancelTask = (): void => {
  void runtime.tasks.cancel().then(() => { render(); }, (err: unknown) => {
    showError(`停止失败：${err instanceof Error ? err.message : String(err)}`);
  });
};

/** 命令面板命令表（P2-M6）：工作区/视图/搜索/设置/恢复动作/新建。 */
const paletteCommands = (): PaletteCommand[] => {
  const out: PaletteCommand[] = [];
  for (const ws of runtime.workspaces.list()) {
    out.push({
      id: `ws-${ws.id}`,
      title: t("palette.switchWs", { name: ws.name }),
      keywords: ws.path,
      run: () => { void selectWorkspace(ws.id); },
    });
  }
  for (const view of dockCtl.snapshot().enabled) {
    out.push({
      id: `view-${view}`,
      title: t("palette.openView", { title: t(`dock.${view}`) }),
      run: () => { openDockView(view); },
    });
  }
  out.push({ id: "search", title: t("palette.search"), keywords: "search", run: () => { openSearch(host, searchHandlers); } });
  out.push({ id: "focus", title: t("palette.focus"), keywords: "focus", run: () => { composer.focus(); } });
  out.push({ id: "settings", title: t("palette.settings"), keywords: "settings", run: () => { void settingsView.open(); } });
  out.push({ id: "resume", title: t("palette.resume"), run: resumeTask });
  out.push({ id: "stop", title: t("palette.stop"), run: cancelTask });
  out.push({
    id: "new-ws", title: t("palette.newWs"),
    run: () => { chooseWorkspaceDir(); },
  });
  out.push({
    id: "show-float", title: t("palette.showFloat"), keywords: "float task card",
    run: () => { setFloatCardEnabled(true); },
  });
  return out;
};

/** E2-UI：执行扩展命令（无参直跑；有参先开逐字段表单——不出现 JSON 裸输入）。 */
const runExtCommand = (wsId: string, cmd: ExtCommandDto): void => {
  const title = cmd.description || cmd.name;
  const doRun = (args: Record<string, unknown>): void => {
    void runtime.extensions.run(wsId, cmd.name, args).then(
      (res) => {
        openCommandResult(host, {
          title, status: res.status, text: res.text, error: res.error,
        });
      },
      () => { /* 失败已由命令总线全局呈现 */ },
    );
  };
  if (cmd.args.length > 0) {
    openCommandArgs(host, { title, schema: cmd.args, onSubmit: doRun });
    return;
  }
  doRun({});
};

/** E2-UI：本会话装配切换（name 空 = 跟随默认；服务端已 reload 引擎——下一任务生效）。 */
const switchSessionPreset = (wsId: string, name: string): void => {
  const session = modeTargetSession();
  void runtime.presets.setSession(wsId, session, name).then(
    () => {
      showToast(name === ""
        ? t("preset.toast.default")
        : t("preset.toast.bound", { name }));
    },
    () => { /* 失败已由命令总线全局呈现 */ },
  );
};

/** E2-UI：扩展命令 + 预设的调色板条目（当前装配标「（当前）」；跟随默认恒在列）。 */
const paletteExtCommands = (
  wsId: string,
  ext: ExtCommandListDto | null,
  presets: AssemblyPresetListDto | null,
  currentPreset: string,
): PaletteCommand[] => {
  const out: PaletteCommand[] = [];
  for (const cmd of ext?.commands ?? []) {
    out.push({
      id: `ext-${cmd.name}`,
      title: t("palette.ext", { name: cmd.description || cmd.name }),
      keywords: `extension ${cmd.name} ${cmd.source}`,
      run: () => { runExtCommand(wsId, cmd); },
    });
  }
  for (const p of presets?.presets ?? []) {
    const on = p.name === currentPreset;
    out.push({
      id: `preset-${p.name}`,
      title: on
        ? t("palette.preset.current", { name: p.name })
        : t("palette.preset", { name: p.name }),
      keywords: `preset assembly ${p.name}`,
      run: () => { switchSessionPreset(wsId, p.name); },
    });
  }
  if ((presets?.presets.length ?? 0) > 0) {
    out.push({
      id: "preset-default",
      title: t("palette.preset.default"),
      keywords: "preset assembly default",
      run: () => { switchSessionPreset(wsId, ""); },
    });
  }
  return out;
};

/** 调色板数据拉取：单项失败降级为 null（静态条目仍可用；错误不静默——记入 void 形参）。 */
const orNull = <T>(p: Promise<T>): Promise<T | null> =>
  p.catch((err: unknown) => { void err; return null; });

let paletteLoading = false;
initPalette(() => {
  if (paletteLoading) return;   // 拉取中防重入
  const wsId = runtime.workspaces.activeId();
  if (wsId === null) { openPalette(host, paletteCommands()); return; }
  paletteLoading = true;
  const session = modeTargetSession();
  void Promise.all([
    orNull(runtime.extensions.list(wsId)),
    orNull(runtime.presets.list(wsId)),
    orNull(runtime.presets.session(wsId, session)),
  ]).then(([ext, presets, current]) => {
    paletteLoading = false;
    if (isPaletteOpen()) return;   // 已被其他路径打开——不重复
    openPalette(host, [
      ...paletteCommands(),
      ...paletteExtCommands(wsId, ext, presets, current?.name ?? ""),
    ]);
  }, () => {
    paletteLoading = false;
    if (!isPaletteOpen()) openPalette(host, paletteCommands());
  });
});

initConfirmKeys();

const dock = createDock(dockHost, {
  view: "artifacts",
  enabled: dockCtl.snapshot().enabled,
  data: {
    artifacts: [], skills: [], mcp: [], recycle: [], sessions: [],
    artifactPreview: null,
    context: null, contextRows: [], contextUnits: [],
    tasks: [], usage: [], provenance: [], trace: [], traceUnit: "",
    log: [], notices: [], brain: deriveBrainRows(null), reports: [],
    trajectory: [],
    skillDetail: null, discover: null, skillNotice: "", mcpNotice: "",
  },
  states: dockCtl.snapshot().states,
  skillPanel: null,
  skillBusy: false,
  mcpBusy: false,
  onSelect: (id) => { void selectDock(id); },
  onRestore: () => { /* start 前无交互 */ },
  onPurge: () => { /* start 前无交互 */ },
  onRenameSession: () => { /* start 前无交互 */ },
  onExportSession: () => { /* start 前无交互 */ },
  onContextSelect: () => { /* start 前无交互 */ },
  onContextOmit: () => { /* start 前无交互 */ },
  onContextReplace: () => { /* start 前无交互 */ },
  onContextRestore: () => { /* start 前无交互 */ },
  onContextUnit: () => { /* start 前无交互 */ },
  onContextSources: () => { /* start 前无交互 */ },
  onContextUnitEdit: () => { /* start 前无交互 */ },
  onContextBudget: () => { /* start 前无交互 */ },
  onFocusUnit: () => { /* start 前无交互 */ },
  onOpenReport: () => { /* start 前无交互 */ },
  onLogExport: () => { /* start 前无交互 */ },
  onRetry: () => { /* start 前无交互 */ },
  onSkillPanel: () => { /* start 前无交互 */ },
  onSkillOpen: () => { /* start 前无交互 */ },
  onSkillInstall: () => { /* start 前无交互 */ },
  onSkillRemove: () => { /* start 前无交互 */ },
  onSkillToggle: () => { /* start 前无交互 */ },
  onSkillDiscover: () => { /* start 前无交互 */ },
  onMcpReload: () => { /* start 前无交互 */ },
});
document.addEventListener("keydown", (ev) => {
  if (ev.key === "Escape") settingsView.close();
});
onLangChange(() => { render(); });

const selectWorkspace = async (id: string): Promise<void> => {
  runtime.workspaces.setActive(id);
  newSession = false;
  activeSession = null;
  // 2026-09-27 审查：同步清空会话行——防右栏上下文回退（railSessions[0]）
  // 引用上一工作区的会话（网络实测：跨工作区 session 预览请求）。
  railSessions = [];
  // 碎片钻取态随工作区切换失效（防跨工作区陈旧视图）
  activeFragment = null;
  activeFragmentRun = null;
  fragmentData = null;
  await runtime.tasks.setWorkspace(id);
  refreshContextPercent();   // 工作区切换 → 顶栏口径刷新（活动会话已清空 → null）
  pendingSessionName = null;
  pendingModePicked = false;
  refreshSessionMeta();      // 工作区切换 → 模式回默认（sessionMode 由读取填充）
  void refreshSessionMessages(); // 修复②：切换工作区 → 清空/重载聊天记录
  void refreshRailSessions().then(() => { render(); });
  invalidateObserved();
  const dv = dockCtl.currentView();
  if (dv !== "artifacts" && dv !== "usage") {
    await loadDockView(dv);
  }
  render();
};

const handleConfirm = (items: readonly ConfirmItem[], reason: string): Promise<boolean> =>
  runtime.tasks.confirm(items, reason).then(
    () => true,
    () => false, // 失败已在命令总线广播（onCommandFailure 呈现）——保留待确认行可重试
  );

/** E2-5（A10）：答复提问（失败保留问题卡可重试——同确认口径）。 */
const handleAnswer = (unitId: string, questionId: string, answer: string,
                      source: string): Promise<boolean> =>
  runtime.tasks.answer(unitId, questionId, answer, source).then(
    () => true,
    () => false,
  );

// ---- A3（M7 #8）：重启后挂起任务恢复（快照 pending_resume） ----

/** 续跑：引擎从 task_state.json 恢复（确认门重发 → 确认卡再现）。 */
const resumePending = (): void => {
  void (async () => {
    const wsId = runtime.workspaces.activeId();
    if (wsId === null) return;
    try {
      await runtime.tasks.resumeWorkspace();
    } catch (err) {
      showError(`续跑失败：${err instanceof Error ? err.message : String(err)}`);
    }
    await runtime.tasks.setWorkspace(wsId);
    render();
  })();
};

/** 放弃：服务端改名留痕（不物理删除）——快照不再报挂起。 */
const abandonPending = (): void => {
  void (async () => {
    const wsId = runtime.workspaces.activeId();
    if (wsId === null) return;
    try {
      await runtime.tasks.abandonWorkspace();
    } catch (err) {
      showError(`放弃失败：${err instanceof Error ? err.message : String(err)}`);
    }
    await runtime.tasks.setWorkspace(wsId);
    render();
  })();
};

// ---- 结果恢复动作（P2-M6）：重试回填 / 续跑 / 回滚（两步确认在视内部） ----

const retryTask = (text: string): void => {
  composer.setText(text);
  notice(t("stream.retryFilled"));
};

const resumeTask = (): void => {
  void runtime.tasks.resume().then(() => { render(); }, (err: unknown) => {
    showError(`续跑失败：${err instanceof Error ? err.message : String(err)}`);
  });
};

const rollbackTask = (deleteArtifacts: boolean): void => {
  void (async () => {
    const wsId = runtime.workspaces.activeId();
    const runId = runtime.tasks.state().runId;
    if (wsId === null || runId === "") return;
    try {
      await runtime.tasks.rollback(runId, deleteArtifacts);
      await runtime.tasks.setWorkspace(wsId);
    } catch (err) {
      showError(`回滚失败：${err instanceof Error ? err.message : String(err)}`);
    }
    render();
  })();
};

const activeWorkspacePath = (): string => {
  if (!appStarted) return "";  // start 前不得触碰服务（组件初始 props 路径）
  const id = runtime.workspaces.activeId();
  return runtime.workspaces.list().find((w) => w.id === id)?.path ?? "";
};

const composerProps = (disabled: boolean, running: boolean,
                       opts?: { onSubmit?: (text: string) => void; draftKey?: string }) => ({
  disabled,
  running,
  references: taskRefs,
  skills: skillList,
  selectedSkills: taskSkills,
  draftKey: opts?.draftKey ?? (appStarted ? runtime.workspaces.activeId() ?? "" : ""),
  workspacePath: activeWorkspacePath(),
  onPickFiles: pickRefs,
  onRemoveRef: removeRef,
  onToggleSkill: toggleSkill,
  onSkillsOpen: openSkills,
  onStop: cancelTask,
  isolateRun,
  onToggleIsolate: () => { isolateRun = !isolateRun; render(); },
  onSubmit: opts?.onSubmit ?? ((text: string) => {
    submitTaskText(text, taskRefs);
  }),
});

const hero = createHero(heroHost, {
  hasWorkspace: false,
  examples: [],
  references: [],
  skills: [],
  selectedSkills: [],
  draftKey: "",
  workspacePath: "",
  pendingResume: null,
  onResumePending: () => { /* start 前无交互 */ },
  onAbandonPending: () => { /* start 前无交互 */ },
  onSubmit: (text) => { submitTaskText(text, taskRefs); },
  onPickFiles: () => { void pickRefs(); },
  onRemoveRef: () => { /* start 前无交互 */ },
  onToggleSkill: () => { /* start 前无交互 */ },
  onSkillsOpen: () => { /* start 前无交互 */ },
  onboard: false,
  onDismissOnboard: () => { /* start 前无交互 */ },
  onOpenHelp: () => { /* start 前无交互 */ },
  onCreateWorkspace: () => { rail.openCreateDialog(); },
});
const fragment = createFragment(fragmentHost, {
  unitId: "", session: null, live: null, composer: null, onBack: closeFragment,
});
const stream = createStream(streamHost, {
  state: INITIAL_TASK_STATE, // 服务在 start() 后才注册——初始用静态空态
  wsId: "",
  transcript: [],
  onCopyMessage: () => { /* start 前无交互 */ },
  onEditMessage: () => { /* start 前无交互 */ },
  onConfirm: handleConfirm,
  onRetry: retryTask,
  onResume: resumeTask,
  onRollback: rollbackTask,
  onWorktreeApply: (rid: string) => { void runtime.tasks.applyWorktree(rid); },
  onWorktreeDiscard: (rid: string) => { void runtime.tasks.discardWorktree(rid); },
});
// Wave-2 T2：会话装载/空会话骨架（切换中不闪旧内容——先清后填 + 骨架提示）
const sessionSkeleton = h("div", {
  class: "session-skeleton", dataset: { st: "session-loading" },
});
streamHost.prepend(sessionSkeleton);
const composer = createComposer(composerHost, composerProps(true, false));
const modeBar = createModeBar(modeBarHost, {
  current: "minimal-standard", editable: true, visible: false,
  onPick: (id) => { pickMode(id); },
});
const designCard = createDesignCard(designCardHost, {
  visible: false, phase: "", round: 0, tickets: [], mapReady: false,
  mapChanged: false, spec: null, implTickets: [], composerText: "",
  onViewMap: designViewMap, onHandoff: designHandoff,
  onToggleRecommend: () => { /* start 前无交互 */ },
  onPublishTickets: () => { /* start 前无交互 */ },
});
const floatCard = createFloatCard(floatRoot, {
  state: INITIAL_TASK_STATE, maxParallel: null, enabled: floatCardEnabled,
  onClose: () => { setFloatCardEnabled(false); },
});
let maxParallel: number | null = null;

function render(): void {
  if (!appStarted || appStopping) return; // boot/停机期不得触碰服务（初始 props 已静态安全）
  const taskState = runtime.tasks.state();
  const prefsWs = runtime.workspaces.activeId();
  if (prefsWs !== interactionPrefsWs) {
    interactionPrefsWs = prefsWs;
    interactionPrefs = {};
    void loadInteractionPrefs(prefsWs);   // #2 P1.5：随工作区切换取偏好（懒加载）
  }
  const ds = dockCtl.snapshot();
  // 串台修复（2026-09-25）：视图按会话隔离——任务流/结果/产物不得跨会话显示
  const taskView = taskViewForSession(taskState, activeSession);
  if (topbar !== null) topbar.update(topbarProps());
  dock.update({
    view: ds.view,
    enabled: ds.enabled,
    onOpenFragment: (unitId: string) => { void openFragment(unitId); },
    data: {
      artifacts: deriveArtifactRows(taskView.result),
      artifactPreview: ds.artifactPreview,
      skills: ds.skills,
      mcp: ds.mcp,
      recycle: ds.recycle,
      sessions: ds.sessions,
      context: dockContext,
      contextRows: dockContextRows,
      contextUnits: dockContextUnits,
      contextFallback: dockContextFallback,
      tasks: ds.tasks,
      trajectory: ds.trajectory,
      usage: deriveUsageRows(taskView.result?.metrics),
      provenance: ds.provenance,
      trace: ds.trace,
      traceUnit: ds.traceUnit,
      log: ds.log,
      notices: ds.notices,
      brain: ds.brain,
      reports: ds.reports,
      skillDetail: ds.skillDetail,
      discover: ds.discover,
      skillNotice: ds.skillNotice,
      mcpNotice: ds.mcpNotice,
    },
    states: ds.states,
    skillPanel: ds.skillPanel,
    skillBusy: ds.skillBusy,
    mcpBusy: ds.mcpBusy,
    onSelect: (id) => { void selectDock(id); },
    onRestore: restoreRecycle,
    onPurge: purgeRecycle,
    onRenameSession: renameSession,
    onExportSession: exportSession,
    onContextSelect: (name: string) => {
      // 选会话 → 与左栏选中同口径（显示会话流 + 投影刷新）
      activeSession = name;
      activeSessionSince = Date.now();   // Wave-2 T3
      activeFragment = null;
      fragmentData = null;
      activeFragmentRun = null;
      newSession = false;
      void refreshSessionMessages();
      refreshContextPercent();
      pendingSessionName = null;
      pendingModePicked = false;
      refreshSessionMeta();
      void refreshDockContext();
      render();
    },
    onContextOmit: (name: string, round: number) => {
      contextEdit(name, round, "omit");
    },
    onContextReplace: (name: string, round: number) => {
      openPrompt(host, {
        title: t("ctx.replace"),
        value: "",
        onOk: (value) => { contextEdit(name, round, "replace", value); },
      });
    },
    onContextRestore: (name: string, round: number) => {
      contextEdit(name, round, "restore");
    },
    onContextUnit: (unitId: string) => {
      const wsId = runtime.workspaces.activeId();
      if (wsId === null) return;
      void runtime.context.preview(wsId, { unit: unitId }).then(
        (d) => { dockContext = d; render(); },
        () => { /* 失败已命令总线可见——保留旧面板 */ },
      );
    },
    onContextSources: contextSetSources,
    onContextHandoff: (name: string) => { contextHandoff(name); },
    onContextUnitEdit: contextUnitEdit,
    onContextBudget: (target: { session?: string; unit?: string }, current: number) => {
      openPrompt(host, {
        title: t("ctx.budget.set"),
        value: current > 0 ? String(current) : "0",
        onOk: (value) => {
          const n = Number(value.trim());
          if (!Number.isFinite(n) || n < 0) return;
          contextSetSources(target, { budget_tokens: Math.floor(n) });
        },
      });
    },
    onFocusUnit: focusUnit,
    onOpenReport: openReport,
    onPreviewArtifact: openArtifactPreview,
    onCloseArtifactPreview: closeArtifactPreview,
    onCopyArtifactPath: copyArtifactPath,
    onOpenArtifactLocal: openArtifactLocal,
    onLogExport: exportEvents,
    onRetry: (id) => { void loadDockView(id); },
    onSkillPanel: (panel) => {
      dockCtl.setSkillPanel(panel);
      if (panel === null) dockCtl.setSkillNotice("");
      render();
    },
    onSkillOpen: openSkill,
    onSkillInstall: installSkill,
    onSkillRemove: removeSkill,
    onSkillToggle: toggleSkillEnabled,
    onSkillDiscover: discoverSkills,
    onMcpReload: reloadMcp,
  });
  rail.update({
    ...railCallbacks,
    workspaces: runtime.workspaces.list(),
    folders: runtime.workspaces.folders(),
    activeId: runtime.workspaces.activeId(),
    sessions: railSessions,
    activeSession,
    rounds: sessionRoundsData?.rounds ?? null,
    recycle: ds.recycle,
    notices: railNotices,
    noticeUnread,
    onSearch: () => { openSearch(host, searchHandlers); },
    onNotices: () => { openDockView("notifications"); },
    onOpenSettings: () => { void settingsView.open(); },
    onRecycle: () => { openDockView("recycle"); },
    onCreateWorkspace: createWorkspace,
  });
  // hero-mode（旧壳口径）：零态显示欢迎页（大 LOGO 仅此出现），工作态显示任务流+输入区。
  // 2026-09-21 修复：选中「有内容的历史会话」时展示会话流（原仅在任务态展示——历史会话看不到内容）
  const sessionHasContent = activeSession !== null && sessionRows.length > 0;
  const taskEmpty = taskView.rows.length === 0
    && taskView.pendingConfirms.length === 0
    && taskView.result === null
    && taskView.taskText === "";
  const zeroState = deriveZeroState({ activeSession, newSession, taskEmpty, sessionHasContent });
  heroHost.hidden = !zeroState;
  streamHost.hidden = zeroState;
  composerHost.hidden = zeroState;
  // Wave-2 T2：装载/空会话骨架（activeSession 非空且无行时提示——载入中/空会话）
  const skeletonVisible = activeSession !== null && sessionRows.length === 0;
  sessionSkeleton.hidden = !skeletonVisible;
  if (skeletonVisible) {
    sessionSkeleton.textContent = sessionLoadState === "loading"
      ? t("stream.sessionLoading")
      : t("stream.sessionEmpty");
  }
  // 碎片会话视图（批 3）：优先于 hero/stream 显示
  const fragmentActive = activeFragment !== null;
  fragmentHost.hidden = !fragmentActive;
  if (fragmentActive) {
    heroHost.hidden = true;
    streamHost.hidden = true;
    composerHost.hidden = true;
  }
  fragment.update({
    unitId: activeFragment ?? "",
    session: fragmentData,
    live: fragmentActive
      ? {
          unitId: activeFragment ?? "",
          boundRunId: activeFragmentRun,
          runId: taskView.runId,
          status: taskView.status,
          taskText: taskView.taskText,
          rows: taskView.rows,
          thoughts: taskView.thoughts,
          boundUserTexts: (fragmentData?.bound_rounds ?? []).map((b) => b.user_text),
        }
      : null,
    composer: fragmentActive
      ? composerProps(
          taskState.status === "running" || runtime.commands.pendingCount() > 0,
          taskState.status === "running",
          {
            onSubmit: (text: string) => { submitFragmentText(text, taskRefs); },
            draftKey: `${runtime.workspaces.activeId() ?? ""}:unit:${activeFragment ?? ""}`,
          },
        )
      : null,
    onOpenFragment: (unitId: string) => { void openFragment(unitId); },
    onBack: closeFragment,
  });
  hero.update({
    hasWorkspace: runtime.workspaces.activeId() !== null,
    examples: [t("hero.example.1"), t("hero.example.2"), t("hero.example.3")],
    references: taskRefs,
    skills: skillList,
    selectedSkills: taskSkills,
    draftKey: runtime.workspaces.activeId() ?? "",
    workspacePath: activeWorkspacePath(),
    pendingResume: taskState.pendingResume,
    onResumePending: resumePending,
    onAbandonPending: abandonPending,
    onRemoveRef: removeRef,
    onToggleSkill: toggleSkill,
    onSkillsOpen: openSkills,
    onSubmit: (text) => { submitTaskText(text, taskRefs); },
    onPickFiles: () => { void pickRefs(); },
    onCreateWorkspace: () => { rail.openCreateDialog(); },
    onboard: shouldShowOnboard({ heroVisible: zeroState, done: onboardDone }),
    onDismissOnboard: () => { markOnboardDone(); render(); },
    onOpenHelp: () => { openHelp(host); },
    isolateRun,
    onToggleIsolate: () => { isolateRun = !isolateRun; render(); },
  });
  floatCard.update({
    state: taskState, maxParallel, enabled: floatCardEnabled,
    onClose: () => { setFloatCardEnabled(false); },
  });
  stream.update({
    state: taskView,
    wsId: runtime.workspaces.activeId() ?? "",
    transcript: deriveChatMessages(sessionRows),
    rounds: sessionRoundsData?.rounds ?? [],
    onCopyMessage: copyMessage,
    onEditMessage: editMessage,
    onBranchMessage: branchFromMessage,
    onConfirm: handleConfirm,
    onAnswer: handleAnswer,
    onRetry: retryTask,
    onResume: resumeTask,
    onOverride: overrideGate,
    onRollback: rollbackTask,
    onOpenFragment: (unitId) => { void openFragment(unitId); },
    onOpenArtifact: (path) => { openReport(path); },
    onWorktreeApply: (rid: string) => { void runtime.tasks.applyWorktree(rid); },
    onWorktreeDiscard: (rid: string) => { void runtime.tasks.discardWorktree(rid); },
    prefs: () => interactionPrefs,
    onPrefsChange,
  });
  composer.update(composerProps(
    taskState.status === "running" || runtime.commands.pendingCount() > 0,
    taskState.status === "running",
  ));
  modeBar.update({
    current: sessionMode === null ? "minimal-standard"
      : joinModeId(sessionMode.mode, sessionMode.variant),
    editable: sessionMode === null ? true : sessionMode.editable,
    visible: runtime.workspaces.activeId() !== null
      && (sessionMode === null || sessionMode.picker_enabled),
    onPick: pickMode,
  });
  const specWs = runtime.workspaces.activeId();
  designCard.update({
    visible: sessionMode !== null && sessionMode.mode === "theroad"
      && designState !== null,
    session: activeSession ?? "",   // Wave-2 T9：开合记忆键（换会话记忆独立）
    phase: designState?.phase ?? "",
    round: designState?.round ?? 0,
    tickets: deriveDesignTicketRows(designState?.tickets ?? [],
                                    designState?.questions ?? []),
    mapReady: designState?.map_ready ?? false,
    mapChanged: designState?.map_changed ?? false,
    spec: designState?.spec != null && specWs !== null
      ? { slug: designState.spec.slug,
          ready: designState.spec.ready,
          url: runtime.design.specFileUrl(specWs, designState.spec.path) }
      : null,
    implTickets,
    composerText: composer.getText(),
    onViewMap: designViewMap,
    onHandoff: designHandoff,
    onToggleRecommend: (recommend: string) => {
      const line = recommendLine(t("design.answerPrefix"), recommend);
      composer.setText(toggleRecommendText(composer.getText(), line));
      render();   // 刷新按钮 applied 态（textarea 持久——不丢内容/焦点）
    },
    onPublishTickets: publishImplTickets,
  });
}

/** 订阅只在 start 成功后绑定（服务在 start 内注册——提前解析会抛「服务未注册」）。 */
function bindSubscriptions(): void {
  let lastTaskStatus = "";
  runtime.tasks.subscribe(() => {
    const state = runtime.tasks.state();
    confirmNotify.sync();   // T-2：挂起集合变化 → 剪枝/通知（隐藏态）
    if (state.status !== lastTaskStatus) {
      const wasTerminal = TERMINAL_STATUSES.includes(lastTaskStatus);
      lastTaskStatus = state.status;
      if (!wasTerminal && TERMINAL_STATUSES.includes(state.status)) {
        void refreshNotices(); // 终态 → 刷新通知徽标（unread 与 /notifications 同源）
        void refreshRailSessions().then(() => { render(); }); // 终态可能沉淀新会话文件
        void refreshSessionMessages(); // 修复②：终态 → 聊天记录补全该轮
        // 碎片会话后半程：终态 → 重取碎片数据（绑定轮次就该轮落位）
        if (activeFragment !== null) void refreshFragmentData();
        refreshContextPercent();   // B 期：终态 → 顶栏口径刷新（新轮入上下文）
        refreshSessionMeta();      // 批 1：终态 → 模式 editable 同步（首轮落地后锁定）
        void refreshDockContext();
      }
    }
    // E3-1/R5（T5）：worktree_ready → 自动取一次变更视图（reviewed 后不再取）
    const wt = state.worktree;
    if (wt !== null && wt !== undefined && !wt.reviewed && !wt.busy) {
      void runtime.tasks.reviewWorktree(wt.runId);
    }
    scheduler.schedule(render);
  });
  runtime.workspaces.subscribe(() => { scheduler.schedule(render); });
  runtime.commands.subscribe((ev) => {
    // 双模式批 1：设置写入可能变更模式默认/显隐 → 模式 DTO 失效重取
    if (ev.name === "settings.write" && ev.state === "success") refreshSessionMode();
    scheduler.schedule(render);
  });
}

runtime
  .start()
  .then(() => {
    appStarted = true;
    bindSubscriptions();
    render();
    refreshSessionMeta();      // 双模式批 1：首屏模式 chip/标签
    void refreshNotices();
    void refreshRailSessions().then(() => { render(); });
    void runtime.settings.readConfig().then((cfg) => {
      const value = Number(cfg.values.max_parallel_units);
      maxParallel = Number.isFinite(value) && value > 0 ? value : null;
      applyUiTheme(cfg.values.ui_theme);   // 主题随配置加载（默认 ink）
      render();
    }).catch((err: unknown) => { void err; /* 并发上限/主题未知：默认值 */ });
    bootLine.textContent = "";
    document.body.dataset.state = "ready";
  })
  .catch((error: unknown) => {
    showError(`启动失败：${error instanceof Error ? error.message : String(error)}`);
    errorBox.textContent = `启动失败：${error instanceof Error ? error.message : String(error)}`;
    errorBox.removeAttribute("hidden");
    bootLine.textContent = "启动失败";
    runtime.stop();
  });

window.addEventListener("beforeunload", () => {
  appStopping = true;
  runtime.stop();
});
