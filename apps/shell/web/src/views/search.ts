/** 全库搜索覆盖层（P2-M6）：任务文本 + 会话（名称/首部内容）。
    —— 入口：左栏搜索按钮 / 命令面板；220ms 防抖；点击结果由主装配决策导航。 */
import { h, mount } from "../render/dom.ts";
import type { SearchResultDto } from "../protocol/generated.ts";
import { t } from "./i18n.ts";
import { deriveSearchRows, type SearchRow } from "./view-model.ts";

export interface SearchHandlers {
  onQuery(query: string): Promise<SearchResultDto>;
  onPick(row: SearchRow): void;
}

let overlay: HTMLDivElement | null = null;
let timer: ReturnType<typeof setTimeout> | null = null;
let opener: HTMLElement | null = null;   // T-3：关闭时焦点归还

export function isSearchOpen(): boolean {
  return overlay !== null;
}

export function openSearch(
  host: HTMLElement,
  handlers: SearchHandlers,
  initialQuery = "",
): void {
  closeSearch();
  opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const root = h("div", { class: "search-overlay",
    attrs: { role: "dialog", "aria-modal": "true", "aria-label": t("search.placeholder") } }) as HTMLDivElement;
  overlay = root;
  const input = h("input", {
    class: "search-input",
    attrs: {
      type: "text", "data-st": "search-input",
      id: "search-input", name: "search",
      placeholder: t("search.placeholder"), spellcheck: "false",
    },
  }) as HTMLInputElement;
  const body = h("div", { class: "search-body" });
  let seq = 0;

  const hint = (): void => {
    mount(body, h("div", { class: "dock-empty", text: t("search.hint") }));
  };

  const run = async (query: string): Promise<void> => {
    const q = query.trim();
    if (q === "") {
      hint();
      return;
    }
    const mine = ++seq;
    mount(body, h("div", { class: "dock-empty", text: t("dock.loading") }));
    try {
      const result = await handlers.onQuery(q);
      if (overlay !== root || mine !== seq) return;
      const rows = deriveSearchRows(result);
      if (rows.length === 0) {
        mount(body, h("div", { class: "dock-empty", text: t("search.empty") }));
        return;
      }
      mount(body, ...rows.map((row, index) =>
        h("button", {
          class: "search-item",
          attrs: { type: "button", "data-st": `search-item:${index}` },
          onClick: () => {
            closeSearch();
            handlers.onPick(row);
          },
        },
          h("span", { class: "si-main", text: row.title }),
          h("span", {
            class: "si-meta",
            text: `${row.kind === "task" ? t("search.tasks") : t("search.sessions")} · ${row.meta}`,
          }))));
    } catch (err) {
      if (overlay !== root) return;
      mount(body, h("div", {
        class: "dock-error-msg",
        text: err instanceof Error ? err.message : String(err),
      }));
    }
  };

  input.addEventListener("input", () => {
    if (timer !== null) clearTimeout(timer);
    timer = setTimeout(() => { void run(input.value); }, 220);
  });
  input.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape") closeSearch();
  });
  root.addEventListener("pointerdown", (ev) => {
    if (ev.target === root) closeSearch();
  });
  mount(root, h("div", { class: "search-card" }, input, body));
  host.appendChild(root);
  input.focus();
  if (initialQuery !== "") {
    input.value = initialQuery;
    void run(initialQuery);
  } else {
    hint();
  }
}

export function closeSearch(): void {
  if (timer !== null) {
    clearTimeout(timer);
    timer = null;
  }
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
