import { test } from "node:test";
import assert from "node:assert/strict";

import {
  ServiceRegistry,
  serviceToken,
} from "../src/runtime/kernel/services.ts";

test("provide/resolve 往返 + 撤销后不可解析", () => {
  const registry = new ServiceRegistry();
  const token = serviceToken<{ name: string }>("demo");
  const dispose = registry.provide(token, { name: "wuxing" });
  assert.equal(registry.resolve(token).name, "wuxing");
  dispose();
  assert.equal(registry.has(token), false);
  assert.throws(() => registry.resolve(token), /服务未注册/);
});

test("重复注册直接失败", () => {
  const registry = new ServiceRegistry();
  const token = serviceToken<number>("n");
  registry.provide(token, 1);
  assert.throws(() => registry.provide(token, 2), /服务已注册/);
});
