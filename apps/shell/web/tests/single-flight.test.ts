import { test } from "node:test";
import assert from "node:assert/strict";

import { createSingleFlight } from "../src/views/single-flight.ts";

function deferred<T>(): { promise: Promise<T>; resolve: (v: T) => void } {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((res) => { resolve = res; });
  return { promise, resolve };
}

test("single-flight：进行中忽略再次调用；完成后恢复可用", async () => {
  const d = deferred<string>();
  let runs = 0;
  const run = createSingleFlight(async () => { runs += 1; return d.promise; });
  const first = run();
  assert.notEqual(first, null, "首次调用必须执行");
  const second = run();
  assert.equal(second, null, "进行中再次调用必须被忽略（防双击）");
  assert.equal(runs, 1, "底层仅执行一次");
  d.resolve("ok");
  assert.equal(await first, "ok");
  const third = run();
  assert.notEqual(third, null, "完成后允许再次调用");
  d.resolve("done"); // 第三次共享同一个 deferred——仅为解开挂起
  await third;
});

test("single-flight：失败后守卫释放（不永久卡死）", async () => {
  let calls = 0;
  const run = createSingleFlight(async () => {
    calls += 1;
    if (calls === 1) throw new Error("boom");
    return "ok";
  });
  await assert.rejects(async () => { await run(); }, /boom/);
  const again = run();
  assert.notEqual(again, null, "失败后必须允许重试");
  assert.equal(await again, "ok");
});

test("single-flight：同步抛错同样释放守卫", async () => {
  let calls = 0;
  const run = createSingleFlight((): Promise<never> => {
    calls += 1;
    throw new Error("sync-boom");
  });
  await assert.rejects(async () => { await run(); }, /sync-boom/);
  const again = run();
  assert.notEqual(again, null, "同步抛错也要释放");
  await assert.rejects(async () => { await again; }, /sync-boom/);
  assert.equal(calls, 2);
});
