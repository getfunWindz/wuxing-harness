import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";

test("命令生命周期：pending → success", async () => {
  const bus = createCommandBus();
  const events: string[] = [];
  bus.subscribe((event) => { events.push(`${event.name}:${event.state}`); });
  const value = await bus.run("demo", async () => 42);
  assert.equal(value, 42);
  assert.deepEqual(events, ["demo:pending", "demo:success"]);
  assert.equal(bus.pendingCount(), 0);
});

test("失败：事件 + 重抛 + 全局失败钩子", async () => {
  const failures: string[] = [];
  const bus = createCommandBus((event) => { failures.push(event.error ?? ""); });
  const events: string[] = [];
  bus.subscribe((event) => { events.push(event.state); });
  await assert.rejects(bus.run("boom", async () => { throw new Error("坏了"); }), /坏了/);
  assert.deepEqual(events, ["pending", "failure"]);
  assert.deepEqual(failures, ["坏了"]);
  assert.equal(bus.pendingCount(), 0);
});
