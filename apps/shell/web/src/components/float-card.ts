/** 悬浮任务卡（外观复现 A8（二））：可拖动小卡 + 点击放大（旧壳 task-card.js 口径）。
    位置/展开态持久化 localStorage（wuxing.taskcard.v1）；#float-root 层由 main 提供。 */
import { h, svgIcon } from "../render/dom.ts";
import type { ComponentInstance } from "../render/component.ts";
import type { TaskState } from "../runtime/services/tasks.ts";
import { statusLabel } from "../views/view-model.ts";
import { deriveConcurrency, deriveEta, deriveFloatCardVisible, deriveFragmentDomains, deriveFscSummary, domainLabel } from "../views/view-model.ts";
import { ICON_CHEVRON, ICON_CLOSE } from "../views/icons.ts";
import { t } from "../views/i18n.ts";

const LS_KEY = "wuxing.taskcard.v1";
const MARGIN = 8;
const DRAG_THRESHOLD = 5;

export interface FloatCardProps {
  state: TaskState;
  /** 引擎并发上限（config.max_parallel_units；未知为 null） */
  maxParallel: number | null;
  /** 显示开关（设置中心可重开；关闭后全局隐藏） */
  enabled: boolean;
  onClose(): void;
}

interface Prefs {
  x: number | null;
  y: number | null;
  expanded: boolean;
}

function loadPrefs(): Prefs {
  try {
    return { x: null, y: null, expanded: false, ...JSON.parse(localStorage.getItem(LS_KEY) || "{}") };
  } catch (err) {
    void err; // 偏好不可用/损坏：以默认值启动（不阻断交互）
    return { x: null, y: null, expanded: false };
  }
}

function savePrefs(p: Prefs): void {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify(p));
  } catch (err) {
    void err; // 偏好不可用：内存态生效，不阻断交互
  }
}

/** 单元状态文案（碎片详情行）。 */
function unitStatusLabel(status: string): string {
  if (status === "ok") return t("status.done");
  if (status === "failed") return t("status.failed");
  if (status === "confirm") return t("status.pending");
  return t("status.running");
}

export function createFloatCard(
  host: HTMLElement,
  initial: FloatCardProps,
): ComponentInstance<FloatCardProps> {
  let props = initial;
  const prefs = loadPrefs();
  let fragsOpen = false;
  let drag: { sx: number; sy: number; ox: number; oy: number; moved: boolean } | null = null;

  const root = h("div", { class: "task-card" });
  host.appendChild(root);

  function place(): void {
    if (root.hidden) return;
    const w = root.offsetWidth || 240;
    const hgt = root.offsetHeight || 44;
    const x = prefs.x ?? Math.max(MARGIN, window.innerWidth - 320 - w - 16);
    const y = prefs.y ?? 64;
    root.style.left = `${Math.max(MARGIN, Math.min(x, window.innerWidth - w - MARGIN))}px`;
    root.style.top = `${Math.max(52, Math.min(y, window.innerHeight - hgt - MARGIN))}px`;
  }

  root.addEventListener("pointerdown", (ev) => {
    if (ev.button !== 0) return;
    if ((ev.target as HTMLElement).closest("[data-no-drag]")) return;   // 卡内按钮不触发拖动/展开
    const r = root.getBoundingClientRect();
    drag = { sx: ev.clientX, sy: ev.clientY, ox: r.left, oy: r.top, moved: false };
    root.setPointerCapture(ev.pointerId);
  });
  root.addEventListener("pointermove", (ev) => {
    if (!drag) return;
    const dx = ev.clientX - drag.sx;
    const dy = ev.clientY - drag.sy;
    if (Math.abs(dx) + Math.abs(dy) > DRAG_THRESHOLD) {
      drag.moved = true;
      root.classList.add("dragging");
    }
    if (drag.moved) {
      root.style.left = `${Math.max(MARGIN, Math.min(drag.ox + dx, window.innerWidth - root.offsetWidth - MARGIN))}px`;
      root.style.top = `${Math.max(52, Math.min(drag.oy + dy, window.innerHeight - root.offsetHeight - MARGIN))}px`;
    }
  });
  root.addEventListener("pointerup", () => {
    if (!drag) return;
    const moved = drag.moved;
    drag = null;
    root.classList.remove("dragging");
    if (moved) {
      prefs.x = parseFloat(root.style.left);
      prefs.y = parseFloat(root.style.top);
      savePrefs(prefs);
      return;
    }
    prefs.expanded = !prefs.expanded;
    savePrefs(prefs);
    paint();
  });
  root.addEventListener("pointercancel", () => {
    drag = null;
    root.classList.remove("dragging");
  });

  function paint(): void {
    const st = props.state;
    const visible = deriveFloatCardVisible(props.enabled, st);
    root.hidden = !visible;
    if (!visible) {
      root.replaceChildren();
      return;
    }
    if (!prefs.expanded) {
      root.replaceChildren(
        h("div", { class: "tc-compact" },
          h("span", { class: "tc-text", text: st.taskText || t("float.noTask") }),
          h("span", { class: "tc-chev" }, svgIcon(ICON_CHEVRON))));
    } else {
      const eta = deriveEta(st);
      const rows: [string, string][] = [
        [t("float.status"), statusLabel(st.status)],
        [t("float.fragments"), st.rows.length > 0
          ? `${st.rows.length}（${deriveFragmentDomains(st.rows)}）` : "—"],
        [t("float.fsc"), deriveFscSummary(st, st.result?.metrics)],
        [t("float.eta"), eta === "" ? t("float.etaReady") : eta],
        [t("float.artifacts"), String(st.unitArtifacts.length)],
        [t("float.concurrency"), deriveConcurrency(st, props.maxParallel)],
      ];
      root.replaceChildren(
        h("div", { class: "tc-head" },
          h("span", { text: t("float.title") }),
          h("span", { class: "tc-status", text: statusLabel(st.status) }),
          h("button", {
            class: "tc-close",
            attrs: {
              type: "button", "data-st": "float-close", title: t("float.close"),
              "data-no-drag": "",
            },
            onClick: () => { props.onClose(); },
          }, svgIcon(ICON_CLOSE))),
        h("div", { class: "tc-body" },
          h("p", { class: "tc-task", text: st.taskText || "—" }),
          ...rows.map(([key, value]) => h("div", { class: "tc-row" },
            h("span", { class: "tc-key", text: key }),
            h("span", { class: "tc-val", text: value }))),
          h("div", { class: "tc-frags" },
            ...st.rows.slice(0, 8).map((row) => h("span", { class: "frag-chip" },
              h("span", { class: `dot ${row.status === "ok" ? "ok" : row.status === "failed" ? "bad" : "run"}` }),
              h("span", { text: `${row.unitId} · ${domainLabel(row.domainId)}` })))),
          h("button", {
            class: "tc-frag-toggle",
            attrs: { type: "button", "data-st": "float-frags-toggle", "data-no-drag": "" },
            text: `${t("float.fragmentsDetail")}（${st.rows.length}）`,
            onClick: () => { fragsOpen = !fragsOpen; paint(); },
          }),
          fragsOpen
            ? (st.rows.length === 0
              ? h("div", { class: "tc-frag-empty", text: t("float.fragsEmpty") })
              : h("div", { class: "tc-frag-list", attrs: { "data-st": "float-frags-list" } },
                ...st.rows.map((row) => h("div", { class: "tc-frag-row" },
                  h("span", { class: `dot ${row.status === "ok" ? "ok" : row.status === "failed" ? "bad" : "run"}` }),
                  h("span", { class: "tfr-unit", attrs: { title: row.unitId }, text: row.unitId }),
                  h("span", { class: "tfr-domain", text: domainLabel(row.domainId) }),
                  h("span", { class: "tfr-status", text: unitStatusLabel(row.status) }),
                  h("span", { class: "tfr-detail", text: [row.eta !== "" ? `${t("float.eta")} ${row.eta}` : "", row.detail]
                    .filter((part) => part !== "").join(" · ") })))))
            : null));
      root.classList.add("expanded");
    }
    if (!prefs.expanded) root.classList.remove("expanded");
    place();
  }

  const onResize = (): void => { place(); };
  window.addEventListener("resize", onResize);

  const update = (next: FloatCardProps): void => {
    props = next;
    paint();
  };
  update(initial);

  return {
    update,
    dispose(): void {
      window.removeEventListener("resize", onResize);
      root.remove();
    },
  };
}
