/** fold 折叠状态纯逻辑（Wave-2 T7）。
 *
 * 与 fold.ts 拆分：纯函数可在 node:test 覆盖（DOM 应用由 fold.ts/E2E 验证）。
 */
export type FoldAction = "toggle" | "open" | "close";

/** 状态迁移：toggle 翻转；open/close 定向且幂等。 */
export function nextFoldState(current: boolean, action: FoldAction): boolean {
  if (action === "toggle") return !current;
  return action === "open";
}
