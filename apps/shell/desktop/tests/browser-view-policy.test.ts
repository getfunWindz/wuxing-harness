/** TDD · O2-2 §11.5-②：多视图纯策略（激活回退/LRU/前缀匹配——可单测，零 Electron）。 */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const {
  lruEvictions,
  nextActive,
  overlayKeysFor,
} = require("../dist/browser-view-policy.js") as typeof import("../src/browser-view-policy.ts");

test("nextActive：关闭活跃视图后回退次新；空则 null", () => {
  assert.equal(nextActive(["a", "b", "c"], "c"), "b");
  assert.equal(nextActive(["a", "b", "c"], "a"), "c");
  assert.equal(nextActive(["a"], "a"), null);
  assert.equal(nextActive([], "x"), null);
});

test("lruEvictions：超限淘汰最旧；在用途保留", () => {
  assert.deepEqual(lruEvictions(["a", "b", "c"], [], 2), ["a"]);
  assert.deepEqual(lruEvictions(["a", "b", "c"], ["a"], 2), ["b"]);
  assert.deepEqual(lruEvictions(["a", "b"], [], 2), []);
  assert.deepEqual(lruEvictions(["a", "b", "c", "d"], ["b"], 2), ["a", "c"]);
});

test("overlayKeysFor：base 与 base-<token> 命中；不吞并相似前缀", () => {
  const keys = ["k", "k-1", "k1", "k-2", "other"];
  assert.deepEqual(overlayKeysFor(keys, "k"), ["k", "k-1", "k-2"]);
  assert.deepEqual(overlayKeysFor(keys, "other"), ["other"]);
});
