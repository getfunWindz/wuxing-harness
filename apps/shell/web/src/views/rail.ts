/** 左栏（P2-S9/M1）：工作区列表 + 文件夹 + 行菜单 + 收起（与旧壳同款时序动画）。 */
import { h, mount, svgIcon } from "../render/dom.ts";
import type { ComponentInstance } from "../render/component.ts";
import type { FolderDto, WorkspaceDto } from "../protocol/generated.ts";
import { deriveRailRows } from "./view-model.ts";
import type { NoticeViewRow, RailFragRow, RailRoundSource, RecycleRow, SessionRow } from "./view-model.ts";
import { deriveRailRounds } from "./view-model.ts";
import { ICON_ADD, ICON_BELL, ICON_CHEVRON, ICON_MORE, ICON_RECYCLE, ICON_SEARCH, ICON_SETTINGS } from "./icons.ts";
import { t } from "./i18n.ts";

const RAIL_KEY = "wuxing.rail.v2";

export interface RailProps {
  workspaces: readonly WorkspaceDto[];
  folders: readonly FolderDto[];
  activeId: string | null;
  noticeUnread: number;
  /** 会话列表（当前工作区；B1：工作区/会话两区各一个 ＋） */
  sessions: readonly SessionRow[];
  /** 轮次化（批 3）：当前会话的轮→碎片树（仅非线性轮出碎片行——用户运行思路） */
  rounds?: readonly RailRoundSource[] | null;
  /** 当前选中会话（文件名；B1 补：选中效果 + 二级菜单） */
  activeSession: string | null;
  /** 回收站弹出菜单（R1-2 保留裁决：左栏按钮直接弹菜单——不依赖右栏） */
  recycle: readonly RecycleRow[];
  /** 通知弹出菜单（2026-09-19 用户反馈：收起态也可用） */
  notices: readonly NoticeViewRow[];
  onSelect(id: string): void;
  onArchive(id: string): void;
  onClose(id: string): void;
  onCopyPath(id: string): void;
  onMoveToFolder(id: string, folder: string): void;
  onToggleFolder(id: string, collapsed: boolean): void;
  onNewFolder(): void;
  onRenameFolder(id: string): void;
  onDeleteFolder(id: string): void;
  onNewSession(): void;
  /** 新建工作区：走系统资源管理器选文件夹（2026-09-19 用户裁决） */
  onPickWorkspaceDir(): void;
  onSelectSession(name: string): void;
  onOpenFragment?(unitId: string): void;
  onRenameSession(name: string): void;
  onExportSession(name: string): void;
  onArchiveSession(name: string): void;
  onDeleteSession(name: string): void;
  onRecycleOpen(): void;
  onRestoreRecycle(id: string): void;
  onPurgeRecycle(id: string): void;
  onNoticesOpen(): void;
  onOpenAllNotices(): void;
  onSearch(): void;
  onNotices(): void;
  onOpenSettings(): void;
  onRecycle(): void;
  onCreateWorkspace(path: string): Promise<void>;
}

function loadCollapsed(): boolean {
  try {
    return localStorage.getItem(RAIL_KEY) === "1";
  } catch (err) {
    void err; // 偏好不可用 → 默认展开
    return false;
  }
}

function saveCollapsed(value: boolean): void {
  try {
    localStorage.setItem(RAIL_KEY, value ? "1" : "0");
  } catch (err) {
    void err; // 持久化失败不阻断交互
  }
}

export type RailInstance = ComponentInstance<RailProps> & {
  openCreateDialog(prefill?: string): void;
};

export function createRail(host: HTMLElement, initial: RailProps): RailInstance {
  let props = initial;
  let collapsed = loadCollapsed();
  let narrow = typeof window !== "undefined" && window.innerWidth <= 768;
  let drawerOpen = false;
  /** 当前是否收起（窄屏下由抽屉态决定，不覆盖用户偏好）。 */
  const isCollapsed = (): boolean => (narrow ? !drawerOpen : collapsed);
  let animating = false;
  let openMenu: string | null = null;   // "ws:<id>" | "folder:<id>" | "session:<name>"
  let confirmSessionDel: string | null = null;
  let confirmFolderDel: string | null = null;
  let addOpen = false;
  let dialogOpen = false;
  /** 手输路径草稿（2026-09-30：弹窗重绘/回退时保留上次输入与预填） */
  let createDraft = "";
  let busy = false;
  let addError = "";
  let recycleOpen = false;
  let purgeConfirm: string | null = null;
  let noticesOpen = false;

  // 二级菜单/弹层外点关闭（2026-09-21 修正：栏内其他位置点击也关闭——原仅在栏外点击生效，
  // 导致「必须再点菜单按钮才能收回」；触发按钮例外——由按钮自身切换逻辑处理）
  const root = h("aside", { class: "rail" });
  host.appendChild(root);

  // 外点关闭弹出层（工作区＋菜单/会话菜单、回收站与通知弹层）
  const onDocPointer = (ev: MouseEvent): void => {
    if (!recycleOpen && !noticesOpen && openMenu === null && !addOpen) return;
    const target = ev.target as HTMLElement;
    // 触发按钮自身例外（展开态 rail-foot / 收起态 rail-mini——2026-09-22 修复：
    // 原仅排除 .rail-foot button，收起态迷你按钮点击被本处理器吞掉，弹层无法打开）
    if (target.closest(".rail-menu, .rail-popover, .rail-more, .rail-foot button, "
        + ".rail-mini button, [data-st='rail-add']")) return;
    recycleOpen = false;
    noticesOpen = false;
    openMenu = null;
    addOpen = false;   // 2026-09-19 修复：＋菜单此前漏在外点关闭之外（悬留遮挡）
    paint();
  };
  // 2026-09-21：改 click 冒泡阶段——晚于目标自身 click 处理器（避免先重建 DOM 吞掉点击）
  document.addEventListener("click", onDocPointer, false);

  function menuButton(label: string, onClick: () => void, key = "", danger = false): HTMLElement {
    return h("button", {
      class: danger ? "rail-menu-item danger" : "rail-menu-item",
      attrs: { type: "button", ...(key !== "" ? { "data-st": key } : {}) },
      text: label,
      onClick: () => { onClick(); },
    });
  }

  function workspaceMenu(ws: WorkspaceDto): HTMLElement {
    const items: HTMLElement[] = [
      menuButton(t("rail.menu.archive"), () => { openMenu = null; props.onArchive(ws.id); }, `rail-menu:archive:${ws.id}`),
      menuButton(t("rail.menu.close"), () => { openMenu = null; props.onClose(ws.id); }, `rail-menu:close:${ws.id}`, true),
      menuButton(t("rail.menu.copyPath"), () => { openMenu = null; props.onCopyPath(ws.id); }, `rail-menu:copy:${ws.id}`),
    ];
    for (const folder of props.folders) {
      if (ws.folder !== folder.id) {
        items.push(menuButton(`${t("rail.menu.moveTo")}${folder.name}`, () => {
          openMenu = null;
          props.onMoveToFolder(ws.id, folder.id);
        }, `rail-menu:move:${ws.id}:${folder.id}`));
      }
    }
    if ((ws.folder ?? "") !== "") {
      items.push(menuButton(t("rail.menu.moveOut"), () => {
        openMenu = null;
        props.onMoveToFolder(ws.id, "");
      }, `rail-menu:moveout:${ws.id}`));
    }
    return h("div", { class: "rail-menu" }, ...items);
  }

  function folderMenu(folder: FolderDto): HTMLElement {
    if (confirmFolderDel === folder.id) {
      return h("div", { class: "rail-menu" },
        menuButton(`${t("rail.menu.delete")}？`, () => {
          openMenu = null;
          confirmFolderDel = null;
          props.onDeleteFolder(folder.id);
        }, `rail-menu:folder-delete-ok:${folder.id}`, true),
        menuButton(t("settings.prov.cancel"), () => { confirmFolderDel = null; paint(); },
          `rail-menu:folder-delete-cancel:${folder.id}`));
    }
    return h("div", { class: "rail-menu" },
      menuButton(t("rail.menu.rename"), () => {
        openMenu = null;
        props.onRenameFolder(folder.id);
      }, `rail-menu:folder-rename:${folder.id}`),
      menuButton(t("rail.menu.delete"), () => { confirmFolderDel = folder.id; paint(); },
        `rail-menu:folder-delete:${folder.id}`, true));
  }

  function workspaceRow(ws: WorkspaceDto, nested: boolean): HTMLElement {
    const row = deriveRailRows([ws], props.activeId)[0]!;
    const menuKey = `ws:${ws.id}`;
    return h("div", { class: nested ? "rail-item-wrap nested" : "rail-item-wrap" },
      h("button", {
        class: row.active ? "rail-item active" : "rail-item",
        attrs: { type: "button", "data-st": `rail:${row.id}` },
        onClick: () => { props.onSelect(row.id); },
      },
        h("span", { class: "rail-name", text: row.label }),
        h("span", { class: "rail-status", text: row.statusLabel })),
      h("button", {
        class: "rail-more", attrs: { type: "button", "data-st": `rail-more:${row.id}`, title: t("rail.menu.more"), "aria-label": t("rail.menu.more") },
        onClick: () => { openMenu = openMenu === menuKey ? null : menuKey; paint(); },
      }, svgIcon(ICON_MORE)),
      openMenu === menuKey ? workspaceMenu(ws) : null);
  }

  function recyclePopover(): HTMLElement[] {
    if (!recycleOpen) return [];
    const rows = props.recycle;
    return [h("div", { class: "rail-popover", attrs: { "data-st": "rail-recycle-pop" } },
      h("div", { class: "rp-head", text: t("rail.recycle") }),
      rows.length === 0
        ? h("div", { class: "rail-empty", text: t("dock.empty.recycle") })
        : h("div", { class: "rp-body" }, ...rows.map((entry) =>
          h("div", { class: "rp-entry" },
            h("div", { class: "rp-main" },
              h("span", { class: "rp-name", text: entry.name }),
              h("span", { class: "rp-note", text: entry.detail })),
            h("div", { class: "rp-actions" },
              h("button", {
                class: "st-btn ghost",
                attrs: { type: "button", "data-st": `rail-rc-restore:${entry.id}` },
                text: t("dock.restore"),
                onClick: () => { props.onRestoreRecycle(entry.id); },
              }),
              purgeConfirm === entry.id
                ? h("button", {
                  class: "st-btn danger",
                  attrs: { type: "button", "data-st": `rail-rc-purge-ok:${entry.id}` },
                  text: t("dock.purgeConfirm"),
                  onClick: () => { purgeConfirm = null; props.onPurgeRecycle(entry.id); },
                })
                : h("button", {
                  class: "st-btn ghost",
                  attrs: { type: "button", "data-st": `rail-rc-purge:${entry.id}` },
                  text: t("dock.purge"),
                  onClick: () => { purgeConfirm = entry.id; paint(); },
                }))))))];
  }

  function noticesPopover(): HTMLElement[] {
    if (!noticesOpen) return [];
    const rows = props.notices;
    return [h("div", { class: "rail-popover", attrs: { "data-st": "rail-notices-pop" } },
      h("div", { class: "rp-head", text: t("rail.notices") }),
      rows.length === 0
        ? h("div", { class: "rail-empty", text: t("dock.empty.notifications") })
        : h("div", { class: "rp-body" }, ...rows.slice(0, 20).map((row) =>
          h("div", { class: "rp-entry" },
            h("div", { class: "rp-main" },
              h("span", { class: "rp-name", text: row.title }),
              h("span", { class: "rp-note", text: row.meta }))))),
      h("button", {
        class: "rp-all", attrs: { type: "button", "data-st": "rail-notices-all" },
        text: t("rail.noticesAll"),
        onClick: () => { noticesOpen = false; props.onOpenAllNotices(); },
      }))];
  }

  /** 弹层定位（fixed）：逃逸收起态 overflow 裁切；展开态左缘对齐，收起态开在轨道右侧 */
  function placePopovers(): void {
    const railRect = root.getBoundingClientRect();
    const place = (anchorSel: string, popSel: string): void => {
      const pop = root.querySelector<HTMLElement>(popSel);
      if (!pop) return;
      const anchor = root.querySelector<HTMLElement>(anchorSel);
      pop.style.left = isCollapsed()
        ? `${Math.round(railRect.right) + 8}px`
        : `${Math.round(railRect.left) + 8}px`;
      if (anchor) {
        const r = anchor.getBoundingClientRect();
        pop.style.bottom = `${Math.max(8, Math.round(window.innerHeight - r.bottom))}px`;
      }
    };
    place('[data-st="rail-recycle"]', '[data-st="rail-recycle-pop"]');
    place('[data-st="rail-notices"], [data-st="rail-notices-mini"]',
          '[data-st="rail-notices-pop"]');
  }

  function searchInput(): HTMLElement {
    return h("input", {
      class: "rail-search",
      attrs: {
        type: "search", "data-st": "rail-search",
        id: "rail-search", name: "search",
        placeholder: t("rail.search"), "aria-label": t("rail.search"), spellcheck: "false",
      },
      onClick: () => { props.onSearch(); },
      onKeyDown: (ev: KeyboardEvent) => {
        if (ev.key === "Enter") {
          ev.preventDefault();
          props.onSearch();
        }
      },
    }) as HTMLInputElement;
  }

  async function submitWorkspace(): Promise<void> {
    const input = root.querySelector<HTMLInputElement>('[data-st="new-ws-path"]');
    const path = input?.value.trim() ?? "";
    if (path === "") {
      addError = t("topbar.err.path");
      paint();
      return;
    }
    busy = true;
    addError = "";
    paint();
    try {
      await props.onCreateWorkspace(path);
      dialogOpen = false;
    } catch (err) {
      addError = err instanceof Error ? err.message : String(err);
    } finally {
      busy = false;
      paint();
    }
  }

  function footButton(icon: readonly string[], key: string, title: string,
                      onClick: () => void, place: "foot" | "mini"): HTMLElement {
    void place;
    return h("button", {
      attrs: { type: "button", "data-st": key, title, "aria-label": title },
      onClick,
    }, svgIcon(icon));
  }

  function searchButton(place: "head" | "mini"): HTMLElement {
    return h("button", {
      class: place === "mini" ? "rail-mini-btn" : "rail-more",
      attrs: {
        type: "button",
        "data-st": place === "mini" ? "rail-search-mini" : "rail-search",
        title: t("rail.search"),
        "aria-label": t("rail.search"),
      },
      onClick: () => { props.onSearch(); },
    }, svgIcon(ICON_SEARCH));
  }

  function noticesButton(place: "foot" | "mini"): HTMLElement {
    const unread = props.noticeUnread;
    return h("button", {
      class: place === "mini" ? "rail-mini-btn rail-notice" : "rail-notice",
      attrs: {
        type: "button",
        "data-st": place === "mini" ? "rail-notices-mini" : "rail-notices",
        title: t("rail.notices"),
        "aria-label": t("rail.notices"),
        ...(unread > 0 ? { "data-unread": String(unread) } : {}),
      },
      onClick: () => {
        noticesOpen = !noticesOpen;
        recycleOpen = false;
        openMenu = null;
        if (noticesOpen) props.onNoticesOpen();
        paint();
      },
    },
      svgIcon(ICON_BELL),
      unread > 0
        ? h("span", { class: "rail-badge", text: unread > 99 ? "99+" : String(unread) })
        : null);
  }

  function inner(): HTMLElement[] {
    if (isCollapsed()) {
      return [
        h("div", { class: "rail-mini" },
          h("button", {
            class: "rail-toggle-mini",
            attrs: { type: "button", "data-st": "rail-expand", title: t("rail.expand"), "aria-label": t("rail.expand") },
            onClick: () => { toggle(); },
          }, svgIcon(ICON_CHEVRON)),
          searchButton("mini"),
          noticesButton("mini"),
          footButton(ICON_SETTINGS, "open-settings", t("app.settings"),
            () => { props.onOpenSettings(); }, "mini"),
          h("button", {
            attrs: { type: "button", "data-st": "rail-recycle", title: t("rail.recycle"), "aria-label": t("rail.recycle") },
            onClick: () => {
              recycleOpen = !recycleOpen;
              openMenu = null;
              if (recycleOpen) props.onRecycleOpen();
              paint();
            },
          }, svgIcon(ICON_RECYCLE)),
          ...props.workspaces.map((ws) =>
            h("button", {
              class: ws.id === props.activeId ? "rail-mini-ws on" : "rail-mini-ws",
              attrs: { type: "button", "data-st": `rail-mini:${ws.id}`, title: ws.name },
              text: (ws.name || "?").slice(0, 1).toUpperCase(),
              onClick: () => { props.onSelect(ws.id); },
            }))),
        ...recyclePopover(),
        ...noticesPopover(),
      ];
    }
    const known = new Set(props.folders.map((f) => f.id));
    const grouped = new Map<string, WorkspaceDto[]>();
    const loose: WorkspaceDto[] = [];
    for (const ws of props.workspaces) {
      const folder = ws.folder ?? "";
      if (folder !== "" && known.has(folder)) {
        grouped.set(folder, [...(grouped.get(folder) ?? []), ws]);
      } else {
        loose.push(ws);
      }
    }
    const body: HTMLElement[] = [];
    for (const folder of props.folders) {
      const items = grouped.get(folder.id) ?? [];
      const key = `folder:${folder.id}`;
      body.push(h("div", { class: "rail-folder" },
        h("div", {
          class: folder.collapsed ? "rail-folder-head closed" : "rail-folder-head",
          attrs: { "data-st": `rail-folder:${folder.id}` },
          onClick: () => { props.onToggleFolder(folder.id, !folder.collapsed); },
        },
          h("span", { class: folder.collapsed ? "rail-caret closed" : "rail-caret" }, svgIcon(ICON_CHEVRON)),
          h("span", { class: "rail-name", text: folder.name }),
          h("span", { class: "count", text: String(items.length) }),
          h("button", {
            class: "rail-more", attrs: { type: "button", "data-st": `rail-folder-more:${folder.id}` },
            onClick: (ev: Event) => { ev.stopPropagation(); openMenu = openMenu === key ? null : key; paint(); },
          }, svgIcon(ICON_MORE))),
        openMenu === key ? folderMenu(folder) : null,
        folder.collapsed ? null
          : h("div", { class: "rail-list", attrs: { "data-st": `rail-folder-list:${folder.id}` } },
            ...items.map((ws) => workspaceRow(ws, true)))));
    }
    body.push(...loose.map((ws) => workspaceRow(ws, false)));
    if (props.workspaces.length === 0) {
      body.push(h("div", { class: "rail-empty", text: t("rail.empty") }));
    }
    return [
      h("div", { class: "rail-scroll" },
        h("div", { class: "rail-top" },
          searchInput(),
          h("button", {
            class: "rail-more", attrs: { type: "button", "data-st": "rail-collapse", title: t("rail.collapse"), "aria-label": t("rail.collapse") },
            onClick: () => { toggle(); },
          }, h("span", { class: "rot180" }, svgIcon(ICON_CHEVRON)))),
        h("div", { class: "rail-section" },
          h("div", { class: "rail-title" },
            t("rail.title"),
            h("button", {
              class: "rail-add", attrs: { type: "button", "data-st": "rail-add", title: t("topbar.newWorkspace"), "aria-label": t("topbar.newWorkspace") },
              onClick: () => { addOpen = !addOpen; dialogOpen = false; paint(); },
            }, svgIcon(ICON_ADD))),
          addOpen
            ? h("div", { class: "topbar-menu" },
              h("button", {
                class: "topbar-menu-item", attrs: { type: "button", "data-st": "menu-new-ws" },
                text: t("topbar.newWorkspace"),
                onClick: () => { addOpen = false; props.onPickWorkspaceDir(); paint(); },
              }),
              h("button", {
                class: "topbar-menu-item", attrs: { type: "button", "data-st": "menu-new-ws-typed" },
                text: t("rail.menu.typedPath"),
                onClick: () => { addOpen = false; dialogOpen = true; addError = ""; paint(); },
              }),
              h("button", {
                class: "topbar-menu-item", attrs: { type: "button", "data-st": "menu-new-folder" },
                text: t("rail.newFolder"),
                onClick: () => { addOpen = false; props.onNewFolder(); paint(); },
              }))
            : null,
          dialogOpen
            ? h("div", { class: "topbar-dialog" },
              h("div", { class: "st-fl", text: t("topbar.newWorkspace") }),
              h("input", {
                class: "st-input", attrs: { type: "text", "data-st": "new-ws-path",
                                            id: "new-ws-path", name: "workspace-path",
                                            placeholder: "C:/path/to/workspace",
                                            value: createDraft },
                onInput: (ev: Event) => {
                  createDraft = (ev.target as HTMLInputElement).value;
                },
              }),
              addError !== "" ? h("div", { class: "st-err", text: addError }) : null,
              h("div", { class: "st-row" },
                h("button", {
                  class: "st-btn", attrs: { type: "button", "data-st": "new-ws-ok", ...(busy ? { disabled: "disabled" } : {}) },
                  text: busy ? t("settings.prov.saving") : t("topbar.create"),
                  onClick: () => { void submitWorkspace(); },
                }),
                h("button", {
                  class: "st-btn ghost", attrs: { type: "button", "data-st": "new-ws-cancel" },
                  text: t("settings.prov.cancel"),
                  onClick: () => { dialogOpen = false; paint(); },
                })))
            : null,
          ...body),
        h("div", { class: "rail-section" },
          h("div", { class: "rail-title" },
            t("rail.sessions"),
            h("button", {
              class: "rail-add", attrs: { type: "button", "data-st": "rail-new-session", title: t("rail.newSession"), "aria-label": t("rail.newSession") },
              onClick: () => { props.onNewSession(); },
            }, svgIcon(ICON_ADD))),
          props.sessions.length === 0
            ? h("div", { class: "rail-empty", text: t("rail.sessionEmpty") })
            : h("div", { class: "rail-list" }, ...props.sessions.map((session) => {
              const menuKey = `session:${session.name}`;
              const menu = openMenu === menuKey
                ? h("div", { class: "rail-menu" },
                  menuButton(t("dock.renameSession"), () => {
                    openMenu = null;
                    props.onRenameSession(session.name);
                  }, `rail-session-rename:${session.name}`),
                  menuButton(t("dock.exportSession"), () => {
                    openMenu = null;
                    props.onExportSession(session.name);
                  }, `rail-session-export:${session.name}`),
                  menuButton(t("rail.session.archive"), () => {
                    openMenu = null;
                    props.onArchiveSession(session.name);
                  }, `rail-session-archive:${session.name}`, true),
                  confirmSessionDel === session.name
                    ? menuButton(t("rail.session.deleteOk"), () => {
                        confirmSessionDel = null;
                        openMenu = null;
                        props.onDeleteSession(session.name);
                      }, `rail-session-delete-ok:${session.name}`)
                    : menuButton(t("rail.session.delete"), () => {
                        confirmSessionDel = session.name;
                        paint();
                      }, `rail-session-delete:${session.name}`))
                : null;
              const fragNode = (f: RailFragRow): HTMLElement => h("button", {
                class: "rail-frag",
                attrs: { type: "button", "data-st": `rail-frag:${f.unitId}`, title: f.goal },
                onClick: () => { props.onOpenFragment?.(f.unitId); },
              },
                h("i", { class: `dot ${f.status === "ok" ? "ok" : f.status === "failed" ? "bad" : "run"}` }),
                h("span", { class: "dom-tag", text: f.domain }),
                h("span", { class: "rail-frag-label", text: f.goal }));
              const railRounds = props.activeSession === session.name
                ? deriveRailRounds(props.rounds ?? []) : [];
              const treeNodes: HTMLElement[] = [];
              if (railRounds.length >= 2) {
                for (const r of railRounds) {
                  treeNodes.push(h("div", {
                    class: "rail-round",
                    text: t("rail.roundLabel", { n: String(r.round), label: r.label }),
                  }));
                  for (const f of r.fragments) treeNodes.push(fragNode(f));
                }
              } else if (railRounds[0]) {
                for (const f of railRounds[0].fragments) treeNodes.push(fragNode(f));
              }
              const tree = treeNodes.length === 0 ? null
                : h("div", { class: "rail-frag-tree", dataset: { st: "rail-frag-tree" } }, ...treeNodes);
              return h("div", { class: "rail-item-wrap" },
                h("button", {
                  class: props.activeSession === session.name
                    ? "rail-item rail-session active" : "rail-item rail-session",
                  attrs: {
                    type: "button", "data-st": `rail-session:${session.name}`,
                    title: session.title,
                  },
                  onClick: () => { props.onSelectSession(session.name); },
                },
                  h("span", { class: "rail-name", text: session.title }),
                  session.branchedFrom !== null
                    ? h("span", {
                        class: "rail-branch",
                        attrs: {
                          "data-st": `rail-branch:${session.name}`,
                          title: t("rail.branchFrom", {
                            source: session.branchedFrom.source,
                            round: String(session.branchedFrom.fromRound),
                          }),
                        },
                        text: "↳",
                      })
                    : null,
                  h("span", { class: "rail-status", text: session.detail.split(" · ")[0] ?? "" })),
                h("button", {
                  class: "rail-more",
                  attrs: {
                    type: "button", "data-st": `rail-session-more:${session.name}`,
                    title: t("rail.menu.more"),
                    "aria-label": t("rail.menu.more"),
                  },
                  onClick: () => {
                    openMenu = openMenu === menuKey ? null : menuKey;
                    recycleOpen = false;
                    paint();
                  },
                }, svgIcon(ICON_MORE)),
                menu, tree);
            }))),
      ),
      h("div", { class: "rail-note", attrs: { hidden: "hidden" } }),
      h("div", { class: "rail-foot" },
        noticesButton("foot"),
        footButton(ICON_SETTINGS, "open-settings", t("app.settings"),
          () => { props.onOpenSettings(); }, "foot"),
        h("button", {
          attrs: { type: "button", "data-st": "rail-recycle", title: t("rail.recycle"), "aria-label": t("rail.recycle") },
          onClick: () => {
            recycleOpen = !recycleOpen;
            noticesOpen = false;
            openMenu = null;
            if (recycleOpen) props.onRecycleOpen();
            paint();
          },
        }, svgIcon(ICON_RECYCLE))),
      ...recyclePopover(),
      ...noticesPopover(),
    ];
  }

  function paint(): void {
    mount(root, ...inner());
    placePopovers();
  }

  /** 收起/展开（旧壳同款时序：内容淡出 150ms → 轨道滑动 → 导轨图标滑入 150ms）。 */
  function toggle(): void {
    if (animating) return;
    animating = true;
    if (!isCollapsed()) {
      root.classList.add("rail-fading");
      setTimeout(() => {
        if (narrow) {
          drawerOpen = false;
        } else {
          collapsed = true;
          saveCollapsed(true);
        }
        root.classList.remove("rail-fading");
        root.classList.add("collapsed");
        paint();
        root.classList.add("rail-in");
        animating = false;
        setTimeout(() => { root.classList.remove("rail-in"); }, 320);
      }, 150);
      return;
    }
    if (narrow) {
      drawerOpen = true;
    } else {
      collapsed = false;
      saveCollapsed(false);
    }
    root.classList.remove("collapsed");
    paint();
    root.classList.add("rail-wide-in");
    animating = false;
    setTimeout(() => { root.classList.remove("rail-wide-in"); }, 240);
  }

  root.classList.toggle("collapsed", isCollapsed());
  const onResize = (): void => {
    const nextNarrow = window.innerWidth <= 768;
    if (nextNarrow !== narrow) {
      narrow = nextNarrow;
      drawerOpen = false;
      root.classList.toggle("collapsed", isCollapsed());
      paint();
    }
  };
  window.addEventListener("resize", onResize);
  paint();

  return {
    update(next: RailProps): void {
      props = next;
      paint();
    },
    openCreateDialog(prefill?: string): void {
      if (typeof prefill === "string" && prefill !== "") {
        createDraft = prefill;   // 回退时预填上次选定/输入（选择不丢失）
      }
      addOpen = false;
      dialogOpen = true;
      addError = "";
      paint();
    },
    dispose(): void {
      document.removeEventListener("click", onDocPointer, false);
      window.removeEventListener("resize", onResize);
      root.remove();
    },
  };
}
