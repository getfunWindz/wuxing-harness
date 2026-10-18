/** fold 折叠原语（Wave-2 T7）：grid-rows 0fr↔1fr 动画 + aria-expanded/hidden 双轨。
 *
 * 用途：统一全壳收起/展开动画（替代 <details> 原生跳变——T8 迁移）。
 * 受控语义：外部可 setOpen()；点击头 → 状态经 nextFoldState 迁移后应用并
 * onToggle 通知（调用方可覆盖——策略归调用方）。
 * 无障碍：head 为 button（键盘可达）+ aria-expanded；body 容器 aria-hidden。
 * 布局：body 外包 .fold-body（display:grid）——动画不改变文档流稳定。
 */
import { h } from "./dom.ts";
import { nextFoldState, type FoldAction } from "./fold-state.ts";

export interface FoldOptions {
  /** 触发头（点击/键盘开合——建议 button）。 */
  readonly head: HTMLElement;
  /** 折叠体（内容容器）。 */
  readonly body: HTMLElement;
  readonly open?: boolean;
  /** 状态变化通知（受控使用：调用方决定是否 setOpen 覆盖）。 */
  readonly onToggle?: (open: boolean) => void;
}

export interface FoldInstance {
  readonly root: HTMLElement;
  setOpen(open: boolean): void;
  isOpen(): boolean;
}

export function createFold(options: FoldOptions): FoldInstance {
  let open = options.open ?? false;
  const head = options.head;
  const body = options.body;
  const bodyWrap = h("div", { class: "fold-body" }, body);
  const root = h("div", { class: "fold" }, head, bodyWrap);

  const apply = (): void => {
    root.classList.toggle("open", open);
    head.setAttribute("aria-expanded", open ? "true" : "false");
    bodyWrap.setAttribute("aria-hidden", open ? "false" : "true");
  };

  const transition = (action: FoldAction, notify: boolean): void => {
    open = nextFoldState(open, action);
    apply();
    if (notify) options.onToggle?.(open);   // Wave-2 T9：程序性 setOpen 不通知
  };

  head.addEventListener("click", (ev) => {
    ev.preventDefault();
    transition("toggle", true);
  });
  apply();

  return {
    root,
    setOpen(next: boolean): void {
      if (next === open) return;            // 幂等（重复 paint 不触发动效/通知）
      transition(next ? "open" : "close", false);
    },
    isOpen(): boolean {
      return open;
    },
  };
}
