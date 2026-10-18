/** 模式栏组件（双模式批 1）：输入区上方的模式 chip + 当前态会话标签。
 *
 * 行为（设计 §3/§4/§8）：
 * - chip 显示当前模式（`data-st="mode-chip"`）；点击展开三项选择
 *   （`data-st="mode-pick:<id>"`——极简·纯净 / 极简·标准 / 循迹）。
 * - **仅空白会话可切**：非空白时点选 → 内联提示（`data-st="mode-locked-tip"`）；
 *   服务端 422 `session/not-blank` 为机制守卫（壳提示不替代守卫）。
 * - 选择器显隐由设置 `mode_picker_enabled` 控制（visible=false → 整栏隐藏）。
 * - 会话标签（`data-st="session-mode-tag"`）与 chip 同源（当前模式）。
 */
import { h, mount } from "../render/dom.ts";
import type { ComponentInstance } from "../render/component.ts";
import { t } from "../views/i18n.ts";

export interface ModeBarProps {
  /** 当前模式 id（minimal-pure / minimal-standard / theroad） */
  current: string;
  /** 空白会话才可切（机制守卫的服务端口径在 API） */
  editable: boolean;
  /** picker_enabled && 工作区就绪 */
  visible: boolean;
  onPick(id: string): void;
}

export type ModeBarInstance = ComponentInstance<ModeBarProps>;

/** 三项选择器条目（顺序即呈现顺序——与服务端解析同口径）。 */
export const MODE_IDS = ["minimal-pure", "minimal-standard", "theroad"] as const;

export function createModeBar(host: HTMLElement,
                              initial: ModeBarProps): ModeBarInstance {
  let props = initial;
  let open = false;
  let hint = false;

  const chip = h("button", {
    class: "mode-chip",
    attrs: { type: "button", "data-st": "mode-chip" },
    onClick: () => { open = !open; paint(); },
  });
  const pop = h("div", { class: "mode-pop" });
  const locked = h("span", {
    class: "mode-hint", attrs: { "data-st": "mode-locked-tip" },
  });
  const tag = h("span", {
    class: "session-mode-tag", attrs: { "data-st": "session-mode-tag" },
  });
  const root = h("div", { class: "mode-bar" },
    chip, locked, h("span", { class: "grow" }), tag, pop);
  host.appendChild(root);

  const onDocPointer = (ev: PointerEvent): void => {
    if (!open) return;
    if (root.contains(ev.target as Node)) return;
    open = false;
    paint();
  };
  document.addEventListener("pointerdown", onDocPointer, true);

  function paint(): void {
    root.hidden = !props.visible;
    const label = t(`mode.label.${props.current}`);
    chip.textContent = `${label} ▾`;
    chip.title = t("mode.chipTip");
    tag.textContent = t("mode.tag", { label });
    locked.hidden = !(hint && props.visible);
    locked.textContent = locked.hidden ? "" : t("mode.locked");
    mount(pop, ...(open && props.visible
      ? [h("div", { class: "mode-pop-card" },
          ...MODE_IDS.map((id) => h("button", {
            class: id === props.current ? "mode-opt on" : "mode-opt",
            attrs: { type: "button", "data-st": `mode-pick:${id}` },
            onClick: () => {
              if (!props.editable) {
                hint = true;
                open = false;
                paint();
                return;
              }
              hint = false;
              open = false;
              props.onPick(id);
              paint();
            },
          },
            h("span", { class: "mode-opt-label", text: t(`mode.label.${id}`) }),
            h("span", { class: "mode-opt-desc", text: t(`mode.desc.${id}`) }))))]
      : []));
  }

  const update = (next: ModeBarProps): void => {
    props = next;
    paint();
  };
  update(initial);

  return {
    update,
    dispose(): void {
      document.removeEventListener("pointerdown", onDocPointer, true);
      root.remove();
    },
  };
}
