import { test } from "node:test";
import assert from "node:assert/strict";

import { createCommandBus } from "../src/runtime/commands.ts";
import type { WritableRestClient } from "../src/runtime/connection/rest.ts";
import { createObserveService } from "../src/runtime/services/observe.ts";

function fakeRest(
  handler: (method: string, path: string, body?: unknown) => unknown,
): WritableRestClient {
  return {
    async get<T>(path: string): Promise<T> { return handler("GET", path) as T; },
    async post<T>(path: string, body?: unknown): Promise<T> { return handler("POST", path, body) as T; },
    async put<T>(path: string, body?: unknown): Promise<T> { return handler("PUT", path, body) as T; },
    async patch<T>(path: string, body?: unknown): Promise<T> { return handler("PATCH", path, body) as T; },
    async del<T>(path: string): Promise<T> { return handler("DELETE", path) as T; },
  };
}

test("observe：观测面端点路径与查询参数", async () => {
  const calls: string[] = [];
  const service = createObserveService({
    rest: fakeRest((_method, path) => { calls.push(path); return {}; }),
    commands: createCommandBus(),
  });
  await service.skills();
  await service.mcpStatus();
  await service.taskHistory("w1");
  await service.provenance("w1");
  await service.trace("w1");
  await service.trace("w1", "u-9");
  await service.eventLog();
  await service.eventLog(80);
  await service.notifications();
  await service.notifications(12, 30);
  await service.brain("w1");
  await service.reports("w1");
  assert.deepEqual(calls, [
    "/api/v1/skills",
    "/api/v1/mcp",
    "/api/v1/workspaces/w1/tasks/history",
    "/api/v1/workspaces/w1/observe/provenance",
    "/api/v1/workspaces/w1/observe/trace",
    "/api/v1/workspaces/w1/observe/trace?unit=u-9",
    "/api/v1/events/log?tail=200",
    "/api/v1/events/log?tail=80",
    "/api/v1/notifications?since=0&limit=100",
    "/api/v1/notifications?since=12&limit=30",
    "/api/v1/workspaces/w1/brain",
    "/api/v1/workspaces/w1/reports",
  ]);
});

test("observe：技能启停走 PATCH（M7 #5）", async () => {
  const calls: string[] = [];
  let seen: unknown = null;
  const service = createObserveService({
    rest: fakeRest((method, path, body) => {
      calls.push(`${method} ${path}`); seen = body; return {};
    }),
    commands: createCommandBus(),
  });
  await service.skillSetEnabled("demo", false);
  assert.deepEqual(calls, ["PATCH /api/v1/skills/demo"]);
  assert.deepEqual(seen, { enabled: false });
});

test("observe：失败经命令总线可见（不静默）", async () => {
  const failures: string[] = [];
  const service = createObserveService({
    rest: fakeRest(() => { throw new Error("boom"); }),
    commands: createCommandBus((e) => { failures.push(e.name); }),
  });
  await assert.rejects(() => service.taskHistory("w1"));
  assert.deepEqual(failures, ["observe.tasks.history"]);
});

test("observe：技能/MCP 管理端点（detail/install/remove/discover/reload）", async () => {
  const calls: Array<{ method: string; path: string; body?: unknown }> = [];
  const service = createObserveService({
    rest: fakeRest((method, path, body) => {
      calls.push({ method, path, ...(body === undefined ? {} : { body }) });
      return {};
    }),
    commands: createCommandBus(),
  });
  await service.skillDetail("演示 技能");
  await service.skillInstall("demo", "描述", "---\n---\n");
  await service.skillRemove("demo");
  await service.skillDiscover("找技能");
  await service.mcpReload();
  assert.deepEqual(calls, [
    { method: "GET", path: "/api/v1/skills/%E6%BC%94%E7%A4%BA%20%E6%8A%80%E8%83%BD" },
    {
      method: "POST", path: "/api/v1/skills/install",
      body: { name: "demo", description: "描述", content: "---\n---\n" },
    },
    { method: "DELETE", path: "/api/v1/skills/demo" },
    { method: "POST", path: "/api/v1/skills/discover", body: { goal: "找技能" } },
    { method: "POST", path: "/api/v1/mcp/reload", body: {} },
  ]);
});

test("observe：全库搜索（任务+会话，查询转义）", async () => {
  const calls: Array<{ method: string; path: string }> = [];
  const service = createObserveService({
    rest: fakeRest((method, path) => { calls.push({ method, path }); return {}; }),
    commands: createCommandBus(),
  });
  await service.search("变更 摘要");
  assert.deepEqual(calls, [{
    method: "GET",
    path: "/api/v1/search?q=%E5%8F%98%E6%9B%B4%20%E6%91%98%E8%A6%81",
  }]);
});

test("observe：浏览器允许条目 列表/撤销（O2-2 P3）", async () => {
  const calls: string[] = [];
  let seen: unknown = null;
  const service = createObserveService({
    rest: fakeRest((method, path, body) => {
      calls.push(`${method} ${path}`);
      seen = body;
      return {};
    }),
    commands: createCommandBus(),
  });
  await service.browserAllow();
  await service.browserAllowRevoke("127.0.0.1:8899", "fp-1");
  assert.deepEqual(calls, [
    "GET /api/v1/browser/allow",
    "POST /api/v1/browser/allow/revoke",
  ]);
  assert.deepEqual(seen, { address: "127.0.0.1:8899", fingerprint: "fp-1",
                           kind: "loopback" });
  // §11.5-③：LAN 条目撤销（kind 透传）
  await service.browserAllowRevoke("192.168.1.10:8000", "", "lan");
  assert.deepEqual(seen, { address: "192.168.1.10:8000", fingerprint: "",
                           kind: "lan" });
});

test("observe：域提示词 列表/保存（重大优化清单 #3）", async () => {
  const calls: string[] = [];
  let seen: unknown = null;
  const service = createObserveService({
    rest: fakeRest((method, path, body) => {
      calls.push(`${method} ${path}`);
      seen = body;
      return { entries: [], problems: [] };
    }),
    commands: createCommandBus(),
  });
  await service.domainPrompts("w1");
  await service.domainPromptsSave({ scope: "user", values: { plan: { notes: "x" } } });
  assert.deepEqual(calls, [
    "GET /api/v1/prompts/domains?ws=w1",
    "POST /api/v1/prompts/domains",
  ]);
  assert.deepEqual(seen, { scope: "user", values: { plan: { notes: "x" } } });
});

test("observe：浏览器身份 查看/清除（§11.5-①）", async () => {
  const calls: string[] = [];
  let seen: unknown = null;
  const service = createObserveService({
    rest: fakeRest((method, path, body) => {
      calls.push(`${method} ${path}`);
      seen = body;
      return { mode: "memory", current_key: "", entries: [], problems: [] };
    }),
    commands: createCommandBus(),
  });
  await service.browserIdentity("w1");
  await service.browserIdentityClear("wuxing-browser-x");
  assert.deepEqual(calls, [
    "GET /api/v1/browser/identity?ws=w1",
    "POST /api/v1/browser/identity/clear",
  ]);
  assert.deepEqual(seen, { key: "wuxing-browser-x" });
});
