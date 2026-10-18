/** TDD · Wave-2 T1：零态（欢迎页）推导单一真相——选择 ＞ 意图 ＞ 任务流。
 *
 * 用户裁决/DSH 对齐（2026-10-01）：hero 只在"确实没有可显示对象"时出现：
 *  - activeSession 非空 → 永不 hero（含空会话/装载中——空会话是合法会话视图）；
 *  - 未选会话时：有新建意图或确无任务 → hero；任务在途（提交在途）→ 任务流。
 * 修 Bug#1：onNewSession 置 newSession=true 且 openSession 不清除 → 选中会话仍弹初始页。
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { deriveZeroState } from "../src/views/zero-state.ts";

test("deriveZeroState：选择优先于意图（Bug#1）", () => {
  // 选中会话 → 一律非零态（不论 newSession/内容如何）
  assert.equal(deriveZeroState({ activeSession: "c1", newSession: true, taskEmpty: true, sessionHasContent: false }), false);
  assert.equal(deriveZeroState({ activeSession: "c1", newSession: false, taskEmpty: true, sessionHasContent: false }), false);
  // 未选会话：新建意图或无事可做 → 零态
  assert.equal(deriveZeroState({ activeSession: null, newSession: true, taskEmpty: true, sessionHasContent: false }), true);
  assert.equal(deriveZeroState({ activeSession: null, newSession: false, taskEmpty: true, sessionHasContent: false }), true);
  // 未选会话但有活跃任务（提交在途）→ 非零态（显示任务流）
  assert.equal(deriveZeroState({ activeSession: null, newSession: false, taskEmpty: false, sessionHasContent: false }), false);
});

test("deriveZeroState：空会话是合法会话视图（不弹 hero）", () => {
  assert.equal(deriveZeroState({ activeSession: "empty-sess", newSession: false, taskEmpty: true, sessionHasContent: false }), false);
});
