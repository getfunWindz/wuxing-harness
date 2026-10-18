/** 报告内嵌查看（M7 挂账 C）：modal 卡片 + report-md 排版 + 新页打开。 */
import { h, svgIcon } from "../render/dom.ts";
import { renderMarkdown } from "./markdown.ts";
import { ICON_CLOSE } from "./icons.ts";
import { t } from "./i18n.ts";

export function openReportModal(
  host: HTMLElement,
  title: string,
  markdown: string,
  url: string,
): void {
  const overlay = h("div", { class: "modal-overlay", attrs: { "data-st": "report-modal",
    role: "dialog", "aria-modal": "true", "aria-label": title } });

  function close(): void {
    document.removeEventListener("keydown", onKey);
    overlay.remove();
  }
  function onKey(ev: KeyboardEvent): void {
    if (ev.key === "Escape") close();
  }

  overlay.appendChild(h("div", { class: "modal-card report-card" },
    h("div", { class: "modal-head" },
      h("b", { text: title }),
      h("a", {
        class: "modal-x",
        attrs: { href: url, target: "_blank", rel: "noopener" },
        text: t("report.openNew"),
      }),
      h("button", {
        class: "modal-x", attrs: { type: "button", "data-st": "report-close" },
        onClick: () => { close(); },
      }, svgIcon(ICON_CLOSE))),
    h("div", { class: "modal-body" }, renderMarkdown(markdown))));

  overlay.addEventListener("click", (ev) => { if (ev.target === overlay) close(); });
  document.addEventListener("keydown", onKey);
  host.appendChild(overlay);
}
