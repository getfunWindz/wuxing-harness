import { test } from "node:test";
import assert from "node:assert/strict";

import { createScheduler } from "../src/render/scheduler.ts";

test("批合并：多次 schedule 只触发一次底层调度", () => {
  const scheduled: Array<() => void> = [];
  const scheduler = createScheduler((callback) => { scheduled.push(callback); });
  const ran: string[] = [];
  scheduler.schedule(() => { ran.push("a"); });
  scheduler.schedule(() => { ran.push("b"); });
  assert.equal(scheduled.length, 1);
  scheduled[0]?.();
  assert.deepEqual(ran, ["a", "b"]);
  scheduler.schedule(() => { ran.push("c"); });
  assert.equal(scheduled.length, 2);
});
