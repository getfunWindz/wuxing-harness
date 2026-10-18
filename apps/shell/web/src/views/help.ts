/** 帮助弹窗（外观复现 A9 / M7 挂账 A 关闭）：步骤说明 + 快捷键键帽。
    以宿主层追加（overlay 自管理）；Esc / 遮罩点击 / × 关闭。 */
import { h, svgIcon } from "../render/dom.ts";
import { ICON_CLOSE } from "./icons.ts";
import { t } from "./i18n.ts";

export function openHelp(host: HTMLElement): void {
  const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;   // T-3：关闭归还
  const overlay = h("div", { class: "modal-overlay",
    attrs: { "data-st": "help", role: "dialog", "aria-modal": "true",
             "aria-label": t("help.title") } });

  function close(): void {
    document.removeEventListener("keydown", onKey);
    overlay.remove();
    if (opener !== null && opener.isConnected) opener.focus();   // T-3：触发者归位
  }
  function onKey(ev: KeyboardEvent): void {
    if (ev.key === "Escape") close();
  }

  const keys: [string, string][] = [
    ["⌘K / Ctrl+K", t("help.key.palette")],
    ["Enter", t("help.key.submit")],
    ["Shift+Enter", t("help.key.newline")],
    ["Alt+↓ / Alt+↑", t("help.key.confirmNav")],
    ["Alt+X", t("help.key.confirmCheck")],
    ["Alt+A", t("help.key.confirmAll")],
    ["Alt+Y / Alt+N", t("help.key.confirmDecide")],
    ["Esc", t("help.key.close")],
  ];

  const closeBtn = h("button", {
    class: "modal-x", attrs: { type: "button", "data-st": "help-close" },
    onClick: () => { close(); },
  }, svgIcon(ICON_CLOSE));
  const card = h("div", { class: "modal-card help-card" },
    h("div", { class: "modal-head" },
      h("b", { text: t("help.title") }),
      closeBtn),
    h("div", { class: "modal-body" },
      h("div", { class: "help-step" },
        h("b", { text: t("help.step1") }), h("span", { text: t("help.step1Desc") })),
      h("div", { class: "help-step" },
        h("b", { text: t("help.step2") }), h("span", { text: t("help.step2Desc") })),
      h("div", { class: "help-step" },
        h("b", { text: t("help.step3") }), h("span", { text: t("help.step3Desc") })),
      h("div", { class: "help-title", text: t("help.keys") }),
      ...keys.map(([key, desc]) => h("div", { class: "help-key" },
        h("kbd", { text: key }), h("span", { text: desc })))));

  overlay.appendChild(card);
  overlay.addEventListener("click", (ev) => { if (ev.target === overlay) close(); });
  document.addEventListener("keydown", onKey);
  host.appendChild(overlay);
  closeBtn.focus();   // T-3：打开即聚焦模态内（键盘可达）
}
