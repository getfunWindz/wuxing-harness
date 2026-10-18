/** 零态（欢迎页）推导（单一真相 · Wave-2 T1）：选择 ＞ 意图 ＞ 任务流。
 *
 * 用户裁决/DSH 对齐（2026-10-01）：hero 只在"确实没有可显示对象"时出现：
 *  - activeSession !== null → 永不 hero（含空会话/装载中——空会话是合法会话视图）；
 *  - 未选会话时：有新建意图或确无任务 → hero；任务在途（提交在途）→ 任务流。
 *
 * 修 Bug#1：onNewSession 置 newSession=true 后 openSession 未清除 → 选中会话仍弹 hero；
 * 本函数以"选择"为最高优先，兜底该双源冲突（openSession 同步清 newSession 为双保险）。
 */
export interface ZeroStateInput {
  readonly activeSession: string | null;
  readonly newSession: boolean;
  readonly taskEmpty: boolean;
  readonly sessionHasContent: boolean;   // 保留入参（调用方仍计算）——推导不再依赖
}

export function deriveZeroState(input: ZeroStateInput): boolean {
  if (input.activeSession !== null) return false;
  return input.newSession || input.taskEmpty;
}
