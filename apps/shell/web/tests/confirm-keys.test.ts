import { test } from "node:test";
import assert from "node:assert/strict";

import { focusIndex, resolveConfirmKey } from "../src/views/view-model.ts";

const key = (code: string, mods: Partial<{
  altKey: boolean; ctrlKey: boolean; metaKey: boolean; shiftKey: boolean;
  isComposing: boolean; defaultPrevented: boolean;
}> = {}) => ({
  code, altKey: true, ctrlKey: false, metaKey: false, shiftKey: false, ...mods,
});

test("resolveConfirmKey：Alt+↓/↑/X/A/Y/N → 六动作", () => {
  assert.equal(resolveConfirmKey(key("ArrowDown")), "next");
  assert.equal(resolveConfirmKey(key("ArrowUp")), "prev");
  assert.equal(resolveConfirmKey(key("KeyX")), "toggle");
  assert.equal(resolveConfirmKey(key("KeyA")), "toggleAll");
  assert.equal(resolveConfirmKey(key("KeyY")), "approve");
  assert.equal(resolveConfirmKey(key("KeyN")), "reject");
});

test("resolveConfirmKey：修饰键/IME/已消费/无关键一律不匹配", () => {
  assert.equal(resolveConfirmKey(key("ArrowDown", { ctrlKey: true })), null);
  assert.equal(resolveConfirmKey(key("ArrowDown", { metaKey: true })), null);
  assert.equal(resolveConfirmKey(key("ArrowDown", { shiftKey: true })), null);
  assert.equal(resolveConfirmKey(key("ArrowDown", { altKey: false })), null);
  assert.equal(resolveConfirmKey(key("ArrowDown", { isComposing: true })), null);
  assert.equal(resolveConfirmKey(key("ArrowDown", { defaultPrevented: true })), null);
  assert.equal(resolveConfirmKey(key("KeyZ")), null);
});

test("focusIndex：空列表与首末钳制（不循环）", () => {
  assert.equal(focusIndex(0, 0, 1), -1);
  assert.equal(focusIndex(-1, 3, 1), 0);
  assert.equal(focusIndex(-1, 3, -1), 2);
  assert.equal(focusIndex(0, 3, -1), 0);
  assert.equal(focusIndex(2, 3, 1), 2);
  assert.equal(focusIndex(1, 3, 1), 2);
  assert.equal(focusIndex(1, 3, -1), 0);
});
