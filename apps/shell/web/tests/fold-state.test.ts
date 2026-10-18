/** TDD · Wave-2 T7：fold 折叠原语纯逻辑（状态迁移）。
 *
 * 目的：以 grid-rows 0fr↔1fr 动画统一全壳折叠件（替代 <details> 原生跳变）；
 * 受控语义——状态迁移经纯函数（DOM 应用在 fold.ts；E2E 验证形态）。
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { nextFoldState } from "../src/render/fold-state.ts";

test("nextFoldState：toggle 翻转 / open / close 定向", () => {
  assert.equal(nextFoldState(false, "toggle"), true);
  assert.equal(nextFoldState(true, "toggle"), false);
  assert.equal(nextFoldState(false, "open"), true, "open 幂等");
  assert.equal(nextFoldState(true, "open"), true);
  assert.equal(nextFoldState(true, "close"), false, "close 幂等");
  assert.equal(nextFoldState(false, "close"), false);
});
