/** 命令面板（⌘/Ctrl+K · P2-M6）：过滤 + ↑↓/Enter/Esc 全键盘（IME 组字守卫）。 */
import { h, mount } from "../render/dom.ts";
import { t } from "./i18n.ts";
import { filterPaletteCommands } from "./view-model.ts";

export interface PaletteCommand {
  readonly id: string;
  readonly title: string;
  readonly keywords?: string;
  run(): void;
}

let overlay: HTMLDivElement | null = null;
let keybound = false;
let opener: HTMLElement | null = null;   // T-3：关闭时焦点归还

/** 全局快捷键只绑定一次（幂等）。 */
export function initPalette(onOpen: () => void): void {
  if (keybound) return;
  keybound = true;
  document.addEventListener("keydown", (ev: KeyboardEvent) => {
    if ((ev.ctrlKey || ev.metaKey) && (ev.key === "k" || ev.key === "K")) {
      ev.preventDefault();
      onOpen();
    }
  });
}

export function isPaletteOpen(): boolean {
  return overlay !== null;
}

export function openPalette(host: HTMLElement, commands: readonly PaletteCommand[]): void {
  closePalette();
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const root = h("div", { class: "palette-overlay",
    attrs: { role: "dialog", "aria-modal": "true", "aria-label": t("palette.placeholder") } }) as HTMLDivElement;
  overlay = root;
  const input = h("input", {
    class: "palette-input",
    attrs: {
      type: "text", "data-st": "palette-input",
      id: "palette-input", name: "command",
      placeholder: t("palette.placeholder"), spellcheck: "false",
    },
  }) as HTMLInputElement;
  const list = h("div", { class: "palette-list" });
  let filtered = filterPaletteCommands(commands, "");
  let index = 0;

  const runCommand = (command: PaletteCommand): void => {
    closePalette();
    command.run();
  };

  const paint = (): void => {
    if (filtered.length === 0) {
      mount(list, h("div", { class: "dock-empty", text: t("palette.noMatch") }));
      return;
    }
    mount(list, ...filtered.map((command, i) =>
      h("button", {
        class: i === index ? "palette-item on" : "palette-item",
        attrs: { type: "button", "data-st": `palette-item:${i}` },
        onClick: () => { runCommand(command); },
      },
        h("span", { class: "pi-title", text: command.title }))));
  };

  input.addEventListener("input", () => {
    filtered = filterPaletteCommands(commands, input.value);
    index = 0;
    paint();
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.isComposing || ev.keyCode === 229) return; // IME 组字未结束——不响应
    if (ev.key === "ArrowDown") {
      ev.preventDefault();
      if (filtered.length > 0) { index = (index + 1) % filtered.length; paint(); }
    } else if (ev.key === "ArrowUp") {
      ev.preventDefault();
      if (filtered.length > 0) { index = (index - 1 + filtered.length) % filtered.length; paint(); }
    } else if (ev.key === "Enter") {
      ev.preventDefault();
      const command = filtered[index];
      if (command !== undefined) runCommand(command);
    } else if (ev.key === "Escape") {
      ev.preventDefault();
      closePalette();
    }
  });
  root.addEventListener("pointerdown", (ev) => {
    if (ev.target === root) closePalette();
  });
  mount(root, h("div", { class: "palette-card" }, input, list));
  host.appendChild(root);
  input.focus();
  paint();
}

export function closePalette(): void {
  if (overlay !== null) {
    const inside = document.activeElement instanceof Node
      && overlay.contains(document.activeElement);
    overlay.remove();
    overlay = null;
    if (inside && opener !== null && opener.isConnected) {
      opener.focus();   // T-3：键盘/点击触发者归位
    }
  }
  opener = null;
}
