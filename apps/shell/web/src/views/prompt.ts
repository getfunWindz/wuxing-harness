/** 通用输入弹窗（P2-M1）：标题 + 输入 + 确定/取消（文件夹新建/重命名等）。 */
import { h, mount } from "../render/dom.ts";
import { t } from "./i18n.ts";

export interface PromptOptions {
  title: string;
  value?: string;
  onOk(value: string): Promise<void> | void;
}

let overlay: HTMLDivElement | null = null;

export function openPrompt(host: HTMLElement, options: PromptOptions): void {
  closePrompt();
  const root = h("div", { class: "prompt-overlay" }) as HTMLDivElement;
  overlay = root;
  const input = h("input", {
    class: "st-input",
    attrs: { type: "text", "data-st": "prompt-input",
             id: "prompt-input", name: "prompt-input" },
    value: options.value ?? "",
  }) as HTMLInputElement;
  const error = h("div", { class: "st-err", attrs: { hidden: "hidden" } });
  let busy = false;

  const submit = async (): Promise<void> => {
    const value = input.value.trim();
    if (value === "") {
      error.textContent = t("topbar.err.path");
      error.removeAttribute("hidden");
      return;
    }
    busy = true;
    try {
      await options.onOk(value);
      closePrompt();
    } catch (err) {
      error.textContent = err instanceof Error ? err.message : String(err);
      error.removeAttribute("hidden");
    } finally {
      busy = false;
    }
  };

  root.addEventListener("pointerdown", (ev) => {
    if (ev.target === root) closePrompt();
  });
  mount(root,
    h("div", { class: "prompt-card" },
      h("div", { class: "st-fl", text: options.title }),
      input,
      error,
      h("div", { class: "st-row" },
        h("button", {
          class: "st-btn", attrs: { type: "button", "data-st": "prompt-ok" },
          text: t("topbar.create"),
          onClick: () => { if (!busy) void submit(); },
        }),
        h("button", {
          class: "st-btn ghost", attrs: { type: "button", "data-st": "prompt-cancel" },
          text: t("settings.prov.cancel"),
          onClick: () => { closePrompt(); },
        }))));
  host.appendChild(root);
  input.focus();
}

export function closePrompt(): void {
  if (overlay !== null) {
    overlay.remove();
    overlay = null;
  }
}
