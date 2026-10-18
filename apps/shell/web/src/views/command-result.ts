/** E2-UI：扩展命令结果卡片（命令名 + 状态 + 文本/错误；Esc/遮罩关闭；可复制）。
    —— 用户裁决 Q1：结果以卡片呈现（长文本可读），而非瞬时 toast。 */
import { h, svgIcon } from "../render/dom.ts";
import { ICON_CLOSE } from "./icons.ts";
import { t } from "./i18n.ts";

export interface CommandResultOptions {
  /** 显示标题（命令描述或名称）。 */
  title: string;
  status: string;
  text: string;
  error: string;
}

export function openCommandResult(host: HTMLElement,
                                  opts: CommandResultOptions): void {
  const overlay = h("div", { class: "modal-overlay",
                             attrs: { "data-st": "cmd-result", role: "dialog",
                                      "aria-modal": "true", "aria-label": opts.title } });

  function close(): void {
    document.removeEventListener("keydown", onKey);
    overlay.remove();
  }
  function onKey(ev: KeyboardEvent): void {
    if (ev.key === "Escape") close();
  }

  const ok = opts.status === "ok";
  const copyPayload = opts.error !== "" ? opts.error : opts.text;
  const copyBtn = h("button", {
    class: "modal-x",
    attrs: { type: "button", "data-st": "cmd-result-copy" },
    text: t("cmd.result.copy"),
    onClick: () => {
      void navigator.clipboard.writeText(copyPayload).then(() => {
        copyBtn.textContent = t("cmd.result.copied");
      }, () => { /* 剪贴板不可用：静默（结果可见即可） */ });
    },
  });

  overlay.appendChild(h("div", { class: "modal-card cmd-result-card" },
    h("div", { class: "modal-head" },
      h("b", { text: opts.title }),
      h("span", {
        class: ok ? "cmd-result-status on" : "cmd-result-status bad",
        attrs: { "data-st": "cmd-result-status" },
        text: ok ? t("cmd.result.ok") : t("cmd.result.error"),
      }),
      copyBtn,
      h("button", {
        class: "modal-x",
        attrs: { type: "button", "data-st": "cmd-result-close" },
        onClick: () => { close(); },
      }, svgIcon(ICON_CLOSE))),
    h("div", { class: "modal-body" },
      opts.text !== ""
        ? h("pre", {
            class: "cmd-result-text",
            attrs: { "data-st": "cmd-result-text" },
            text: opts.text,
          })
        : null,
      opts.error !== ""
        ? h("div", {
            class: "st-err",
            attrs: { "data-st": "cmd-result-error" },
            text: opts.error,
          })
        : null)));
  overlay.addEventListener("click", (ev) => {
    if (ev.target === overlay) close();
  });
  document.addEventListener("keydown", onKey);
  host.appendChild(overlay);
}
