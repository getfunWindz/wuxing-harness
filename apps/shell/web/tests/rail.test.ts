import { test } from "node:test";
import assert from "node:assert/strict";

import { deriveRailRows } from "../src/views/view-model.ts";

const LIST = [
  { id: "w1", path: "/a", name: "工作区一", auto_confirm: false, status: "idle", folder: null },
  { id: "w2", path: "/b", name: "ws-two", auto_confirm: false, status: "running", folder: null },
] as const;

test("deriveRailRows：标签/激活/状态文案", () => {
  const rows = deriveRailRows([...LIST], "w2");
  assert.equal(rows.length, 2);
  assert.deepEqual(rows.map((r) => r.label), ["工作区一", "ws-two"]);
  assert.deepEqual(rows.map((r) => r.active), [false, true]);
  assert.equal(rows[0]!.statusLabel, "就绪");
  assert.equal(rows[1]!.statusLabel, "运行中");
});

test("deriveRailRows：无激活工作区时全部非激活", () => {
  const rows = deriveRailRows([...LIST], null);
  assert.deepEqual(rows.map((r) => r.active), [false, false]);
});
