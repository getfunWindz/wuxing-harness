import { test } from "node:test";
import assert from "node:assert/strict";

import { createProjection } from "../src/runtime/projection/store.ts";

test("seq 单调：旧序拒绝、新序生效", () => {
  const projection = createProjection<number>(0);
  assert.equal(projection.apply(2, (v) => v + 1), true);
  assert.equal(projection.apply(1, (v) => v + 100), false);
  assert.equal(projection.get(), 1);
  assert.equal(projection.apply(3, (v) => v + 1), true);
  assert.equal(projection.get(), 2);
});

test("订阅收到通知 + 可退订", () => {
  const projection = createProjection<string>("a");
  const seen: string[] = [];
  const unsubscribe = projection.subscribe((value) => { seen.push(value); });
  projection.apply(1, () => "b");
  unsubscribe();
  projection.apply(2, () => "c");
  assert.deepEqual(seen, ["b"]);
});

test("seed 不降低已有 seq；reset 清空", () => {
  const projection = createProjection<number>(0);
  projection.apply(5, (v) => v + 1);
  projection.seed(42, 3);
  assert.equal(projection.apply(4, (v) => v + 1), false);
  projection.reset();
  assert.equal(projection.get(), 0);
  assert.equal(projection.apply(1, (v) => v + 1), true);
});
