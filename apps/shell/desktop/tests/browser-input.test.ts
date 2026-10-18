/** TDD · O2-2 P2：输入坐标换算（纯函数）。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { quadsToPoint, serializeValue } = require("../dist/browser-input.js") as
  typeof import("../src/browser-input.ts");

test("quadsToPoint：中心 − 滚动偏移；空 → null", () => {
  const quad = [10, 20, 110, 20, 110, 60, 10, 60]; // 100x40 → 中心 (60,40)
  assert.deepEqual(quadsToPoint([quad], { pageX: 0, pageY: 0 }), {
    x: 60,
    y: 40,
  });
  assert.deepEqual(quadsToPoint([quad], { pageX: 5, pageY: 7 }), {
    x: 55,
    y: 33,
  });
  assert.equal(quadsToPoint([], { pageX: 0, pageY: 0 }), null);
  assert.equal(quadsToPoint([[1, 2, 3]], { pageX: 0, pageY: 0 }), null);
});

test("serializeValue：字符串直出/JSON/undefined/循环回退", () => {
  assert.equal(serializeValue("abc"), "abc");
  assert.equal(serializeValue(3), "3");
  assert.equal(serializeValue(true), "true");
  assert.equal(serializeValue(null), "null");
  assert.equal(serializeValue(undefined), "undefined");
  assert.equal(serializeValue({ a: 1 }), '{"a":1}');
  const circular: Record<string, unknown> = {};
  circular.self = circular;
  assert.equal(typeof serializeValue(circular), "string");
});
