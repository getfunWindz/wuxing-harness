/** 确认区键盘导航与批量键（T-4 · 安全键盘效率）。
    键位：Alt+↓/↑ 跳转 · Alt+X 勾选当前 · Alt+A 全选/清空 · Alt+Y 允许已选 · Alt+N 拒绝已选。
    安全语义：选择/导航不触发放行；允许/拒绝复用既有批量按钮路径（禁用与缺失原因守卫不变）。
    守卫：文本输入类控件内不触发（checkbox/按钮等非文本控件不拦截——导航目标本身是 checkbox；
    批量原因框仅对 Alt+N 豁免——「聚焦→输入→提交」同一路径）；
    palette/help/设置/命令弹层打开时不触发；IME 组字与已消费事件不触发；首末钳制不循环。 */
import { focusIndex, resolveConfirmKey } from "./view-model.ts";
import { isPaletteOpen } from "./palette.ts";

let keybound = false;

function overlayOpen(): boolean {
  return isPaletteOpen()
    || document.querySelector(".modal-overlay") !== null
    || document.querySelector(".settings-overlay:not([hidden])") !== null;
}

/** 文本输入类控件（打字中不抢键）——checkbox/button 等非文本控件不拦截（导航目标本身是 checkbox）。 */
function isTextEntry(target: EventTarget | null): boolean {
  const el = target instanceof HTMLElement ? target : null;
  if (el === null) return false;
  if (el.isContentEditable) return true;
  if (el.tagName === "TEXTAREA" || el.tagName === "SELECT") return true;
  if (el.tagName !== "INPUT") return false;
  const type = (el as HTMLInputElement).type;
  return type === "text" || type === "search" || type === "password"
    || type === "email" || type === "url" || type === "number" || type === "tel";
}

/** 可见待确认卡的勾选框（DOM 顺序 = 列表顺序；每次按键现查，防重渲染陈旧引用）。 */
function confirmBoxes(): HTMLInputElement[] {
  return [...document.querySelectorAll<HTMLInputElement>(
    ".stream-confirm-list .stream-confirm-row input[type='checkbox'][data-unit]",
  )].filter((el) => el.offsetParent !== null);
}

/** 批量按钮（不可见/禁用时视为不可达——与鼠标路径同守卫）。 */
function batchButton(st: string): HTMLButtonElement | null {
  const el = document.querySelector<HTMLButtonElement>(`[data-st="${st}"]`);
  if (el === null || el.disabled || el.offsetParent === null) return null;
  return el;
}

/** 全局快捷键只绑定一次（幂等——同 palette 范式）。 */
export function initConfirmKeys(): void {
  if (keybound) return;
  keybound = true;
  document.addEventListener("keydown", (ev: KeyboardEvent) => {
    const action = resolveConfirmKey(ev);
    if (action === null) return;
    const target = ev.target;
    const inBatchReason = target instanceof HTMLElement && target.id === "confirm-batch-reason";
    if (isTextEntry(target) && !(action === "reject" && inBatchReason)) return;
    if (overlayOpen()) return;
    const boxes = confirmBoxes();
    if (boxes.length === 0) return;
    const active = document.activeElement;
    const current = boxes.findIndex((box) =>
      box === active || box.closest(".stream-confirm-row")?.contains(active) === true);
    switch (action) {
      case "prev": case "next": {
        const next = focusIndex(current, boxes.length, action === "next" ? 1 : -1);
        if (next < 0 || next === current) return;
        const box = boxes[next];
        if (box === undefined) return;
        ev.preventDefault();
        box.scrollIntoView({ block: "nearest" });
        box.focus({ preventScroll: true });
        return;
      }
      case "toggle": {
        if (current < 0) return;
        const box = boxes[current];
        if (box === undefined) return;
        ev.preventDefault();
        box.click();
        return;
      }
      case "toggleAll": {
        ev.preventDefault();
        const allChecked = boxes.every((box) => box.checked);
        for (const box of boxes) {
          if (box.checked !== !allChecked) box.click();
        }
        return;
      }
      case "approve": {
        const btn = batchButton("confirm-batch-approve");
        if (btn === null) return;
        ev.preventDefault();
        btn.click();
        return;
      }
      case "reject": {
        const btn = batchButton("confirm-batch-reject");
        if (btn === null) return;
        ev.preventDefault();
        btn.click();
        return;
      }
    }
  });
}
