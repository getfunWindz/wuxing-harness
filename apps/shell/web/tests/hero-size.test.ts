/** TDD · Wave-2 T4：hero 输入框高度计算纯函数（隐藏态不得量测）。
 *
 * Bug#4（真机复现）：hero 隐藏时 offsetHeight=0，autoGrow 把 textarea 压成
 * 0 高度——切回新建会话时占位符不可见。修复：隐藏态不写内联高度；
 * 可见时按 scrollHeight 计算（回退自然高度 / 封顶）。
 */
import { test } from "node:test";
import assert from "node:assert/strict";

import { computeTextareaHeight } from "../src/views/hero-size.ts";

test("computeTextareaHeight：隐藏态不量测（Bug#4）", () => {
  assert.equal(computeTextareaHeight({ visible: false, scrollHeight: 0, max: 200 }), null);   // null=不改内联高度
  assert.equal(computeTextareaHeight({ visible: true, scrollHeight: 48, max: 200 }), "48px");
  assert.equal(computeTextareaHeight({ visible: true, scrollHeight: 999, max: 200 }), "200px");
  assert.equal(computeTextareaHeight({ visible: true, scrollHeight: 0, max: 200 }), "auto");
});
