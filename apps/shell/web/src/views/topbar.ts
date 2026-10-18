/** 顶栏（外观复现 A3/A6/A9 → B4 属性栏可选展示）：品牌（渐隐+粉尘+飞白）+ 属性栏 + 帮助入口。
    B4：属性集对齐旧壳 10 项（conc/ws/cache/ctx/pending/reqHit/tokensIn/tokensOut/calls/fsc）；
    点信息栏打开属性卡（复选显隐，偏好由 main 持久化）。 */
import { h, mount, svgIcon } from "../render/dom.ts";
import type { ComponentInstance } from "../render/component.ts";
import { createBrand, mountBrandDust, mountBrandEtch } from "../components/brand.ts";
import { ICON_HELP } from "./icons.ts";
import { t } from "./i18n.ts";
import type { TopbarAttr, TopbarAttrId } from "./view-model.ts";

export interface TopbarProps {
  attrs: readonly TopbarAttr[];
  visible: readonly TopbarAttrId[];
  onToggleAttr(id: TopbarAttrId): void;
  onOpenHelp(): void;
}

export function createTopbar(host: HTMLElement, initial: TopbarProps): ComponentInstance<TopbarProps> {
  let props = initial;
  let cardOpen = false;

  const root = h("div", { class: "app-top" });
  host.appendChild(root);

  // 外点关闭属性卡（捕获阶段；打开动画的同一事件不误关——用 pointerdown 监听注册在捕获）
  const onDocPointer = (ev: PointerEvent): void => {
    if (!cardOpen) return;
    if (root.contains(ev.target as Node)) return;
    cardOpen = false;
    paint();
  };
  document.addEventListener("pointerdown", onDocPointer, true);

  function paint(): void {
    const byKey = new Map(props.attrs.map((attr) => [attr.key, attr]));
    const shown = props.visible
      .map((id) => byKey.get(id))
      .filter((attr): attr is TopbarAttr => attr !== undefined);
    mount(root,
      createBrand("sm"),
      h("span", { class: "grow" }),
      h("span", {
        class: "usage-bar",
        attrs: {
          title: t("topbar.card.title"), role: "button", tabindex: "0",
          "data-st": "topbar-card-toggle",
        },
        onClick: () => { cardOpen = !cardOpen; paint(); },
      }, ...shown.map((attr) =>
        h("span", {
          class: "u-item",
          attrs: {
            "data-attr": attr.key, title: attr.label,
            ...(attr.key === "ctx" && attr.band
                ? { "data-band": attr.band } : {}),
          },
        },
          h("span", { text: attr.label }),
          h("b", { text: attr.value }),
          attr.key === "ctx"
            && (attr.band === "golden" || attr.band === "managed")
            ? h("span", {
                class: `topbar-ctx-band ${attr.band}`,
                attrs: { "data-st": "topbar-ctx-band", "data-band": attr.band },
                text: t(`ctx.band.${attr.band}`),
              })
            : null))),
      h("button", {
        class: "tb-btn", attrs: { type: "button", "data-st": "open-help", title: t("help.title"), "aria-label": t("help.title") },
        onClick: () => { props.onOpenHelp(); },
      }, svgIcon(ICON_HELP)),
      cardOpen
        ? h("div", { class: "topbar-card", attrs: { "data-st": "topbar-card" } },
          h("div", { class: "topbar-card-head" },
            h("span", { text: t("topbar.card.title") }),
            h("span", { class: "topbar-card-desc", text: t("topbar.card.desc") })),
          ...props.attrs.map((attr) => {
            const on = props.visible.includes(attr.key);
            return h("button", {
              class: "topbar-card-item",
              attrs: { type: "button", "data-st": `topbar-attr:${attr.key}` },
              onClick: () => { props.onToggleAttr(attr.key); },
            },
              h("span", { class: on ? "tcc on" : "tcc" }),   /* 勾选用 CSS 绘制（emoji 纪律：不用对勾字符） */
              h("span", { class: "tc-label", text: attr.label }),
              h("span", { class: "tc-value", text: attr.value }));
          }))
        : null);
    // 属性卡：固定定位（逃逸顶栏 overflow:hidden 裁切——2026-09-19 修复）并对齐信息栏右缘
    if (cardOpen) {
      const bar = root.querySelector<HTMLElement>(".usage-bar");
      const card = root.querySelector<HTMLElement>(".topbar-card");
      if (bar && card) {
        const r = bar.getBoundingClientRect();
        card.style.top = `${Math.round(r.bottom + 6)}px`;
        card.style.right = `${Math.max(8, Math.round(window.innerWidth - r.right))}px`;
      }
    }
    mountBrandDust(root);
    mountBrandEtch(root);
  }

  paint();

  return {
    update(next: TopbarProps): void {
      props = next;
      paint();
    },
    dispose(): void {
      document.removeEventListener("pointerdown", onDocPointer, true);
      root.remove();
    },
  };
}
