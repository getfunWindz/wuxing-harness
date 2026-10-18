import { test } from "node:test";
import assert from "node:assert/strict";

import { ServiceRegistry, serviceToken } from "../src/runtime/kernel/services.ts";
import { defineModule, ModuleHost } from "../src/runtime/kernel/modules.ts";

test("依赖齐备才激活（多轮扫描，声明顺序无关）", () => {
  const host = new ModuleHost(new ServiceRegistry());
  const order: string[] = [];
  host.register(defineModule({ id: "b", deps: ["a"], setup: () => { order.push("b"); } }));
  host.register(defineModule({ id: "a", setup: () => { order.push("a"); } }));
  const report = host.activateAll();
  assert.deepEqual(report.active, ["a", "b"]);
  assert.deepEqual(order, ["a", "b"]);
  assert.deepEqual(report.skipped, []);
});

test("依赖缺失 → 保持未激活", () => {
  const host = new ModuleHost(new ServiceRegistry());
  host.register(defineModule({ id: "x", deps: ["missing"], setup: () => {} }));
  const report = host.activateAll();
  assert.deepEqual(report.active, []);
  assert.deepEqual(report.skipped, ["x"]);
});

test("setup 抛错 → failed，不阻塞其余模块", () => {
  const host = new ModuleHost(new ServiceRegistry());
  host.register(defineModule({ id: "bad", setup: () => { throw new Error("boom"); } }));
  host.register(defineModule({ id: "good", setup: () => {} }));
  const report = host.activateAll();
  assert.deepEqual(report.active, ["good"]);
  assert.equal(report.failed.length, 1);
  assert.equal(report.failed[0]?.id, "bad");
  assert.equal(host.stateOf("bad"), "failed");
});

test("重复注册失败", () => {
  const host = new ModuleHost(new ServiceRegistry());
  host.register(defineModule({ id: "m", setup: () => {} }));
  assert.throws(() => host.register(defineModule({ id: "m", setup: () => {} })), /重复注册/);
});

test("两阶段卸载：服务先注销、资源 LIFO 逆序释放", () => {
  const registry = new ServiceRegistry();
  const host = new ModuleHost(registry);
  const token = serviceToken<string>("x");
  const log: string[] = [];
  host.register(defineModule({
    id: "m",
    setup: (ctx) => {
      ctx.provide(token, "v");
      ctx.effect(() => log.push("effect-1"));
      ctx.effect(() => log.push("effect-2"));
    },
  }));
  host.activateAll();
  assert.equal(registry.has(token), true);
  host.disposeAll();
  assert.equal(registry.has(token), false);
  assert.deepEqual(log, ["effect-2", "effect-1"]);
});
